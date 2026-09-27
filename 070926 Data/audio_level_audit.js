// Dependency-free audit of the WAV recordings used in the damping study.
// Reports per-channel AC RMS after removing each channel's DC offset, plus
// the distribution of one-second AC-RMS blocks. This is intended to catch
// mislabeled takes and recordings that contain different amounts of fan-on time.

const fs = require("fs");
const path = require("path");

function parseWav(filePath) {
  const buffer = fs.readFileSync(filePath);
  if (buffer.toString("ascii", 0, 4) !== "RIFF" ||
      buffer.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${filePath}: not a RIFF/WAVE file`);
  }

  let format;
  let dataOffset;
  let dataBytes;
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const id = buffer.toString("ascii", offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    const payload = offset + 8;
    if (id === "fmt ") {
      format = {
        audioFormat: buffer.readUInt16LE(payload),
        channels: buffer.readUInt16LE(payload + 2),
        sampleRate: buffer.readUInt32LE(payload + 4),
        bitsPerSample: buffer.readUInt16LE(payload + 14),
      };
    } else if (id === "data") {
      dataOffset = payload;
      dataBytes = Math.min(size, buffer.length - payload);
      break;
    }
    offset = payload + size + (size & 1);
  }

  if (!format || dataOffset === undefined) {
    throw new Error(`${filePath}: missing fmt or data chunk`);
  }
  if (format.audioFormat !== 1 || format.bitsPerSample !== 16) {
    throw new Error(`${filePath}: expected 16-bit PCM`);
  }
  return { buffer, dataOffset, dataBytes, ...format };
}

function percentile(sorted, fraction) {
  if (!sorted.length) return NaN;
  const index = (sorted.length - 1) * fraction;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  const weight = index - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function dbfs(rmsCounts) {
  return 20 * Math.log10(Math.max(rmsCounts / 32768, Number.EPSILON));
}

function acRmsForFrames(wav, firstFrame, frameCount, channel) {
  let sum = 0;
  let sumSquares = 0;
  const bytesPerFrame = wav.channels * 2;
  for (let i = 0; i < frameCount; i++) {
    const sampleOffset =
      wav.dataOffset + (firstFrame + i) * bytesPerFrame + channel * 2;
    const value = wav.buffer.readInt16LE(sampleOffset);
    sum += value;
    sumSquares += value * value;
  }
  const mean = sum / frameCount;
  const variance = Math.max(0, sumSquares / frameCount - mean * mean);
  return { mean, rms: Math.sqrt(variance) };
}

function audit(filePath) {
  const wav = parseWav(filePath);
  const bytesPerFrame = wav.channels * 2;
  const frames = Math.floor(wav.dataBytes / bytesPerFrame);
  const seconds = frames / wav.sampleRate;
  const channelRows = [];
  let interchannelCorrelation = NaN;

  for (let channel = 0; channel < wav.channels; channel++) {
    const whole = acRmsForFrames(wav, 0, frames, channel);
    const blocks = [];
    for (let start = 0; start + wav.sampleRate <= frames; start += wav.sampleRate) {
      const block = acRmsForFrames(wav, start, wav.sampleRate, channel);
      blocks.push(dbfs(block.rms));
    }
    blocks.sort((a, b) => a - b);
    channelRows.push({
      channel: channel + 1,
      meanCounts: whole.mean,
      acRmsDbfs: dbfs(whole.rms),
      blockMin: blocks[0],
      blockP10: percentile(blocks, 0.1),
      blockMedian: percentile(blocks, 0.5),
      blockP90: percentile(blocks, 0.9),
      blockMax: blocks[blocks.length - 1],
    });
  }
  if (wav.channels === 2) {
    const bytesPerFrame = wav.channels * 2;
    const mean0 = channelRows[0].meanCounts;
    const mean1 = channelRows[1].meanCounts;
    let covariance = 0;
    let energy0 = 0;
    let energy1 = 0;
    for (let i = 0; i < frames; i++) {
      const offset = wav.dataOffset + i * bytesPerFrame;
      const value0 = wav.buffer.readInt16LE(offset) - mean0;
      const value1 = wav.buffer.readInt16LE(offset + 2) - mean1;
      covariance += value0 * value1;
      energy0 += value0 * value0;
      energy1 += value1 * value1;
    }
    interchannelCorrelation = covariance / Math.sqrt(energy0 * energy1);
  }
  return {
    seconds,
    sampleRate: wav.sampleRate,
    channels: channelRows,
    interchannelCorrelation,
  };
}

const directory = process.argv[2] || __dirname;
const files = fs.readdirSync(directory)
  .filter((name) => /^REC_\d+\.WAV$/i.test(name))
  .sort();

console.log([
  "file", "duration_s", "channel", "dc_mean_counts", "whole_ac_rms_dbfs",
  "1s_min_dbfs", "1s_p10_dbfs", "1s_median_dbfs", "1s_p90_dbfs",
  "1s_max_dbfs", "interchannel_correlation",
].join(","));

for (const file of files) {
  const result = audit(path.join(directory, file));
  for (const row of result.channels) {
    console.log([
      file,
      result.seconds.toFixed(3),
      row.channel,
      row.meanCounts.toFixed(3),
      row.acRmsDbfs.toFixed(3),
      row.blockMin.toFixed(3),
      row.blockP10.toFixed(3),
      row.blockMedian.toFixed(3),
      row.blockP90.toFixed(3),
      row.blockMax.toFixed(3),
      Number.isFinite(result.interchannelCorrelation)
        ? result.interchannelCorrelation.toFixed(6)
        : "",
    ].join(","));
  }
}

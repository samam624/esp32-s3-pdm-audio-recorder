// Minimal 3MF (core spec) writer and reader. One file carries every printable
// body of a variant as a separate named object, already oriented and laid out
// on the bed, so a single drag-and-drop into Bambu Studio or OrcaSlicer is the
// whole print job.
import zlib from 'node:zlib';

const CONTENT_TYPES = '<?xml version="1.0" encoding="UTF-8"?>\n'
  + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
  + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
  + '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
  + '</Types>\n';

const RELS = '<?xml version="1.0" encoding="UTF-8"?>\n'
  + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
  + '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
  + 'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
  + '</Relationships>\n';

const MODEL_PATH = '3D/3dmodel.model';

function escapeXml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// OpenCascade meshes each face separately, so seam vertices are duplicated.
// 3MF expects an indexed mesh with shared vertices; weld on rounded position.
export function weldMesh({ vertices, triangles }) {
  const indexByKey = new Map();
  const welded = [];
  const remap = new Array(vertices.length / 3);
  for (let i = 0; i < vertices.length; i += 3) {
    const point = [vertices[i], vertices[i + 1], vertices[i + 2]].map((v) => Math.round(v * 1e6) / 1e6 + 0);
    const key = point.join(',');
    let index = indexByKey.get(key);
    if (index === undefined) {
      index = welded.length / 3;
      indexByKey.set(key, index);
      welded.push(...point);
    }
    remap[i / 3] = index;
  }
  return { vertices: welded, triangles: Array.from(triangles, (index) => remap[index]) };
}

export function meshStats({ vertices, triangles }) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < vertices.length; i += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis], vertices[i + axis]);
      max[axis] = Math.max(max[axis], vertices[i + axis]);
    }
  }
  const directed = new Map();
  let degenerateTriangles = 0;
  let signedVolume = 0;
  for (let t = 0; t < triangles.length; t += 3) {
    const ids = [triangles[t], triangles[t + 1], triangles[t + 2]];
    const [a, b, c] = ids.map((id) => [vertices[id * 3], vertices[id * 3 + 1], vertices[id * 3 + 2]]);
    const cross = [
      (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1]),
      (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]),
      (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]),
    ];
    if (Math.hypot(...cross) < 1e-9) degenerateTriangles += 1;
    signedVolume += (a[0] * cross[0] + a[1] * cross[1] + a[2] * cross[2]) / 6;
    for (const [from, to] of [[0, 1], [1, 2], [2, 0]]) {
      const key = `${ids[from]}>${ids[to]}`;
      directed.set(key, (directed.get(key) ?? 0) + 1);
    }
  }
  // Watertight and consistently wound: every directed edge appears exactly
  // once and is matched by exactly one opposite-direction edge.
  let nonManifoldEdges = 0;
  for (const [key, uses] of directed) {
    const [from, to] = key.split('>');
    if (uses !== 1 || directed.get(`${to}>${from}`) !== 1) nonManifoldEdges += 1;
  }
  return {
    vertexCount: vertices.length / 3,
    triangleCount: triangles.length / 3,
    min,
    max,
    signedVolume,
    degenerateTriangles,
    nonManifoldEdges,
    watertight: degenerateTriangles === 0 && nonManifoldEdges === 0 && signedVolume > 0,
  };
}

function modelXml(title, objects) {
  const parts = [
    '<?xml version="1.0" encoding="UTF-8"?>\n',
    '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n',
    ` <metadata name="Title">${escapeXml(title)}</metadata>\n`,
    ' <resources>\n',
  ];
  objects.forEach(({ name, vertices, triangles }, index) => {
    parts.push(`  <object id="${index + 1}" name="${escapeXml(name)}" type="model">\n   <mesh>\n    <vertices>\n`);
    for (let i = 0; i < vertices.length; i += 3) {
      parts.push(`     <vertex x="${vertices[i]}" y="${vertices[i + 1]}" z="${vertices[i + 2]}"/>\n`);
    }
    parts.push('    </vertices>\n    <triangles>\n');
    for (let t = 0; t < triangles.length; t += 3) {
      parts.push(`     <triangle v1="${triangles[t]}" v2="${triangles[t + 1]}" v3="${triangles[t + 2]}"/>\n`);
    }
    parts.push('    </triangles>\n   </mesh>\n  </object>\n');
  });
  parts.push(' </resources>\n <build>\n');
  objects.forEach((_, index) => parts.push(`  <item objectid="${index + 1}"/>\n`));
  parts.push(' </build>\n</model>\n');
  return parts.join('');
}

function zip(entries) {
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const [name, content] of entries) {
    const nameBytes = Buffer.from(name, 'utf8');
    const raw = Buffer.from(content, 'utf8');
    const data = zlib.deflateRawSync(raw, { level: 9 });
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0);
    header.writeUInt16LE(20, 4);
    header.writeUInt16LE(0x0800, 6);
    header.writeUInt16LE(8, 8);
    header.writeUInt16LE(0, 10);
    header.writeUInt16LE(0x0021, 12);
    header.writeUInt32LE(zlib.crc32(raw), 14);
    header.writeUInt32LE(data.length, 18);
    header.writeUInt32LE(raw.length, 22);
    header.writeUInt16LE(nameBytes.length, 26);
    const record = Buffer.alloc(46);
    record.writeUInt32LE(0x02014b50, 0);
    record.writeUInt16LE(20, 4);
    header.copy(record, 6, 4, 30);
    record.writeUInt32LE(offset, 42);
    chunks.push(header, nameBytes, data);
    central.push(record, nameBytes);
    offset += header.length + nameBytes.length + data.length;
  }
  const centralSize = central.reduce((total, chunk) => total + chunk.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...chunks, ...central, end]);
}

function unzipEntry(buffer, wanted) {
  const end = buffer.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  if (end < 0) throw new Error('Not a zip archive.');
  let cursor = buffer.readUInt32LE(end + 16);
  for (let entry = 0; entry < buffer.readUInt16LE(end + 10); entry += 1) {
    const nameLength = buffer.readUInt16LE(cursor + 28);
    const name = buffer.toString('utf8', cursor + 46, cursor + 46 + nameLength);
    if (name === wanted) {
      const compressedSize = buffer.readUInt32LE(cursor + 20);
      const local = buffer.readUInt32LE(cursor + 42);
      const start = local + 30 + buffer.readUInt16LE(local + 26) + buffer.readUInt16LE(local + 28);
      const data = buffer.subarray(start, start + compressedSize);
      const raw = buffer.readUInt16LE(cursor + 10) === 0 ? data : zlib.inflateRawSync(data);
      if (zlib.crc32(raw) !== buffer.readUInt32LE(cursor + 16)) throw new Error(`${wanted}: CRC mismatch.`);
      return raw;
    }
    cursor += 46 + nameLength + buffer.readUInt16LE(cursor + 30) + buffer.readUInt16LE(cursor + 32);
  }
  throw new Error(`${wanted} not found in archive.`);
}

// objects: [{ name, vertices: flat xyz[], triangles: flat index[] }]
export function buildThreeMf(title, objects) {
  return zip([
    ['[Content_Types].xml', CONTENT_TYPES],
    ['_rels/.rels', RELS],
    [MODEL_PATH, modelXml(title, objects)],
  ]);
}

export function readThreeMf(buffer) {
  const xml = unzipEntry(buffer, MODEL_PATH).toString('utf8');
  const objects = [];
  for (const [, name, body] of xml.matchAll(/<object id="\d+" name="([^"]*)" type="model">([\s\S]*?)<\/object>/g)) {
    const vertices = [];
    for (const [, x, y, z] of body.matchAll(/<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"\/>/g)) {
      vertices.push(Number(x), Number(y), Number(z));
    }
    const triangles = [];
    for (const [, a, b, c] of body.matchAll(/<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"\/>/g)) {
      triangles.push(Number(a), Number(b), Number(c));
    }
    objects.push({ name, vertices, triangles });
  }
  return objects;
}

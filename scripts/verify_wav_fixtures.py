"""Verify the checked-in WAV evidence using only Python's standard library."""

from pathlib import Path
import wave


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = [
    ROOT / "bench_tests" / "REC_00001.WAV",
    ROOT / "bench_tests" / "REC_00002.WAV",
]


def main() -> None:
    for path in FIXTURES:
        if not path.is_file():
            raise SystemExit(f"FAIL missing WAV fixture: {path.relative_to(ROOT)}")
        with wave.open(str(path), "rb") as audio:
            actual = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
            expected = (2, 2, 48_000)
            if actual != expected:
                raise SystemExit(
                    f"FAIL {path.name}: expected channels/bytes/rate {expected}, got {actual}"
                )
            if audio.getnframes() <= 0:
                raise SystemExit(f"FAIL {path.name}: no audio frames")
            duration = audio.getnframes() / audio.getframerate()
            print(f"PASS {path.relative_to(ROOT)}: 48 kHz stereo 16-bit, {duration:.2f} s")


if __name__ == "__main__":
    main()

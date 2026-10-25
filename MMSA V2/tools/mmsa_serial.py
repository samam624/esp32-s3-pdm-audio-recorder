"""Shared helper for the MMSA V2 recorder's USB serial port (used by stress_test.py and soak_log.py).

Board(port) opens the port WITHOUT resetting the chip, reads every line in a background thread (timestamped, and
optionally written to a log file), and offers send(), wait_for(), health() and reset(). If the port drops (USB
unplugged, PC asleep), it keeps trying to reopen it.
"""
from __future__ import annotations

import re
import threading
import time

import serial

# Lines the idle firmware prints every 2 s; kept in the log but not echoed.
NOISY = ("signal dBFS", "    DC:")

BLE_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_CONTROL = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write 1 = start, 0 = stop, 2 = toggle
BLE_STATUS = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
BLE_NAME = "MMSA V2"


def parse_health(line: str) -> dict:
    """'HEALTH: up=12 rec=0 ...' -> {'up': 12, 'rec': 0, ...}"""
    out = {}
    for k, v in re.findall(r"(\w+)=(-?[\d.]+)", line):
        out[k] = float(v) if "." in v else int(v)
    return out


def parse_status(v: bytes) -> dict:
    """The recorder's Bluetooth status payload (12 bytes, or 16 with the recording's total seconds)."""
    d = {
        "len": len(v),
        "recording": bool(v[0] & 0x01),
        "sd_ready": bool(v[0] & 0x02),
        "low_space": bool(v[0] & 0x04),
        "error": v[9] if v[0] & 0x08 else 0,
        "file_bytes": int.from_bytes(v[1:5], "little"),
        "free_mb": int.from_bytes(v[5:9], "little"),
    }
    if len(v) >= 16:
        d["rec_secs"] = int.from_bytes(v[12:16], "little")
    return d


class Board:
    def __init__(self, port: str, log_path: str | None = None, echo: bool = True, echo_filter=None):
        self.port = port
        self.lines: list[tuple[float, str]] = []
        self.echo = echo
        self.echo_filter = echo_filter or (lambda text: not text.startswith(NOISY))
        self.log = open(log_path, "a", encoding="utf-8", buffering=1) if log_path else None
        self._lock = threading.Lock()
        self._paused = False
        self._stop = False
        self.ser = None
        self.port_drops = 0
        self._open_quiet()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    # ---- port handling ----
    def _open_quiet(self, tries: int = 40) -> bool:
        for _ in range(tries):
            try:
                s = serial.Serial()
                s.port, s.baudrate, s.timeout = self.port, 115200, 0.2
                s.rts = False  # RTS resets the chip on the ESP32-S3 USB serial/JTAG port
                s.dtr = True
                s.open()
                self.ser = s
                return True
            except Exception:
                time.sleep(0.5)
        return False

    def _reader(self):
        buf = b""
        while not self._stop:
            if self._paused or self.ser is None:
                time.sleep(0.05)
                continue
            try:
                d = self.ser.read(4096)
            except Exception:
                self.note("port lost; reopening")
                self.port_drops += 1
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                while not self._stop and not self._paused and not self._open_quiet(tries=1):
                    time.sleep(1)
                if self.ser is not None:
                    self.note("port reopened")
                continue
            if not d:
                continue
            buf += d
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._add(raw.decode(errors="replace").rstrip("\r"))

    def _add(self, text: str, mark: str = ""):
        t = time.time()
        with self._lock:
            self.lines.append((t, text))
        if self.log:
            self.log.write(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d} "
                           + mark + text + "\n")
        if self.echo and (mark or self.echo_filter(text)):
            print(time.strftime("%H:%M:%S ", time.localtime(t)) + mark + text, flush=True)

    def note(self, text: str):
        """A line from the PC side, logged with a '##' prefix."""
        self._add(text, mark="## ")

    def close(self):
        self._stop = True
        time.sleep(0.3)
        try:
            self.ser.close()
        except Exception:
            pass
        if self.log:
            self.log.close()

    # ---- commands ----
    def send(self, chars: str):
        for _ in range(20):
            try:
                self.ser.write(chars.encode())
                return
            except Exception:
                time.sleep(0.5)
        self.note(f"could not send {chars!r}")

    def mark(self) -> int:
        with self._lock:
            return len(self.lines)

    def since(self, mark: int) -> list[str]:
        with self._lock:
            return [t for _, t in self.lines[mark:]]

    def wait_for(self, pattern: str, timeout: float, mark: int | None = None):
        """Wait for a line matching `pattern` (regex) after `mark`; returns the match or None."""
        rx = re.compile(pattern)
        start = self.mark() if mark is None else mark
        end = time.time() + timeout
        seen = start
        while True:
            with self._lock:
                new = self.lines[seen:]
                seen = len(self.lines)
            for _, text in new:
                m = rx.search(text)
                if m:
                    return m
            if time.time() >= end:
                return None
            time.sleep(0.05)

    def health(self, timeout: float = 3) -> dict | None:
        m0 = self.mark()
        self.send("h")
        m = self.wait_for(r"^HEALTH: .*", timeout, m0)
        return parse_health(m.group(0)) if m else None

    def reset(self):
        """Hard-reset the chip (the DTR/RTS sequence of tools/serial_reset_log.py), then reopen quietly."""
        self._paused = True
        time.sleep(0.2)
        try:
            self.ser.close()
        except Exception:
            pass
        s = serial.Serial(self.port, 115200, timeout=0.3)
        s.dtr = False
        s.rts = True
        time.sleep(0.1)
        s.rts = False
        s.close()
        self.note("board reset (DTR/RTS)")
        self._open_quiet()
        self._paused = False

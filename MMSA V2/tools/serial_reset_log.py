import serial, time, sys
secs = float(sys.argv[1])
s = serial.Serial("COM5", 115200, timeout=0.3)
# Reset the ESP32-S3 via the USB-Serial/JTAG DTR/RTS sequence so we catch boot output.
s.dtr = False; s.rts = True; time.sleep(0.1); s.rts = False; s.close()
for _ in range(20):
    try:
        s = serial.Serial("COM5", 115200, timeout=0.3); break
    except Exception:
        time.sleep(0.3)
s.dtr = True
end = time.time() + secs
while time.time() < end:
    d = s.read(1024)
    if d: sys.stdout.write(d.decode(errors="replace")); sys.stdout.flush()

import serial, time, sys
for attempt in range(10):
    try:
        s = serial.Serial("COM5", 115200, timeout=0.5); break
    except Exception as e:
        time.sleep(1)
else:
    sys.exit("could not open COM5")
s.dtr = True
end = time.time() + float(sys.argv[1]) if len(sys.argv)>1 else time.time()+14
while time.time() < end:
    d = s.read(512)
    if d: sys.stdout.write(d.decode(errors="replace")); sys.stdout.flush()

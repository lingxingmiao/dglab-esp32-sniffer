"""Continuously capture ESP32 fake DG-LAB serial output to a log file."""
import serial, time, sys, os

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dglab_capture.log')
port = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('DGLAB_SERIAL_PORT', 'COM4')

with open(LOG, 'a', encoding='utf-8') as f:
    f.write(f"\n===== capture start {time.strftime('%Y-%m-%d %H:%M:%S')} port={port} =====\n")
    f.flush()
    s = serial.Serial(port, 115200, timeout=1)
    # reset ESP32 to catch boot banner
    s.dtr = False
    s.rts = True
    time.sleep(0.1)
    s.rts = False
    s.reset_input_buffer()
    print(f"capturing {port} -> {LOG}", flush=True)
    t0 = time.time()
    try:
        while True:
            line = s.readline()
            if line:
                text = line.decode('utf-8', 'replace').rstrip()
                stamp = time.strftime('%H:%M:%S')
                out = f"[{stamp}] {text}"
                print(out, flush=True)
                f.write(out + "\n")
                f.flush()
    except KeyboardInterrupt:
        pass
    finally:
        s.close()

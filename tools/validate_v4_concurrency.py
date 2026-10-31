#!/usr/bin/env python3
import subprocess,sys,time
start=time.monotonic()
cmd=[sys.executable,"-m","pytest","-q","tests/test_v4_concurrency_writer_isolation_v0114823.py"]
p=subprocess.run(cmd)
elapsed=time.monotonic()-start
print(f"[v4] wall {elapsed:.2f}s")
raise SystemExit(p.returncode)

"""Logs outbound connectivity every 60 s to runs/logs/hosted__net.jsonl (new HTTPS connection to two hosts, and
the number of established connections), to see whether the hosted runs choke this PC's network."""
import json
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "runs" / "logs" / "hosted__net.jsonl"
while True:
    ev = {"time": datetime.now().isoformat(timespec="seconds")}
    for name, url in (("google", "https://www.google.com"), ("openrouter", "https://openrouter.ai/api/v1/models")):
        t = time.time()
        try:
            urllib.request.urlopen(url, timeout=20).read(100)
            ev[name] = round(time.time() - t, 2)
        except Exception as e:
            ev[name] = f"FAIL {type(e).__name__}"
    out = subprocess.run(["netstat", "-an"], capture_output=True, text=True).stdout
    ev["established"] = out.count("ESTABLISHED")
    ev["time_wait"] = out.count("TIME_WAIT")
    with LOG.open("a") as f:
        f.write(json.dumps(ev) + "\n")
    time.sleep(60)

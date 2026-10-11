"""Poll adsb.lol /v2/point around Manhattan; append raw snapshots as JSONL.
Usage: python poll_adsblol.py MINUTES INTERVAL_S"""
import json, sys, time, urllib.request
URL = "https://api.adsb.lol/v2/point/40.75/-73.95/20"  # 20 nm radius
mins, iv = float(sys.argv[1]), float(sys.argv[2])
end = time.time() + mins*60
with open("data/adsblol_snapshots.jsonl", "a") as f:
    while time.time() < end:
        t0 = time.time()
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": "landed-hackathon-eda"})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            f.write(json.dumps({"poll_ts": t0, **d}) + "\n"); f.flush()
        except Exception as e:
            f.write(json.dumps({"poll_ts": t0, "error": str(e)}) + "\n"); f.flush()
        time.sleep(max(0, iv - (time.time() - t0)))

"""Stream adsb.lol globe_history daily release (tar split in parts) from stdin and keep
only aircraft traces that pass through the NYC box. Writes data/history_nyc_traces.jsonl.
Trace format (readsb trace_full): {icao, r, t, desc, timestamp, trace:[[dt, lat, lon, alt, gs, track, flags, vrate, aircraft{}, ...]]}"""
import gzip, json, sys, tarfile
LAT=(40.55,40.95); LON=(-74.25,-73.70)
out=open("data/history_nyc_traces.jsonl","w"); n=k=0
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as tf:
    for m in tf:
        if not m.isfile() or "trace_full" not in m.name: continue
        n+=1
        raw=tf.extractfile(m).read()
        try:
            d=json.loads(gzip.decompress(raw) if raw[:2]==b"\x1f\x8b" else raw)
        except Exception: continue
        pts=[p for p in d.get("trace",[]) if p[1] is not None and LAT[0]<=p[1]<=LAT[1] and LON[0]<=p[2]<=LON[1]]
        if not pts: continue
        k+=1
        # keep NYC points only plus per-point aircraft meta (category/flight) when present
        out.write(json.dumps({"icao":d.get("icao"),"r":d.get("r"),"t":d.get("t"),"desc":d.get("desc"),
                              "base_ts":d.get("timestamp"),"pts":pts})+"\n")
        if n%20000==0: print(n,k,flush=True)
print("done",n,k,flush=True)

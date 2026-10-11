"""Play hand-written ParsedTransmission fixtures for S1, S2 and S5 against a running server.

Usage (server must be running; see server/README in the final report):
    uv run --project server python server/scripts/play_scenario.py S1 S2 S5 [--base http://127.0.0.1:8787] [--pause 1.5]

Prints, for each call, the proposal tier/status, the exact words, and the round-trip latency
(transmission POSTed -> audio ready and fetchable). SIMULATION ONLY. Fixtures use fictional registrations.
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Any

import httpx

ROSTER = ["N2646X", "N312LM", "N405LP"]
JRB = (40.701214, -74.009028)
BROOKLYN = (40.7061, -73.9969)
E34 = (40.742447, -73.972122)


def parsed(text: str, reg: str | None, *, asr: float, parse: float, intent: str = "checkin",
           emergency: bool = False, snap: float = 0.95, **slots: Any) -> dict[str, Any]:  # fmt: skip
    return {
        "raw_text": text,
        "asr_confidence": asr,
        "callsign": {
            "spoken": text.split(",")[0],
            "normalized": reg,
            "snapped_to": reg,
            "snap_score": snap,
            "ambiguous_with": [],
        },
        "intent": intent,
        "slots": slots,
        "emergency": emergency,
        "parse_confidence": parse,
        "parser": "grammar",
        "reason": f"grammar parse, ASR {asr:.2f}",
    }


class Runner:
    def __init__(self, base: str, pause: float):
        self.c = httpx.Client(base_url=base, timeout=60)
        self.pause = pause
        self.timings: list[tuple[str, str, float, int | None]] = []

    def adsb(self, reg: str, pos: tuple[float, float], alt: float, squawk: str | None = None) -> None:
        self.c.post(
            "/adsb", json={"reg": reg, "lat": pos[0], "lon": pos[1], "alt_ft": alt, "squawk": squawk}
        ).raise_for_status()

    def say(self, label: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        r = self.c.post("/transmission", json=body)
        r.raise_for_status()
        props = r.json()["proposals"]
        # "audio ready": for policy-cleared speech, fetch the audio the browser would play
        for p in props:
            if p["status"] in ("auto_spoken", "handoff_spoken"):
                self.c.get(f"/tts/{p['id']}").raise_for_status()
        rt = (time.perf_counter() - t0) * 1000
        self.show(label, body["raw_text"], props, rt)
        return props

    def alerts(self, label: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        t0 = time.perf_counter()
        r = self.c.post("/alerts", json=alerts)
        r.raise_for_status()
        props = r.json()["proposals"]
        for p in props:
            if p["status"] in ("auto_spoken", "handoff_spoken"):
                self.c.get(f"/tts/{p['id']}").raise_for_status()
        self.show(label, "(engine alert)", props, (time.perf_counter() - t0) * 1000)
        return props

    def show(self, label: str, heard: str, props: list[dict[str, Any]], rt_ms: float) -> None:
        print(f"\n[{label}] pilot: {heard}")
        if not props:
            print("   (no proposal)")
        for p in props:
            print(
                f"   -> {p['tier']:<10} {p['status']:<15} conf {p['confidence']:.2f}  triggers={p['triggers']}"
            )
            print(f'      "{p["spoken_text_preview"]}"')
            if p["tier"] != "suppressed":
                self.timings.append((label, p["tier"], rt_ms, p["latency_ms"]))
        print(f"   round trip {rt_ms:.0f} ms (server {props[0]['latency_ms'] if props else '-'} ms)")
        time.sleep(self.pause)

    def start(self, traffic: list[dict[str, Any]] | None = None) -> None:
        self.c.post("/reset").raise_for_status()
        self.c.post(
            "/desk", json={"roster": ROSTER, "altimeter_inhg": 29.92, "traffic": traffic or []}
        ).raise_for_status()


def s1(r: Runner) -> None:
    print("\n=== S1: clean autonomous, JRB -> E 34th via the East River ===")
    r.start(traffic=[{"clock": 3, "distance_nm": 2.0, "traffic_type": "helicopter", "altitude_ft": 700}])
    r.adsb("N2646X", JRB, 300)
    r.say("S1 T+0 check-in", parsed("Landed desk, MEDEVAC Two Six Four Six X-Ray, Downtown Skyport, lifting, East River northbound, five hundred",
                                    "N2646X", asr=0.97, parse=0.98, position="Downtown Skyport", corridor="East River",
                                    direction="northbound", altitude_ft=500))  # fmt: skip
    r.adsb("N2646X", BROOKLYN, 500)
    r.say("S1 T+40s", parsed("MEDEVAC Two Six Four Six X-Ray, Brooklyn Bridge, five hundred", "N2646X", asr=0.97, parse=0.98,
                             intent="position_report", position="Brooklyn Bridge", altitude_ft=500))  # fmt: skip
    r.adsb("N2646X", E34, 500)
    r.say("S1 T+2min", parsed("MEDEVAC Two Six Four Six X-Ray, East 34th, five hundred, landing East 34th", "N2646X", asr=0.96,
                              parse=0.97, intent="position_report", position="East 34th Street", altitude_ft=500))  # fmt: skip


def s2(r: Runner) -> None:
    print("\n=== S2: route crosses the LGA 22 final (College Point area at 600 ft): hand off ===")
    r.start()
    r.adsb("N312LM", E34, 600)
    r.alerts("S2 engine alert", [{
        "id": "SIM312LM", "aircraft": {"hex": "SIM312LM", "reg": "N312LM"}, "volume_id": "lga_22_final", "severity": "handoff",
        "confidence": 0.88, "reason": "Projected path enters LGA Rwy 22 final protected volume in 70 s at 600 ft",
        "time_to_entry_s": 70, "entry_alt_ft": 600, "also_volumes": [],
    }])  # fmt: skip
    r.say("S2 pilot request", parsed("MEDEVAC Three One Two Lima Mike, East 34th, request direct College Point area, six hundred",
                                     "N312LM", asr=0.94, parse=0.96, intent="request_route", position="East 34th Street",
                                     altitude_ft=600, destination="College Point area"))  # fmt: skip


def s5(r: Runner) -> None:
    print("\n=== S5: MAYDAY -> one transmission, then locked silent ===")
    r.start()
    r.adsb("N312LM", E34, 500)
    r.say("S5 MAYDAY", parsed("MAYDAY MAYDAY MAYDAY, MEDEVAC Three One Two Lima Mike, engine chip light, landing East 34th immediately",
                              "N312LM", asr=0.9, parse=0.95, intent="emergency", emergency=True, squawk="7700"))  # fmt: skip
    r.say("S5 follow-up (must stay silent)", parsed("MEDEVAC Three One Two Lima Mike, still inbound East 34th", "N312LM", asr=0.95,
                                                    parse=0.97, intent="position_report", position="East 34th Street"))  # fmt: skip


def a1(r: Runner) -> None:
    print("\n=== A1: approval tier (0.5-0.8 confidence): a card, nothing spoken until A ===")
    r.start()
    r.adsb("N2646X", JRB, 300)
    r.say("A1 mid-confidence check-in", parsed("Landed desk, MEDEVAC Two Six Four Six X-Ray, Downtown Skyport, lifting, five hundred",
                                               "N2646X", asr=0.76, parse=0.92, position="Downtown Skyport", altitude_ft=500))  # fmt: skip


SCENARIOS = {"S1": s1, "S2": s2, "S5": s5, "A1": a1}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=["S1", "S2", "S5"])
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--pause", type=float, default=1.5)
    ap.add_argument(
        "--repeat", type=int, default=1, help="run the list N times (run 2+ shows warm-cache latency)"
    )
    a = ap.parse_args()
    r = Runner(a.base, a.pause)
    print("SIMULATION: no real frequency is used. Server health:", r.c.get("/health").json())
    for i in range(a.repeat):
        print(f"\n######## pass {i + 1}")
        for name in a.scenarios:
            SCENARIOS[name.upper()](r)
    auto = [t for t in r.timings if t[1] in ("auto", "handoff", "emergency")]
    if auto:
        rts = sorted(t[2] for t in auto)
        print(f"\nLatency (transmission in -> audio ready), n={len(rts)}: median {statistics.median(rts):.0f} ms, "
              f"min {rts[0]:.0f}, max {rts[-1]:.0f}")  # fmt: skip


if __name__ == "__main__":
    main()

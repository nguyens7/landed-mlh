"""Scenario-side geometry checks that the TypeScript conflict engine does not (yet) produce.

These are the SPEC section 2.2 "listener and safety checks" that depend only on the ADS-B track:

* ``shoreline_rule``  - Hudson lane rule (west shoreline southbound, east shoreline northbound), S3 variant B.
* ``position_match``  - which target is actually at the reported position (S4 card: "ADS-B position match 0.9").
* ``squawk_emergency``- squawk 7700/7600/7500 appears on a track (S5).
* ``desk_count``      - how many desk helicopters are airborne (S6 volume cap).

They are stand-ins until the app engine emits the same alerts; the expected values live in the scenario YAML so
the integrator can point the real engine at the same expectations.

Calibration note (Hudson centerline): the Track B ``sfra_hudson`` polygon is an approximation whose edges are not
parallel to the river, so a fixed fraction of its width is not a stable "east or west of centre" test. The centre
line below is calibrated from the real Saturday replay (per-latitude mid-range of the 17 helicopters' lanes inside
the polygon) and is only used to decide which shoreline a southbound helicopter is hugging.
"""

from __future__ import annotations

import math

# isort: split
from landed_geo import great_circle_dist_nm

import scn_geo
import scn_tracks

HUDSON_CENTER = [
    (40.68, -74.0336),
    (40.70, -74.0264),
    (40.72, -74.0224),
    (40.74, -74.0185),
    (40.76, -74.0083),
    (40.78, -73.9930),
    (40.80, -73.9850),
]
LANE_TOLERANCE_NM = 0.15  # beyond this on the wrong side of the centre line = wrong shoreline
SUSTAIN_S = 15.0  # must persist this long before an alert
DEPTH_REFERENCE_NM = 0.15  # offset beyond the tolerance that maps to depth score 1.0
STABILITY_REFERENCE_DEG = 60.0
OPPOSING_DELTA_DEG = 120.0


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def hudson_center_lon(lat: float) -> float | None:
    for (a, la), (b, lb) in zip(HUDSON_CENTER, HUDSON_CENTER[1:]):
        if a <= lat <= b:
            return la + (lat - a) / (b - a) * (lb - la)
    return None


def hudson_offset_east_nm(lat: float, lon: float) -> float | None:
    """Signed distance (nm, + = east of the calibrated centre line); None outside the table's latitude range."""
    c = hudson_center_lon(lat)
    if c is None:
        return None
    return (lon - c) * 60 * math.cos(math.radians(lat))


def _heading_std(hs: list[float]) -> float:
    if len(hs) < 2:
        return 0.0
    ms = sum(math.sin(math.radians(h)) for h in hs) / len(hs)
    mc = sum(math.cos(math.radians(h)) for h in hs) / len(hs)
    return math.degrees(math.sqrt(max(0.0, 1 - math.hypot(ms, mc)) * 2))


def _direction(track_deg: float) -> str | None:
    if abs(((track_deg - 180 + 180) % 360) - 180) <= 60:
        return "southbound"
    if min(track_deg, 360 - track_deg) <= 60:
        return "northbound"
    return None


def shoreline_rule(tracks: dict, reg: str, step_s: float = 1.0) -> list[dict]:
    """Alerts for ``reg`` when it holds the wrong Hudson shoreline for SUSTAIN_S seconds."""
    ac = next(a for a in tracks["aircraft"] if a["reg"] == reg)
    pts = ac["points"]
    out: list[dict] = []
    wrong_since: float | None = None
    t = pts[0]["t"]
    while t <= pts[-1]["t"]:
        pos = scn_tracks.position_at(ac, t)
        i = max(j for j, p in enumerate(pts) if p["t"] <= t)
        track = pts[i]["track_deg"]
        direction = _direction(track)
        off = hudson_offset_east_nm(pos[0], pos[1]) if pos else None
        wrong = False
        depth_nm = 0.0
        if off is not None and direction == "southbound" and off > LANE_TOLERANCE_NM:
            wrong, depth_nm = True, off - LANE_TOLERANCE_NM
        if off is not None and direction == "northbound" and off < -LANE_TOLERANCE_NM:
            wrong, depth_nm = True, -off - LANE_TOLERANCE_NM
        if wrong:
            wrong_since = t if wrong_since is None else wrong_since
            if t - wrong_since >= SUSTAIN_S and not out:
                hist = [p["track_deg"] for p in pts[max(0, i - 4) : i + 1]]
                conf = clamp01(
                    0.5 * clamp01(depth_nm / DEPTH_REFERENCE_NM)
                    + 0.3 * clamp01(1 - _heading_std(hist) / STABILITY_REFERENCE_DEG)
                    + 0.2 * 1.0
                )
                opp = opposing_traffic(tracks, reg, t)
                out.append(
                    {
                        "kind": "shoreline",
                        "reg": reg,
                        "volume_id": "sfra_hudson",
                        "severity": "caution",
                        "confidence": round(conf, 4),
                        "first_seen_t": t,
                        "direction": direction,
                        "offset_east_nm": round(off, 3),
                        "opposing_traffic": opp,
                        "reason": (
                            f"{reg}: {direction} aircraft on the {'east' if direction == 'southbound' else 'west'} "
                            f"shoreline ({abs(off):.2f} nm {'east' if off > 0 else 'west'} of the Hudson centre line, "
                            f"{wrong_since:.0f}-{t:.0f} s)"
                            + (f"; opposing traffic {opp['reg']} {opp['nm']:.1f} nm" if opp else "")
                            + "."
                        ),
                    }
                )
        else:
            wrong_since = None
        t += step_s
    return out


def opposing_traffic(tracks: dict, reg: str, t: float) -> dict | None:
    me = next(a for a in tracks["aircraft"] if a["reg"] == reg)
    p0 = scn_tracks.position_at(me, t)
    if p0 is None:
        return None
    my_track = next(p["track_deg"] for p in reversed(me["points"]) if p["t"] <= t)
    best: dict | None = None
    for other in tracks["aircraft"]:
        if other["reg"] == reg:
            continue
        p1 = scn_tracks.position_at(other, t)
        if p1 is None:
            continue
        o_track = next(p["track_deg"] for p in reversed(other["points"]) if p["t"] <= t)
        delta = abs(((o_track - my_track) + 180) % 360 - 180)
        if delta < OPPOSING_DELTA_DEG:
            continue
        d = great_circle_dist_nm(p0[0], p0[1], p1[0], p1[1])
        if best is None or d < best["nm"]:
            best = {"reg": other["reg"], "nm": round(d, 2)}
    return best


def position_match(tracks: dict, reported: str, t: float) -> dict:
    """Rank desk aircraft by distance to the reported place at time ``t``. score = 1 - d / 1 nm."""
    ref = scn_geo.reference_points()[reported]
    ranked = []
    for a in tracks["aircraft"]:
        p = scn_tracks.position_at(a, t)
        if p is None:
            continue
        d = great_circle_dist_nm(p[0], p[1], *ref)
        ranked.append({"reg": a["reg"], "nm": round(d, 3), "score": round(clamp01(1 - d / 1.0), 3)})
    ranked.sort(key=lambda r: r["nm"])
    best = ranked[0] if ranked else None
    unique = bool(best) and (len(ranked) == 1 or ranked[1]["nm"] > 1.0)
    return {"best": best, "unique": unique, "ranked": ranked}


def squawk_emergency(tracks: dict, reg: str) -> list[dict]:
    ac = next(a for a in tracks["aircraft"] if a["reg"] == reg)
    return [
        {"t": s["t"], "code": s["code"]}
        for s in ac.get("squawk", [])
        if s["code"] in {"7700", "7600", "7500"}
    ]


def desk_count(tracks: dict, t: float) -> dict:
    airborne = [
        a["reg"]
        for a in tracks["aircraft"]
        if a.get("desk", True) and scn_tracks.position_at(a, t) is not None
    ]
    return {"count": len(airborne), "regs": airborne}

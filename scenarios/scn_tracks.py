"""Generate replay-format tracks for a scenario with replay/landed_timing.route_positions (never by hand)."""

from __future__ import annotations

# isort: split
from landed_geo import great_circle_dist_nm
from landed_timing import route_positions

import scn_geo
from scn_model import Scenario, SimAircraft, Waypoint

STEP_S = 2.0  # same sampling as replay/build_replay.py DOWNSAMPLE_S


# ------------------------------------------------------------------ Hudson lane geometry
def hudson_cross_section(lat: float) -> tuple[float, float]:
    """(west_lon, east_lon) of the sfra_hudson polygon at ``lat``."""
    ring = scn_geo.corridors()["sfra_hudson"]["ring"]
    xs: list[float] = []
    for (lo1, la1), (lo2, la2) in zip(ring, ring[1:]):
        if (la1 - lat) * (la2 - lat) <= 0 and la1 != la2:
            xs.append(lo1 + (lat - la1) * (lo2 - lo1) / (la2 - la1))
    if len(xs) < 2:
        raise ValueError(f"lat {lat} is outside the Hudson polygon")
    return min(xs), max(xs)


def hudson_frac_at(lat: float, lon: float) -> float:
    w, e = hudson_cross_section(lat)
    return (lon - w) / (e - w)


def hudson_lon(lat: float, frac: float) -> float:
    w, e = hudson_cross_section(lat)
    return w + frac * (e - w)


def resolve_waypoint(wp: Waypoint) -> tuple[float, float]:
    if wp.ref:
        return scn_geo.reference_points()[wp.ref]
    assert wp.lat is not None
    if wp.lon is not None:
        return wp.lat, wp.lon
    assert wp.hudson_frac is not None
    return wp.lat, hudson_lon(wp.lat, wp.hudson_frac)


def resolve_route(ac: SimAircraft) -> list[tuple[float, float]]:
    return [resolve_waypoint(w) for w in ac.route]


def route_length_nm(route: list[tuple[float, float]]) -> float:
    return sum(great_circle_dist_nm(*a, *b) for a, b in zip(route, route[1:]))


# ------------------------------------------------------------------ track generation
def raw_samples(ac: SimAircraft) -> list[dict]:
    return route_positions(
        route=resolve_route(ac),
        climb_time_s=0.0 if ac.airborne else (ac.cruise_alt_ft / ac.climb_fpm) * 60.0,
        cruise_alt_ft=ac.cruise_alt_ft,
        cruise_kt=ac.cruise_kt,
        step_s=STEP_S,
    )


def liftoff_for(ac: SimAircraft, samples: list[dict]) -> float:
    if ac.align_entry is None:
        return ac.liftoff_t
    pts = [{"t": s["t"], "lat": s["lat"], "lon": s["lon"], "alt_ft": s["alt_ft"]} for s in samples]
    found = scn_geo.first_entry(pts, ac.align_entry.volume_prefix)
    if found is None:
        raise RuntimeError(f"{ac.reg}: track never enters {ac.align_entry.volume_prefix}")
    return max(5.0, ac.align_entry.t - found[0]["t"])


def build_aircraft(ac: SimAircraft, window_s: float, slack_s: float = 120.0) -> dict:
    samples = raw_samples(ac)
    liftoff = liftoff_for(ac, samples)
    points = [
        {
            "t": round(liftoff + s["t"], 1),
            "lat": s["lat"],
            "lon": s["lon"],
            "alt_ft_msl": round(s["alt_ft"]),
            "gs_kt": round(s["gs_kt"], 1),
            "track_deg": round(s["track_deg"], 1),
        }
        for s in samples
        if 0 <= liftoff + s["t"] <= window_s + slack_s
    ]
    return {
        "hex": ac.hex_id,
        "reg": ac.reg,
        "type": ac.type,
        "owner": "SIMULATED",
        "role_guess": ac.role_guess,
        "simulated": True,
        "points": points,
        "squawk": [{"t": s.t, "code": s.code} for s in ac.squawk],
        "spoken": ac.spoken,
        "desk": ac.role == "desk",
        "liftoff_t": liftoff,
    }


def build_tracks(sc: Scenario) -> dict:
    return {
        "metadata": {
            "window_seconds": sc.window_s,
            "scenario": sc.id,
            "note": f"Fictional scripted tracks for SPEC.md section 4 scenario {sc.id}. Not real ADS-B. SIM ONLY.",
        },
        "aircraft": [build_aircraft(a, sc.window_s) for a in sc.aircraft],
    }


def position_at(ac_track: dict, t: float) -> tuple[float, float, float] | None:
    """Linear (lat, lon, alt) at t, None before first / after last point."""
    pts = ac_track["points"]
    if not pts or t < pts[0]["t"] or t > pts[-1]["t"]:
        return None
    for a, b in zip(pts, pts[1:]):
        if a["t"] <= t <= b["t"]:
            f = (t - a["t"]) / (b["t"] - a["t"]) if b["t"] > a["t"] else 0.0
            return (
                a["lat"] + (b["lat"] - a["lat"]) * f,
                a["lon"] + (b["lon"] - a["lon"]) * f,
                a["alt_ft_msl"] + (b["alt_ft_msl"] - a["alt_ft_msl"]) * f,
            )
    return None


def squawk_at(ac_track: dict, t: float) -> str:
    code = "1200"
    for s in sorted(ac_track.get("squawk", []), key=lambda s: s["t"]):
        if s["t"] <= t:
            code = s["code"]
    return code

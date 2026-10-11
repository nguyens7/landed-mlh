"""Climb-then-cruise position generator for the scripted sim medevac track."""

from __future__ import annotations

import itertools

from landed_geo import dest_point, great_circle_bearing, great_circle_dist_nm


def climb_cruise_positions(
    start: tuple[float, float],
    bearing_true: float,
    climb_time_s: float,
    cruise_alt_ft: float,
    cruise_kt: float,
    total_flight_time_s: float,
    step_s: float,
) -> list[dict]:
    """Great-circle steps along a single bearing: a climb segment with ground speed
    ramping linearly from 0 to cruise speed (a rough but realistic liftoff/climb-out),
    then level cruise at cruise_alt_ft / cruise_kt for the remainder of the flight.

    Returns samples [{t, lat, lon, alt_ft, gs_kt}], t in seconds from liftoff.
    """
    samples: list[dict] = []
    dist_nm = 0.0
    t = 0.0
    lat, lon = start
    while t <= total_flight_time_s:
        if t <= climb_time_s:
            frac = t / climb_time_s if climb_time_s > 0 else 1.0
            gs_kt = cruise_kt * frac
            alt_ft = cruise_alt_ft * frac
        else:
            gs_kt = cruise_kt
            alt_ft = cruise_alt_ft
        samples.append({"t": round(t, 1), "lat": lat, "lon": lon, "alt_ft": alt_ft, "gs_kt": gs_kt})

        # advance position by the distance covered during this step at current gs
        step_dist_nm = gs_kt * (step_s / 3600.0)
        dist_nm += step_dist_nm
        lat, lon = dest_point(*start, bearing_true, dist_nm)
        t += step_s

    return samples


def route_positions(
    route: list[tuple[float, float]],
    climb_time_s: float,
    cruise_alt_ft: float,
    cruise_kt: float,
    step_s: float,
) -> list[dict]:
    """Like climb_cruise_positions, but along a multi-leg route of waypoints. Each sample
    also carries its leg's track_deg. Stops at the last waypoint."""
    legs = []
    for a, b in itertools.pairwise(route):
        legs.append((a, great_circle_bearing(*a, *b), great_circle_dist_nm(*a, *b)))
    total_nm = sum(d for _, _, d in legs)

    samples: list[dict] = []
    dist_nm = 0.0
    t = 0.0
    while dist_nm <= total_nm:
        if t <= climb_time_s:
            frac = t / climb_time_s if climb_time_s > 0 else 1.0
            gs_kt, alt_ft = cruise_kt * frac, cruise_alt_ft * frac
        else:
            gs_kt, alt_ft = cruise_kt, cruise_alt_ft
        along = dist_nm
        for start, bearing, leg_nm in legs:
            if along <= leg_nm:
                break
            along -= leg_nm
        lat, lon = dest_point(*start, bearing, along)
        samples.append(
            {
                "t": round(t, 1),
                "lat": lat,
                "lon": lon,
                "alt_ft": alt_ft,
                "gs_kt": gs_kt,
                "track_deg": bearing,
            }
        )
        dist_nm += gs_kt * (step_s / 3600.0)
        t += step_s
    return samples

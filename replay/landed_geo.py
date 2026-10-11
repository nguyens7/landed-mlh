"""Shared geodesy helpers + APPROXIMATE reference geometry for Track A.

All geometry here is hand-drawn from `eda/scripts/analyze.py` and the cited
points in SPEC.md section 1. It is intentionally marked `approximate: true`
everywhere it surfaces in the app's GeoJSON stubs. Track B owns the real,
sourced geometry and will overwrite `app/public/data/geo/*.geojson` with
files that follow the same schema -- nothing here is a source of truth for
the app at runtime; the app reads only the GeoJSON files, never this module.
This module exists so `build_replay.py` (timing the simulated medevac
conflict) and `build_geo_stubs.py` (writing the stub GeoJSON) agree on the
same approximate reference points without duplicating numbers.
"""

from __future__ import annotations

import math

NM_M = 1852.0
EARTH_R_NM = 3440.065

# --- Cited reference points (SPEC.md section 1, eda/scripts/analyze.py) ---


def dm(s: str) -> float:
    """Parse AirNav-style 'DD-MM.mmmmmmN' / 'DDD-MM.mmmmmmW' into signed decimal degrees."""
    d, m = s[:-1].split("-")
    v = int(d) + float(m) / 60
    return -v if s[-1] in "SW" else v


HELIPORT_6N5 = (40.7424472, -73.9721222)  # E 34th St Heliport, AirNav
R22_THR = (dm("40-47.126200N"), dm("073-52.240402W"))  # LGA Rwy 22 threshold, AirNav KLGA
R31_THR = (dm("40-46.324287N"), dm("073-51.426695W"))  # LGA Rwy 31 threshold, AirNav KLGA

# Simulated-only destination for the fictional medevac scenario (S2 in SPEC.md section 4).
# A College Point-area waypoint on the north Queens shore (40.81, -73.82), NOT a hospital
# location: it sits ~1.5 nm north of the real Flushing Hospital Medical Center
# (40.7599, -73.8294). A literal 6N5 -> Flushing Hospital line passes south of the airport and
# never reaches the Rwy 22 final, so the scripted direct track aims here instead; its
# great-circle path crosses the Rwy 22 final low, the DCA-style conflict the demo is about.
# Approximate, simulation-only; narration calls it "the College Point area".
COLLEGE_POINT_WAYPOINT = (40.797, -73.835)

# Simulated route: north up the East River (the normal helicopter route), past the north
# side of Rikers Island, then "direct College Point". That last leg is the request the
# controller should catch: it cuts across the Rwy 22 final ~1 nm out over open water, at
# right angles, below the glidepath ceiling. Waypoints are hand-placed over water,
# simulation-only.
SIM_MEDEVAC_ROUTE = [
    HELIPORT_6N5,
    (40.772, -73.938),  # East River, off the north tip of Roosevelt Island
    (40.797, -73.905),  # past Hell Gate, near North Brother Island
    (40.806, -73.885),  # north of Rikers Island; turn for "direct College Point"
    COLLEGE_POINT_WAYPOINT,
]

# Approach centerline model, same as eda/scripts/analyze.py APP dict:
# straight line from the runway threshold, outward along the inbound course's
# reciprocal-ish bearing, length in nm. APPROXIMATE -- Track B's real geometry
# (and its possible multi-segment rising-ceiling split) supersedes this.
LGA22_APPROACH = {"thr": R22_THR, "bearing_true": 32.0, "length_nm": 10.0}
LGA31_APPROACH = {"thr": R31_THR, "bearing_true": 122.0, "length_nm": 3.0}


def dest_point(lat: float, lon: float, bearing_true: float, dist_nm: float) -> tuple[float, float]:
    """Destination point given a start, true bearing (deg), and great-circle distance (nm)."""
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    brg = math.radians(bearing_true)
    d_r = dist_nm / EARTH_R_NM
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def great_circle_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial true bearing (deg, 0-360) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360


def great_circle_dist_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in nautical miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_R_NM * math.asin(math.sqrt(a))


def local_xy_nm(lat: float, lon: float, lat0: float = 40.75) -> tuple[float, float]:
    """Local equirectangular projection in nm, matching eda/scripts/analyze.py's xy()."""
    x = (lon + 73.95) * 60 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 60
    return x, y


def seg_intersection_fraction(
    p1: tuple[float, float], p2: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float | None:
    """Fraction (0-1) along segment p1->p2 where it crosses segment a->b, in local nm
    coords, or None if the segments don't cross within both their extents."""
    x1, y1 = local_xy_nm(*p1)
    x2, y2 = local_xy_nm(*p2)
    x3, y3 = local_xy_nm(*a)
    x4, y4 = local_xy_nm(*b)
    d1x, d1y = x2 - x1, y2 - y1
    d2x, d2y = x4 - x3, y4 - y3
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-9:
        return None
    t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / denom
    u = ((x3 - x1) * d1y - (y3 - y1) * d1x) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t
    return None

"""Geo helpers: load the app's real protected volumes / corridors and test tracks against them."""

from __future__ import annotations

import json
import math
from functools import lru_cache

import paths  # sys.path for replay/ and speech/ must be set up first

# isort: split
from landed_geo import great_circle_dist_nm

LatLon = tuple[float, float]
Ring = list[tuple[float, float]]  # (lon, lat) pairs, GeoJSON order


@lru_cache(maxsize=1)
def protected_volumes() -> list[dict]:
    fc = json.loads((paths.GEO_DIR / "protected_volumes.geojson").read_text())
    return [
        {**f["properties"], "ring": [tuple(c) for c in f["geometry"]["coordinates"][0]]}
        for f in fc["features"]
    ]


@lru_cache(maxsize=1)
def corridors() -> dict[str, dict]:
    fc = json.loads((paths.GEO_DIR / "corridors.geojson").read_text())
    return {
        f["properties"]["id"]: {
            **f["properties"],
            "ring": [tuple(c) for c in f["geometry"]["coordinates"][0]],
        }
        for f in fc["features"]
    }


@lru_cache(maxsize=1)
def reference_points() -> dict[str, LatLon]:
    fc = json.loads((paths.GEO_DIR / "reference_points.geojson").read_text())
    return {
        f["properties"]["id"]: (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
        for f in fc["features"]
    }


def point_in_ring(lat: float, lon: float, ring: Ring) -> bool:
    """Ray casting; same algorithm as app/src/engine/geometry.ts pointInPolygon."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def alt_of(p: dict) -> float:
    return p["alt_ft_msl"] if "alt_ft_msl" in p else p["alt_ft"]


def in_volume(lat: float, lon: float, alt_ft: float, vol: dict) -> bool:
    return vol["floor_ft_msl"] <= alt_ft <= vol["ceiling_ft_msl"] and point_in_ring(lat, lon, vol["ring"])


def volumes_matching(prefix: str) -> list[dict]:
    return [v for v in protected_volumes() if v["id"].startswith(prefix)]


def first_entry(points: list[dict], prefix: str) -> tuple[dict, dict] | None:
    """First track point inside any volume whose id starts with ``prefix`` (polygon AND altitude band)."""
    vols = volumes_matching(prefix)
    for p in points:
        for v in vols:
            if in_volume(p["lat"], p["lon"], alt_of(p), v):
                return p, v
    return None


def volumes_entered(points: list[dict]) -> set[str]:
    """Ids of every protected volume (polygon + altitude band) the track enters."""
    out: set[str] = set()
    for v in protected_volumes():
        if any(in_volume(p["lat"], p["lon"], alt_of(p), v) for p in points):
            out.add(v["id"])
    return out


def _xy(la: float, lo: float) -> tuple[float, float]:
    return (lo + 73.95) * math.cos(math.radians(40.75)) * 60, (la - 40.75) * 60


def min_dist_to_ring_nm(lat: float, lon: float, ring: Ring) -> float:
    if point_in_ring(lat, lon, ring):
        return 0.0
    px, py = _xy(lat, lon)
    best = math.inf
    for (lo1, la1), (lo2, la2) in zip(ring, ring[1:]):
        ax, ay = _xy(la1, lo1)
        bx, by = _xy(la2, lo2)
        dx, dy = bx - ax, by - ay
        len2 = dx * dx + dy * dy
        t = 0.0 if len2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def dist_nm(a: LatLon, b: LatLon) -> float:
    return great_circle_dist_nm(*a, *b)

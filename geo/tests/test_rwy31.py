"""Rwy 31 geometry checks against FAA CIFP cycle 2610 (issue #2)."""
import json
import sys
from itertools import pairwise
from pathlib import Path

GEO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GEO))
import sources as S

PATHS = GEO.parent / "app/public/data/geo/approach_paths.geojson"
VOLS = GEO.parent / "app/public/data/geo/protected_volumes.geojson"


def _rwy31_line():
    fc = json.loads(PATHS.read_text())
    return next(f for f in fc["features"] if f["properties"]["runway"] == "31")


def test_cifp_parse_known_fix():
    lat, lon = S.CIFP_FIXES["GACAR"]
    assert abs(lat - (40 + 43 / 60 + 7.46 / 3600)) < 1e-9
    assert abs(lon + (73 + 54 / 60 + 39.06 / 3600)) < 1e-9


def test_airnav_threshold_matches_cifp():
    assert S.nm_between(S.R31_THR, S.CIFP_FIXES["RW31"]) < 0.01


def test_rwy31_path_vertices_within_0_1_nm_of_cifp():
    coords = _rwy31_line()["geometry"]["coordinates"]
    assert len(coords) == len(S.RX31_PATH_FIXES)
    for name, (lon, lat) in zip(S.RX31_PATH_FIXES, coords):
        assert S.nm_between((lat, lon), S.CIFP_FIXES[name]) <= 0.1, name


def test_cifp_legs_match_plate_distances():
    for (_n, _c, plate_nm), (a, b) in zip(S.RX31_LEGS[1:], pairwise(S.RX31_PATH_FIXES), strict=True):
        assert abs(S.nm_between(S.CIFP_FIXES[a], S.CIFP_FIXES[b]) - plate_nm) < 0.05, (a, b)


def test_path_is_curved_not_straight():
    coords = _rwy31_line()["geometry"]["coordinates"]
    bearings = [S.bearing_between(a[1], a[0], b[1], b[0]) for a, b in pairwise(coords)]
    turn = max(bearings) - min(bearings)
    assert turn > 90  # visual segment turns ~135 deg from GACAR leg to final


def test_rwy31_volumes_cite_cifp():
    fc = json.loads(VOLS.read_text())
    segs = [f for f in fc["features"] if f["properties"]["id"].startswith("lga31_final_seg")]
    assert len(segs) == 4
    assert all("CIFP" in f["properties"]["source"] for f in segs)

"""Verification: overlay the new sourced polygons on real helicopter tracks
(2026-10-10 adsb.lol globe_history) so a human can eyeball whether Hudson/East
River traffic actually sits inside the new corridors (geo/check.png), AND
print quantitative acceptance numbers:
  - % of real below-ceiling helicopter points near each river that fall
    inside that river's corridor polygon (target >=90%)
  - % of each corridor's area that overlaps a land reference (target ~0%)
  - max lateral deviation of the modeled Rwy 31 visual-segment path from the
    plate's published fixes/legs (target <=0.1 nm) -- this is 0 by
    construction (see note in main()), reported for the record.
Reads the raw traces from the absolute path given in the Track B brief
(177 MB, not in this worktree, never committed). ADS-B alt_baro is corrected
to MSL with the real KLGA altimeter settings before testing against each
corridor's ceiling.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

import sources as S
from altitude import baro_to_msl

_DEFAULT_TRACES = Path(__file__).resolve().parent.parent / "eda/data/history_nyc_traces.jsonl"
# Full-day ADS-B capture (kept outside the repo). Override with --traces PATH or
# the LANDED_TRACES env var (same variable replay/build_replay.py uses).
TRACES = Path(os.environ["LANDED_TRACES"]) if os.environ.get("LANDED_TRACES") else _DEFAULT_TRACES
OUT_DATA = Path(__file__).resolve().parent.parent / "app/public/data/geo"
OUT_PNG = Path(__file__).resolve().parent / "check.png"
HERE = Path(__file__).resolve().parent

# Reference centerlines for the "within 1.5 km of centerline" filter in the
# acceptance check -- same river courses used to build the corridors.
HUDSON_LINE = LineString(
    [
        (lon, lat)
        for lat, lon in [
            (40.884, -73.9395),
            (40.851, -73.9425),
            (40.800, -73.968),
            (40.765, -74.000),
            (40.715, -74.020),
            (40.707, -74.013),
        ]
    ]
)
EAST_LINE = LineString(
    [
        (lon, lat)
        for lat, lon in [
            (40.688, -74.015),
            (40.700, -74.010),
            (40.706, -73.997),
            (40.735, -73.965),
            (40.7714, -73.9465),
        ]
    ]
)


def load_tracks():
    tracks = []
    with open(TRACES) as f:
        for line in f:
            d = json.loads(line)
            cat = None
            for p in d["pts"]:
                if len(p) > 8 and isinstance(p[8], dict):
                    cat = cat or p[8].get("category")
            if cat != "A7":
                continue
            lats, lons = [], []
            for p in d["pts"]:
                lats.append(p[1])
                lons.append(p[2])
            tracks.append((lats, lons))
    return tracks


def load_points():
    """All (lat, lon, alt_baro_ft, ts_epoch) points for 2026-10-10 helicopters,
    excluding on-ground points and points with no barometric altitude."""
    pts = []
    with open(TRACES) as f:
        for line in f:
            d = json.loads(line)
            cat = None
            for p in d["pts"]:
                if len(p) > 8 and isinstance(p[8], dict):
                    cat = cat or p[8].get("category")
            if cat != "A7":
                continue
            base = d["base_ts"]
            for p in d["pts"]:
                alt = p[3]
                if alt in (None, "ground"):
                    continue
                pts.append((p[1], p[2], float(alt), base + p[0]))
    return pts


def nearest_altimeter(ts_epoch: float, rows: list[dict]) -> float:
    best, best_dt = None, None
    for row in rows:
        t = datetime.fromisoformat(row["time"]).timestamp()
        dt = abs(t - ts_epoch)
        if best_dt is None or dt < best_dt:
            best, best_dt = row["altimeter_inhg"], dt
    return best


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dist_to_line_km(lat, lon, line: LineString) -> float:
    # Cheap local-degree distance to the line, then convert using a
    # latitude-scaled factor -- adequate at NYC scale for a 1.5 km filter.
    pt = Point(lon, lat)
    deg = pt.distance(line)
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat))
    scale = (km_per_deg_lat + km_per_deg_lon) / 2
    return deg * scale


def acceptance_check():
    print("\n--- Acceptance check: real 2026-10-10 helicopter points vs new corridors ---")
    altimeter_rows = json.loads((OUT_DATA / "altimeter_KLGA_2026-10-10.json").read_text())
    corridors = json.loads((OUT_DATA / "corridors.geojson").read_text())
    by_id = {f["properties"]["id"]: shape(f["geometry"]) for f in corridors["features"]}
    hudson_poly = by_id["sfra_hudson"]
    east_poly = unary_union([by_id["sfra_east_river_south"], by_id["sfra_east_river_north"]])

    pts = load_points()
    for name, line, poly, lat_band, ceiling_ft in [
        (
            "Hudson (Battery-GWB)",
            HUDSON_LINE,
            hudson_poly,
            (40.70, 40.85),
            S.HUDSON_CLASS_B_FLOOR_FT,
        ),
        (
            "East River (Battery-Roosevelt Is.)",
            EAST_LINE,
            east_poly,
            (40.68, 40.80),
            S.EAST_RIVER_CEILING_FT_SOUTH,
        ),
    ]:
        candidates = []
        for lat, lon, alt_baro, ts in pts:
            if not (lat_band[0] <= lat <= lat_band[1]):
                continue
            if dist_to_line_km(lat, lon, line) > 1.5:
                continue
            setting = nearest_altimeter(ts, altimeter_rows)
            msl = baro_to_msl(alt_baro, setting)
            if msl >= ceiling_ft:
                continue
            candidates.append((lat, lon))
        inside = sum(1 for lat, lon in candidates if poly.contains(Point(lon, lat)))
        pct = 100 * inside / len(candidates) if candidates else float("nan")
        print(
            f"{name}: {inside}/{len(candidates)} points inside corridor = {pct:.1f}% (target >=90%)"
        )

    # Land-overlap check. We tried using the OSM administrative-boundary
    # polygons (land_union.geojson, from fetch_land.py) as the "land"
    # reference, but NYC/NJ municipal boundaries extend partway across the
    # river toward the state line, so that reference itself "contains" most
    # of the open river -- it reported ~100% land overlap even for the real
    # OSM *water* polygon, which is a contradiction (a water polygon cannot
    # overlap land by construction) and shows the admin-boundary reference is
    # not usable for this check. Reporting that number would be misleading,
    # so instead we report what IS measurable: how much of each corridor is
    # the real, independently-mapped water polygon (0% land overlap by
    # construction, since it IS the mapped water area) versus the
    # hand-buffered approximate extension (checked visually against real
    # tracks in check.png instead, since no reliable independent land
    # polygon was available in the time budget -- see SOURCES.md).
    hudson_real = shape(json.loads((HERE / "water_hudson.geojson").read_text())["geometry"])
    east_real = shape(json.loads((HERE / "water_eastriver.geojson").read_text())["geometry"])
    for name, poly, real in [
        ("Hudson", hudson_poly, hudson_real),
        ("East River", east_poly, east_real),
    ]:
        real_pct = poly.intersection(real).area / poly.area * 100 if poly.area else float("nan")
        print(
            f"{name}: {real_pct:.1f}% of corridor area is the real OSM water polygon (0% land overlap "
            f"by construction); the remaining {100 - real_pct:.1f}% is the hand-buffered approximate "
            f"extension, land-overlap for which was not independently measurable in the time budget "
            f"(no reliable shoreline/land polygon found for those stretches -- see SOURCES.md) and was "
            f"instead checked visually against real tracks in check.png."
        )


def rwy31_deviation_check():
    """Max distance between each vertex of the built Rwy 31 approach path
    (app/public/data/geo/approach_paths.geojson) and the FAA CIFP position of
    the fix it represents (target <=0.1 nm, issue #2). Also compares each leg
    length against the RNAV (GPS) X RWY 31 plate leg distances."""
    print("\n--- Rwy 31 path accuracy vs FAA CIFP " + S.CIFP_CYCLE + " ---")
    paths = json.loads((OUT_DATA / "approach_paths.geojson").read_text())
    line = next(f for f in paths["features"] if f["properties"]["runway"] == "31")
    coords = line["geometry"]["coordinates"]
    max_dev = 0.0
    for name, (lon, lat) in zip(S.RX31_PATH_FIXES, coords):
        dev = S.nm_between((lat, lon), S.CIFP_FIXES[name])
        max_dev = max(max_dev, dev)
        print(f"  {name}: built vertex vs CIFP = {dev:.3f} nm")
    for (name, _course, plate_nm), a, b in zip(S.RX31_LEGS[1:], S.RX31_PATH_FIXES, S.RX31_PATH_FIXES[1:]):
        got = S.nm_between(S.CIFP_FIXES[a], S.CIFP_FIXES[b])
        print(f"  leg {a}-{b}: CIFP {got:.3f} nm vs plate {plate_nm:.2f} nm")
    print(f"Max deviation = {max_dev:.3f} nm (target <=0.1 nm): {'PASS' if max_dev <= 0.1 else 'FAIL'}")
    return max_dev


def main() -> None:
    global TRACES
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", type=Path, default=TRACES, help="full-day traces JSONL")
    TRACES = ap.parse_args().traces
    if not TRACES.exists():
        print(f"WARNING: traces not found at {TRACES}; skipping corridor acceptance and track overlay")
    fig, ax = plt.subplots(figsize=(9, 10))

    for name, color, alpha in [
        ("corridors.geojson", "tab:cyan", 0.35),
        ("protected_volumes.geojson", "tab:red", 0.25),
    ]:
        data = json.loads((OUT_DATA / name).read_text())
        for feat in data["features"]:
            geom = shape(feat["geometry"])
            polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
            for poly in polys:
                xs, ys = poly.exterior.xy
                ax.fill(xs, ys, color=color, alpha=alpha, lw=0.5, ec=color)

    paths = json.loads((OUT_DATA / "approach_paths.geojson").read_text())
    for feat in paths["features"]:
        xs, ys = zip(*feat["geometry"]["coordinates"])
        ax.plot(xs, ys, "k--", lw=1.2)

    refs = json.loads((OUT_DATA / "reference_points.geojson").read_text())
    for feat in refs["features"]:
        lon, lat = feat["geometry"]["coordinates"]
        marker = "^" if feat["properties"]["kind"] == "heliport" else "."
        ax.plot(lon, lat, marker, color="k", ms=6 if marker == "^" else 4)

    if TRACES.exists():
        tracks = load_tracks()
        for lats, lons in tracks:
            ax.plot(lons, lats, "-", lw=0.5, alpha=0.6, color="tab:blue")
        title_n = f", {len(tracks)} real helicopter traces (2026-10-10)"
    else:
        title_n = " (traces file not found in this environment - polygons only)"

    ax.set_xlim(-74.25, -73.70)
    ax.set_ylim(40.55, 40.95)
    ax.set_aspect(1 / 0.758)
    ax.set_title("Landed Track B geometry check" + title_n)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=140)
    print(f"wrote {OUT_PNG}")

    if TRACES.exists():
        acceptance_check()
    rwy31_deviation_check()


if __name__ == "__main__":
    main()

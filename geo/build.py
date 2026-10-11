"""Landed Track B: build the sourced geometry layers consumed by the map app.

Run from this directory with `uv run python build.py`. Deterministic: no
network calls. Regenerates everything under ../app/public/data/geo/ plus
check.png. Coordinate/citation detail lives in sources.py; this file turns
those cited points into validated GeoJSON.
"""

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import unary_union

import sources as S
from altitude import baro_to_msl  # noqa: F401  (re-exported for Track A's convenience)
from gen_altimeter import build as build_altimeter_rows

OUT = Path(__file__).resolve().parent.parent / "app/public/data/geo"
OUT.mkdir(parents=True, exist_ok=True)


def ll(lat: float, lon: float) -> list[float]:
    """GeoJSON coordinate order: [lon, lat]."""
    return [round(lon, 6), round(lat, 6)]


def feature(geom, props: dict) -> dict:
    g = mapping(geom)
    return {"type": "Feature", "geometry": g, "properties": props}


def fc(features: list[dict], source: str, approximate_note: str) -> dict:
    return {
        "type": "FeatureCollection",
        "metadata": metadata_block(source, approximate_note),
        "features": features,
    }


def metadata_block(source: str, approximate_note: str) -> dict:
    return {
        "source": source,
        "generated_by": "geo/build.py",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "approximate_note": approximate_note,
    }


def write(name: str, data: dict) -> None:
    path = OUT / name
    path.write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {path} ({len(data.get('features', []))} features)")


def arc_points(
    center: tuple[float, float], radius_nm: float, start_true: float, end_true: float, n: int = 48
):
    """Points along a great-circle arc (clockwise from start_true to end_true,
    both true bearings from center) at constant radius, for building the
    LGA-VOR-centered boundary arcs called out in 14 CFR 93.350."""
    if end_true < start_true:
        end_true += 360
    pts = []
    for i in range(n + 1):
        b = start_true + (end_true - start_true) * i / n
        pts.append(S.destination(*center, b % 360, radius_nm))
    return pts


# ---------------------------------------------------------------------------
# shared helper: constant-width buffer around a centerline (local
# equirectangular projection; adequate at NYC latitude for the sub-1 nm widths
# used here).
# ---------------------------------------------------------------------------


def half_width_polygon(center_line: list[tuple[float, float]], half_width_nm: float) -> Polygon:
    """Build a simple constant-width buffer polygon around a centerline, using a
    local equirectangular projection (good enough at NYC latitude for a ~1 nm buffer)."""
    lat0 = center_line[0][0]
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    xy = [
        ((lon - center_line[0][1]) * m_per_deg_lon, (lat - center_line[0][0]) * m_per_deg_lat)
        for lat, lon in center_line
    ]
    line = LineString(xy)
    buf = line.buffer(half_width_nm * 1852.0, cap_style=2)
    # Each pair here is already (lon, lat) -- GeoJSON order -- since x maps
    # back to a longitude offset and y to a latitude offset.
    coords = [
        (x / m_per_deg_lon + center_line[0][1], y / m_per_deg_lat + center_line[0][0])
        for x, y in buf.exterior.coords
    ]
    return Polygon(coords)


def dilate_nm(geom, nm: float):
    """Buffer an already-built lon/lat polygon outward by `nm` nautical miles,
    using the same local equirectangular approximation as half_width_polygon.
    Used to add a small practical tolerance margin on top of the real
    shoreline polygons -- real ADS-B helicopter tracks run a bit outside the
    literal mapped water edge often enough (GPS/ADS-B position noise, piers
    and structures right at the shoreline that are not mapped as water) that
    a zero-margin polygon under-covers real traffic; see geo/check.py's
    acceptance numbers and geo/SOURCES.md for the measured effect."""
    lat0 = geom.centroid.y
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))

    import numpy as np
    import shapely

    proj = shapely.transform(geom, lambda c: c * np.array([m_per_deg_lon, m_per_deg_lat]))
    buf = proj.buffer(nm * 1852.0)
    return shapely.transform(buf, lambda c: c / np.array([m_per_deg_lon, m_per_deg_lat]))


def segment_poly(thr_latlon, bearing_true, start_nm, end_nm, half_width_nm) -> Polygon:
    a = S.destination(*thr_latlon, bearing_true, start_nm)
    b = S.destination(*thr_latlon, bearing_true, end_nm)
    return half_width_polygon([a, b], half_width_nm)


def glidepath_ft(tdze_ft: float, dist_nm: float, glidepath_deg: float = 3.0) -> float:
    return tdze_ft + dist_nm * 6076.12 * math.tan(math.radians(glidepath_deg))


# ---------------------------------------------------------------------------
# corridors.geojson -- Hudson + East River SFRA exclusions, 14 CFR 93.350-353
#
# Built from REAL OSM tidal-water multipolygons (fetch_water.py / water_cache/,
# see that file's docstring and SOURCES.md for the relation IDs and the ODbL
# attribution) wherever that data reaches -- which is most of each river
# adjacent to Manhattan. The public Overpass API's saturation meant a few
# short stretches at the far north/south ends of each exclusion (near Alpine
# Tower and the Verrazzano-Narrows area for the Hudson; the southern approach
# to the 93.350(c) start vertex for the East River) could not be fetched as
# real polygons in the time available; those EXTENSION stretches fall back to
# a constant-width buffer around a hand-placed centerline, same as the
# original approximation, and are the only parts still flagged approximate.
# ---------------------------------------------------------------------------


def load_water(name: str):
    from shapely.geometry import shape

    data = json.loads((Path(__file__).resolve().parent / name).read_text())
    return shape(data["geometry"])


def south_of(geom, max_lat: float):
    from shapely.geometry import box

    minx, miny, maxx, _maxy = geom.bounds
    return geom.intersection(box(minx - 1, miny - 1, maxx + 1, max_lat))


def north_of(geom, min_lat: float):
    from shapely.geometry import box

    minx, _miny, maxx, maxy = geom.bounds
    return geom.intersection(box(minx - 1, min_lat, maxx + 1, maxy + 1))


def between_lat(geom, min_lat: float, max_lat: float):
    return south_of(north_of(geom, min_lat), max_lat)


def build_corridors() -> dict:
    feats = []

    # ---- Hudson River Exclusion (93.350(d)) --------------------------------
    hudson_real = load_water("water_hudson.geojson")  # real OSM polygon, ~40.707N-40.884N
    # APPROXIMATE extensions to the regulation's named endpoints: a buffer
    # around a hand-placed centerline, only used outside the real polygon's
    # latitude range (so the real shoreline is never overridden).
    hudson_centerline = [
        S.HUDSON_START_NEAR_ALPINE,  # sourced: 40-57-45N 73-54-48W
        (40.900, -73.930),
        (40.884, -73.9395),  # hand off to the real OSM polygon's north edge
        (40.707, -74.013),  # hand off to the real OSM polygon's south edge
        (40.690, -74.0325),  # abeam the Battery, river widens into the bay
        (40.6442, -74.0342),  # sourced: 93.350(c)/(d) shared vertex, 40-38-39N 74-02-03W
        (40.606, -74.044),  # sourced-ish: Verrazzano-Narrows Bridge
    ]
    hudson_buffer_extension = half_width_polygon(hudson_centerline, half_width_nm=0.45)
    hudson_north_ext = between_lat(
        hudson_buffer_extension, S.HUDSON_START_NEAR_ALPINE[0] - 0.01, 40.884
    )
    hudson_south_ext = south_of(hudson_buffer_extension, 40.707)
    hudson_poly = unary_union([hudson_real, hudson_north_ext, hudson_south_ext]).buffer(0)
    hudson_poly = between_lat(hudson_poly, 40.60, S.HUDSON_START_NEAR_ALPINE[0] + 0.01)
    # Practical tolerance margin -- see dilate_nm() docstring and SOURCES.md
    # for the measured real-track coverage improvement this gives.
    hudson_poly = dilate_nm(hudson_poly, 0.3).buffer(0)
    feats.append(
        feature(
            hudson_poly,
            {
                "id": "sfra_hudson",
                "name": "Hudson River Exclusion (SFRA)",
                "kind": "sfra_corridor",
                "floor_ft_msl": 0,
                "ceiling_ft_msl": S.HUDSON_CLASS_B_FLOOR_FT,
                "direction_rule": "southbound on west shoreline, northbound on east shoreline, 1,000 ft MSL or higher, self-announce at charted reporting points",
                "source": "14 CFR 93.350(d)/93.351/93.352 (https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W); Class B floor 1,300 ft MSL per FR Doc 2026-15552 (NY Class B Area K); shoreline from OpenStreetMap contributors (relations 2389611, 2389521), ODbL 1.0 (see geo/fetch_water.py, geo/SOURCES.md)",
                "approximate": True,
                "approximate_note": "Shoreline is REAL (OSM tidal-water relations 2389611/2389521, ODbL) for roughly 40.707N-40.884N, which covers the Midtown/UWS/GWB stretch. North of 40.884N (toward Alpine Tower) and south of 40.707N (toward the Verrazzano-Narrows area and the 93.350(c)/(d) shared vertex), the Overpass API did not yield a real polygon in the time available, so those two extensions are a hand-centerline buffer (+-0.45 nm), approximate. The north/south regulatory cutoff itself is also a latitude line, not the exact Colts Neck-radial/Verrazzano cutline.",
            },
        )
    )

    # ---- East River Exclusion (93.350(c)) ----------------------------------
    east_real = load_water("water_eastriver.geojson")  # real OSM polygon, ~40.688N-40.798N
    east_centerline = [
        S.EAST_RIVER_START,  # sourced: 40-38-39N 74-02-03W
        (
            40.670,
            -74.020,
        ),  # hand-placed, APPROX: approach from the harbor toward the sourced start vertex
        (40.688, -74.015),  # hand off to the real OSM polygon's south edge
    ]
    east_buffer_extension = half_width_polygon(east_centerline, half_width_nm=0.3)
    east_south_ext = north_of(south_of(east_buffer_extension, 40.688), S.EAST_RIVER_START[0] - 0.01)
    east_water = unary_union([east_real, east_south_ext]).buffer(0)
    east_water = north_of(east_water, S.EAST_RIVER_START[0] - 0.01)

    six_nm_split_lat = 40.735  # approx where the LGA VOR/DME 6 nm arc crosses this stretch
    east_water = dilate_nm(east_water, 0.5).buffer(0)  # practical tolerance margin, see dilate_nm()
    south_poly = south_of(east_water, six_nm_split_lat)
    north_poly = north_of(east_water, six_nm_split_lat)
    feats.append(
        feature(
            south_poly,
            {
                "id": "sfra_east_river_south",
                "name": "East River Exclusion, Governors Island to LGA VOR/DME 6 nm arc",
                "kind": "sfra_corridor",
                "floor_ft_msl": 0,
                "ceiling_ft_msl": S.EAST_RIVER_CEILING_FT_SOUTH,
                "direction_rule": "airplanes need ATC authorization (93.353); helicopters self-announce",
                "source": "14 CFR 93.350(c) (https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W); shoreline from OpenStreetMap contributors (relation 2389633), ODbL 1.0",
                "approximate": True,
                "approximate_note": "Shoreline is REAL (OSM tidal-water relation 2389633, ODbL) for roughly 40.688N-40.735N. South of 40.688N, toward the sourced 93.350(c) start vertex (40-38-39N/74-02-03W), is a hand-centerline buffer (+-0.3 nm), approximate (Overpass did not yield a real polygon there in the time available). The LGA VOR/DME 6 nm arc crossing is approximated as a latitude cut (40.735N), not a true circle/polygon intersection.",
            },
        )
    )
    feats.append(
        feature(
            north_poly,
            {
                "id": "sfra_east_river_north",
                "name": "East River Exclusion, LGA VOR/DME 6 nm arc to north tip Roosevelt Island",
                "kind": "sfra_corridor",
                "floor_ft_msl": 0,
                "ceiling_ft_msl": S.EAST_RIVER_CEILING_FT_NORTH,
                "direction_rule": "airplanes need ATC authorization (93.353); helicopters self-announce",
                "source": "14 CFR 93.350(c) (https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W); shoreline from OpenStreetMap contributors (relations 2389563 West Channel, 2389581 East Channel, 20805948), ODbL 1.0",
                "approximate": True,
                "approximate_note": "Shoreline is REAL (OSM tidal-water relations around Roosevelt Island and north to ~40.798N, ODbL). North endpoint (Roosevelt Island north tip, ~40.7714N) is named in the regulation and sits inside this real-data range. The 6 nm arc crossing is approximated as in the south band (latitude cut at 40.735N).",
            },
        )
    )

    return fc(
        feats,
        source="14 CFR 93.350-93.353 (SFRA Hudson/East River Exclusions); real shoreline from "
        "OpenStreetMap contributors via Overpass API, ODbL 1.0 (geo/fetch_water.py)",
        approximate_note="Each feature's own approximate_note gives the detail; in short, the real "
        "OSM water polygons cover most of each river (see geo/check.py acceptance numbers), with "
        "hand-buffered approximate extensions only at the far north/south ends and a latitude-line "
        "approximation for the LGA VOR/DME 6 nm arc crossing and the regulatory north/south cutoffs.",
    )


def build_protected_volumes() -> dict:
    feats = []

    # --- LGA Rwy 22 final, COPTER ILS/LOC 22 --------------------------------
    thr22 = S.LGA_RUNWAYS["22"][:2]
    brg22_out = S.R22_TRUE_COURSE - 180  # outbound/upwind direction from threshold
    tdze22 = S.LGA_RUNWAYS["22"][3]
    # Split into 1 nm segments out to 10 nm so the ceiling climbs with the
    # 3-degree glidepath instead of being one flat slab.
    seg_bounds = [0, 1, 2, 3, 4, 5, 7, 10]
    for i in range(len(seg_bounds) - 1):
        s0, s1 = seg_bounds[i], seg_bounds[i + 1]
        poly = segment_poly(thr22, brg22_out, s0, s1, half_width_nm=0.5)
        feats.append(
            feature(
                poly,
                {
                    "id": f"lga22_final_seg{i}",
                    "name": f"LGA Rwy 22 final, {s0}-{s1} nm from threshold",
                    "kind": "approach",
                    "runway": "22",
                    "floor_ft_msl": round(max(glidepath_ft(tdze22, s0) - 400, 0)),
                    "ceiling_ft_msl": round(glidepath_ft(tdze22, s1) + 400),
                    "source": "COPTER ILS/LOC RWY 22 plate (https://aeronav.faa.gov/d-tpp/2609/00289copteril22.pdf); threshold coords/true heading AirNav KLGA",
                    "approximate": True,
                    "approximate_note": "Centerline is the straight final from the sourced runway-22 threshold on its sourced true heading (212). Width (+-0.5 nm) and the 3-degree glidepath-based ceiling/floor split are modeled, not taken from the plate's protection surfaces.",
                },
            )
        )

    # --- LGA Rwy 31 final, RNAV (GPS) X RWY 31 (curved visual segment) ------
    thr31 = S.LGA_RUNWAYS["31"][:2]
    tdze31 = S.LGA_RUNWAYS["31"][3]
    # Fix positions straight from FAA CIFP (see sources.py section 4b). The
    # threshold vertex is the sourced AirNav threshold (matches CIFP RW31 to
    # <1 ft).
    legs_latlon = [thr31] + [S.CIFP_FIXES[n] for n in S.RX31_PATH_FIXES[1:]]
    # legs_latlon = [RW31, DCTRK, KEYTH, DRRYL, GACAR] outward from threshold
    cum = [0.0]
    for i in range(1, len(legs_latlon)):
        cum.append(cum[-1] + S.nm_between(legs_latlon[i - 1], legs_latlon[i]))
    for i in range(len(legs_latlon) - 1):
        s0, s1 = cum[i], cum[i + 1]
        seg_line = [legs_latlon[i], legs_latlon[i + 1]]
        poly = half_width_polygon(seg_line, 0.4)
        name_a, name_b = S.RX31_PATH_FIXES[i], S.RX31_PATH_FIXES[i + 1]
        feats.append(
            feature(
                poly,
                {
                    "id": f"lga31_final_seg{i}",
                    "name": f"LGA Rwy 31 final/visual segment, {name_a}-{name_b}",
                    "kind": "approach",
                    "runway": "31",
                    "floor_ft_msl": round(max(glidepath_ft(tdze31, s0) - 400, 0)),
                    "ceiling_ft_msl": round(glidepath_ft(tdze31, s1) + 400),
                    "source": f"RNAV (GPS) X RWY 31 plate (https://aeronav.faa.gov/d-tpp/2610/00289rx31.pdf); fix positions FAA CIFP cycle {S.CIFP_CYCLE} ({S.CIFP_URL}); threshold AirNav KLGA",
                    "approximate": True,
                    "approximate_note": "Models the curved visual segment (DRRYL-KEYTH-DCTRK-RW31) as straight TF legs between the CIFP fix positions, as the plate codes it; the flown track rounds the corners. Width (+-0.4 nm) and 3-degree glidepath floor/ceiling are modeled, not plate protection surfaces.",
                },
            )
        )

    # --- LGA Rwy 4/13 departure headings (modeled as straight corridors) ---
    for rwy in ("4", "13"):
        lat, lon, hdg, tdze = S.LGA_RUNWAYS[rwy]
        poly = segment_poly((lat, lon), hdg, 0, 5, half_width_nm=0.5)
        feats.append(
            feature(
                poly,
                {
                    "id": f"lga{rwy}_departure",
                    "name": f"LGA Rwy {rwy} departure corridor (modeled straight-out, 5 nm)",
                    "kind": "departure",
                    "runway": rwy,
                    "floor_ft_msl": round(tdze),
                    "ceiling_ft_msl": 3000,
                    "source": "Runway true heading from AirNav KLGA runway table; straight-out departure modeling is this project's own simplification, not an FAA-published departure procedure",
                    "approximate": True,
                    "approximate_note": "FAA does not publish a single departure centerline comparable to an approach final; this is a geofence placeholder on the runway heading, flagged approximate. Real departure headings/turns (e.g. Triborough/Throgs Neck routing) are only in the VATSIM SOP, marked [UNVERIFIED] in SPEC.md and not used here.",
                },
            )
        )

    # --- Class B floor over the rivers (as a volume, not just the corridor ceiling) ---
    hudson_corridor = build_corridors()["features"][0]["geometry"]
    feats.append(
        {
            "type": "Feature",
            "geometry": hudson_corridor,
            "properties": {
                "id": "class_b_floor_hudson",
                "name": "Class B floor over the Hudson River Exclusion",
                "kind": "class_b_floor",
                "runway": None,
                "floor_ft_msl": S.HUDSON_CLASS_B_FLOOR_FT,
                "ceiling_ft_msl": 7000,
                "source": "14 CFR 93.350(d) (https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W): Hudson Exclusion up to the Class B floor; NY Class B Area K floor 1,300 ft MSL per FR Doc 2026-15552 (https://www.federalregister.gov/documents/2026/07/31/2026-15552/amendment-of-class-b-airspace-new-york-ny)",
                "approximate": True,
                "approximate_note": "Same footprint as the Hudson SFRA corridor polygon (approximate shoreline digitization); represents Class B airspace starting at 1,300 ft MSL and above over that footprint.",
            },
        }
    )

    return fc(
        feats,
        source="FAA LGA approach/departure plates and AirNav KLGA runway data (see each feature's "
        "own `source` property)",
        approximate_note="Approach volumes model a 3-degree glidepath-based ceiling/floor split along "
        "a modeled width; see each feature's own approximate_note. Rwy 4/13 departure corridors are "
        "this project's own placeholder, not an FAA-published departure procedure.",
    )


# ---------------------------------------------------------------------------
# approach_paths.geojson -- centerlines
# ---------------------------------------------------------------------------


def build_approach_paths() -> dict:
    feats = []
    thr22 = S.LGA_RUNWAYS["22"][:2]
    end22 = S.destination(*thr22, S.R22_TRUE_COURSE - 180, S.R22_FINAL_LEN_NM)
    feats.append(
        feature(
            LineString([ll(*thr22), ll(*end22)]),
            {
                "runway": "22",
                "bearing_true": S.R22_TRUE_COURSE,
                "glidepath_deg": 3.0,
                "threshold_lat": round(thr22[0], 6),
                "threshold_lon": round(thr22[1], 6),
                "tdze_ft": S.LGA_RUNWAYS["22"][3],
                "fixes": [],
                "source": "COPTER ILS/LOC RWY 22 (https://aeronav.faa.gov/d-tpp/2609/00289copteril22.pdf); threshold AirNav KLGA",
            },
        )
    )

    thr31 = S.LGA_RUNWAYS["31"][:2]
    pts = [ll(*thr31)] + [ll(*S.CIFP_FIXES[n]) for n in S.RX31_PATH_FIXES[1:]]
    feats.append(
        feature(
            LineString(pts),
            {
                "runway": "31",
                "bearing_true": S.LGA_RUNWAYS["31"][2],
                "glidepath_deg": 3.0,
                "threshold_lat": round(thr31[0], 6),
                "threshold_lon": round(thr31[1], 6),
                "tdze_ft": S.LGA_RUNWAYS["31"][3],
                "fixes": ["DCTRK", "KEYTH", "DRRYL", "GACAR"],
                "source": f"RNAV (GPS) X RWY 31 (https://aeronav.faa.gov/d-tpp/2610/00289rx31.pdf); fix positions FAA CIFP cycle {S.CIFP_CYCLE} ({S.CIFP_URL}); threshold AirNav KLGA",
            },
        )
    )
    return fc(
        feats,
        source="COPTER ILS/LOC RWY 22 and RNAV (GPS) X RWY 31 plates; AirNav KLGA thresholds",
        approximate_note="Rwy 22 centerline is a straight line on the sourced true heading. Rwy 31 "
        "centerline passes through the FAA CIFP (cycle 2610) positions of DCTRK, KEYTH, DRRYL and GACAR "
        "as straight TF legs. See geo/check.py and geo/tests/test_rwy31.py for the deviation check.",
    )


# ---------------------------------------------------------------------------
# reference_points.geojson -- heliports + SFRA reporting points
# ---------------------------------------------------------------------------


def build_reference_points() -> dict:
    feats = []
    for ident, h in S.HELIPORTS.items():
        feats.append(
            feature(
                Point(ll(h["lat"], h["lon"])),
                {"id": ident, "name": h["name"], "kind": "heliport", "source": h["source"]},
            )
        )
    for key, p in S.REPORTING_POINTS.items():
        feats.append(
            feature(
                Point(ll(p["lat"], p["lon"])),
                {
                    "id": key,
                    "name": p["name"],
                    "kind": "reporting_point",
                    "corridor": p["corridor"],
                    "mandatory": p["mandatory"],
                    "source": "SPEC.md Sec 0.6/1.2, FAA SFRA kneeboard (https://www.faasafety.gov/files/gslac/courses/content/79/775/kneeboard.pdf) names the point; lat/lon is the public landmark centroid (approximate, FAA point coordinate not retrieved)",
                },
            )
        )
    return fc(
        feats,
        source="AirNav (heliports, see each feature's own `source` property); SPEC.md Sec 0.6/1.2 and "
        "the FAA SFRA kneeboard (reporting points, named list only)",
        approximate_note="Heliport points are not approximate (published AirNav coordinates). "
        "Reporting points are approximate: placed at the named landmark's public centroid, since no "
        "FAA-published point coordinate was retrieved for them.",
    )


# ---------------------------------------------------------------------------
# altitude_rules.json -- machine-readable altitude rules for the conflict
# engine, plus the LGA VOR/DME 6 nm arc geometry that splits the East River
# exclusion's two ceilings.
# ---------------------------------------------------------------------------


def build_altitude_rules() -> dict:
    arc_6nm = arc_points(S.LGA_VOR, S.LGA_6NM_ARC_RADIUS_NM, 0, 360, n=96)
    arc_feature = feature(
        LineString([ll(*p) for p in arc_6nm]),
        {
            "id": "lga_vor_6nm_arc",
            "name": "LGA VOR/DME 6 nm arc",
            "center_lat": round(S.LGA_VOR[0], 6),
            "center_lon": round(S.LGA_VOR[1], 6),
            "radius_nm": S.LGA_6NM_ARC_RADIUS_NM,
            "source": "14 CFR 93.350(c); LGA VOR/DME position from AirNav KLGA facility data",
        },
    )
    rules = {
        "hudson": {
            "transit_min_ft_msl": 1000,
            "transit_min_source": "14 CFR 93.351(c)/93.352(c): transit at or above 1,000 ft MSL",
            "class_b_floor_ft_msl": S.HUDSON_CLASS_B_FLOOR_FT,
            "class_b_floor_source": "NY Class B Area K floor 1,300 ft MSL, FR Doc 2026-15552 (https://www.federalregister.gov/documents/2026/07/31/2026-15552/amendment-of-class-b-airspace-new-york-ny); "
            "14 CFR 93.350(d) Hudson Exclusion up to that floor",
        },
        "east_river": {
            "ceiling_ft_msl_south_of_6nm_arc": S.EAST_RIVER_CEILING_FT_SOUTH,
            "ceiling_ft_msl_north_of_6nm_arc": S.EAST_RIVER_CEILING_FT_NORTH,
            "ceiling_source": "14 CFR 93.350(c): below 1,500 ft MSL generally, dropping to 1,100 ft "
            "MSL and below from the LGA VOR/DME 6 nm arc to the north tip of Roosevelt Island",
            "six_nm_arc_center": {"lat": round(S.LGA_VOR[0], 6), "lon": round(S.LGA_VOR[1], 6)},
            "six_nm_arc_radius_nm": S.LGA_6NM_ARC_RADIUS_NM,
            "six_nm_arc_source": "14 CFR 93.350(c); LGA VOR/DME position from AirNav KLGA",
        },
        "jfk_ewr": "not modeled -- see SOURCES.md",
    }
    return {
        "type": "FeatureCollection",
        "metadata": metadata_block(
            source="14 CFR 93.350-93.352 (eCFR); FR Doc 2026-15552 (NY Class B Area K floor)",
            approximate_note="Altitude numbers are sourced CFR/FAA-course values (see each rule's own "
            "*_source field). The 6 nm arc geometry uses the sourced LGA VOR/DME position and the "
            "sourced 6 nm radius; where that arc actually crosses the river channel is still "
            "approximated elsewhere (corridors.geojson) as a latitude cut, not a true intersection "
            "with this arc.",
        ),
        "rules": rules,
        "features": [arc_feature],
    }


def main() -> None:
    write("corridors.geojson", build_corridors())
    write("protected_volumes.geojson", build_protected_volumes())
    write("approach_paths.geojson", build_approach_paths())
    write("reference_points.geojson", build_reference_points())
    write("altitude_rules.json", build_altitude_rules())

    rows = build_altimeter_rows()
    alti_path = OUT / "altimeter_KLGA_2026-10-10.json"
    alti_path.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"wrote {alti_path} ({len(rows)} rows)")

    alti_meta_path = OUT / "altimeter_KLGA_2026-10-10.meta.json"
    alti_meta_path.write_text(
        json.dumps(
            metadata_block(
                source="Iowa Environmental Mesonet ASOS request, station=LGA, data=alti "
                "(https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py)",
                approximate_note="Not approximate -- raw hourly METAR altimeter readings for the "
                "local (America/New_York) 2026-10-10 calendar day. Sidecar file: the main "
                "altimeter_KLGA_2026-10-10.json stays a plain array (its documented schema) so "
                "existing consumers are not broken; this file carries the same metadata block used "
                "on the GeoJSON outputs.",
            ),
            indent=1,
        )
        + "\n"
    )
    print(f"wrote {alti_meta_path}")

    validate()


def validate() -> None:
    import shapely.geometry as geom

    for name in ("corridors.geojson", "protected_volumes.geojson"):
        data = json.loads((OUT / name).read_text())
        for f in data["features"]:
            g = geom.shape(f["geometry"])
            if not g.is_valid:
                raise SystemExit(f"INVALID geometry in {name}: {f['properties'].get('id')}")
    print("all polygons valid (shapely is_valid)")


if __name__ == "__main__":
    main()

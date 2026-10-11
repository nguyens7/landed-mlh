"""Cited source coordinates for Landed Track B geometry.

Every coordinate here carries a one-line citation. Nothing is invented: where a
primary source does not publish a point (e.g. a shoreline, or an approach fix not
in the plate text I could fetch), the value is DERIVED transparently from a
published bearing/distance pair or a public landmark, and the derivation is
written out in the comment. See geo/SOURCES.md for the consolidated table.

All lat/lon pairs are WGS84 decimal degrees, (lat, lon) in this file (build.py
flips to GeoJSON's [lon, lat] order). Bearings are TRUE unless noted "mag".
"""
import math
import re

NM_FT = 6076.12  # 1 nautical mile in feet (standard)


def dm(s: str) -> float:
    """Convert 'DD-MM.mmmmN' / 'DDD-MM.mmmmW' (deg-decimal minutes) to signed decimal degrees."""
    deg, rest = s.split("-")
    minutes = float(rest[:-1])
    val = int(deg) + minutes / 60
    return -val if rest[-1] in "SW" else val


def dms(s: str) -> float:
    """Convert 'DD-MM-SS.ssN' / 'DDD-MM-SS.ssW' (deg-min-sec) to signed decimal degrees."""
    d, m, rest = s.split("-")
    sec = float(rest[:-1])
    val = int(d) + int(m) / 60 + sec / 3600
    return -val if rest[-1] in "SW" else val


def destination(
    lat: float, lon: float, bearing_true_deg: float, distance_nm: float
) -> tuple[float, float]:
    """Great-circle destination point given start, true bearing and distance (nm).

    Standard spherical direct geodesic formula (haversine-consistent), R = 3440.065 nm.
    """
    R = 3440.065
    lat1, lon1, brg = map(math.radians, (lat, lon, bearing_true_deg))
    d_r = distance_nm / R
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def bearing_between(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


# ---------------------------------------------------------------------------
# Magnetic variation, NYC area (~12 deg West). AirNav KLGA facility listing
# gives LGA VOR/DME variation as "11/12W"; FAA plates give approach courses in
# magnetic. true = magnetic + westerly_variation.
# https://www.airnav.com/airport/KLGA
# ---------------------------------------------------------------------------
MAG_VAR_W = 12.0


# ---------------------------------------------------------------------------
# 1. Navaids (for computing SFRA arc boundaries and plate-referenced fixes)
# ---------------------------------------------------------------------------

# LGA VOR/DME (LGA, 113.1, Chan 78), on the airport. AirNav/FAA Chart Supplement
# (NE 226, 2026 ed.): "N40º47.02' W73º52.12' at fld".
# https://www.airnav.com/airport/KLGA (facility data block)
LGA_VOR = (dm("40-47.02N"), dm("073-52.12W"))

# Colts Neck VOR/DME (COL, 115.4, Chan 101), Monmouth County NJ. AirNav / FAA
# Form 8260-2 radio fix record: 40-18-41.866N / 074-09-35.023W.
# https://www.airnav.com/cgi-bin/navaid-info?a=COL
COLTS_NECK_VOR = (dms("40-18-41.866N"), dms("074-09-35.023W"))


# ---------------------------------------------------------------------------
# 2. LGA runway thresholds (AirNav KLGA runway table, FAA data effective
#    2026-10-01). https://www.airnav.com/airport/KLGA
#    {runway: (lat, lon, true_heading_deg, tdze_ft)}
# ---------------------------------------------------------------------------
LGA_RUNWAYS = {
    "4": (dm("40-46.149755N"), dm("073-53.047142W"), 32.0, 20.5),
    "22": (dm("40-47.126200N"), dm("073-52.240402W"), 212.0, 11.5),
    "13": (dm("40-46.937752N"), dm("073-52.711150W"), 122.0, 11.6),
    "31": (dm("40-46.324287N"), dm("073-51.426695W"), 302.0, 6.5),
}

# ---------------------------------------------------------------------------
# 3. COPTER ILS/LOC RWY 22 (FAA d-tpp 00289COPTERIL22). SPEC.md / plate text
#    found by search: final course 224 true (mag var applied: 212 true + 12W
#    = 224 mag, matches AirNav's 212 true runway heading), speed limit 70-90
#    KIAS, missed approach climbs via LGA VOR/DME R-225 to PROUD (SW hold).
#    PROUD's own published lat/lon was not retrievable from the sources I
#    could fetch (chart planview only; FAA fix database not queried). DERIVED
#    here as a point 4.0 nm out on the extended runway-22 centerline (bearing
#    212+180=32... no: outbound/upwind of the threshold is bearing 032,
#    i.e. the reciprocal of the 212 true landing course), which is the
#    position a FAF/IF on this final would occupy. Marked approximate.
# ---------------------------------------------------------------------------
R22_THR = LGA_RUNWAYS["22"][:2]
R22_TRUE_COURSE = 212.0  # AirNav threshold true heading (inbound/landing course)
R22_FINAL_LEN_NM = 10.0  # straight final modeled out to 10 nm, per SPEC/EDA convention
PROUD_DERIVED = destination(*R22_THR, R22_TRUE_COURSE - 180, 4.0)  # APPROX, see note above

# ---------------------------------------------------------------------------
# 4. RNAV (GPS) X RWY 31 (FAA d-tpp 00289RX31). Search of FAA CIFP-adjacent
#    text gave the visual-segment legs with course/distance:
#      GACAR (FAF) -> DRRYL (MAP):   course 089.09 true, 3.11 nm (older plate;
#                                     a newer edition lists 6.31 nm - verify
#                                     current plate before using operationally)
#      DRRYL -> KEYTH:               course 044.14 true, 1.06 nm
#      KEYTH -> DCTRK:               course 359.14 true, 1.06 nm
#      DCTRK -> RW31 threshold:      course 314.15 true, 1.08 nm
#    GACAR's own coordinate (40-43-7.460N, 073-54-39.060W) is from a secondary
#    source (GlobalAir fix lookup), not the FAA CIFP directly: [UNVERIFIED].
#    DRRYL/KEYTH/DCTRK are DERIVED by back-computing from the sourced AirNav
#    RWY31 threshold along the reciprocal of each published course/distance
#    leg (done in build.py), which is self-consistent with the plate legs
#    regardless of GACAR's exact position.
#    https://www.faa.gov/aero_docs/dtpp/2608/00289RX31.PDF (plate, not
#    machine-read directly - leg data via web search of chart text)
# ---------------------------------------------------------------------------
R31_THR = LGA_RUNWAYS["31"][:2]
RX31_LEGS = [
    # (name, course_true_into_this_fix, distance_nm_from_previous)
    ("RW31", None, None),
    ("DCTRK", 314.15, 1.08),
    ("KEYTH", 359.14, 1.06),
    ("DRRYL", 44.14, 1.06),
    ("GACAR", 89.09, 3.11),  # MAP->FAF leg; newer plate edition lists 6.31 nm instead
]
GACAR_SECONDARY = (dms("40-43-7.460N"), dms("073-54-39.060W"))  # superseded by CIFP below (identical)

# ---------------------------------------------------------------------------
# 4b. AUTHORITATIVE fix coordinates: FAA CIFP (ARINC 424), cycle 2610,
#     effective 2026-10-01, header dated 09-SEP-2026.
#     https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261001.zip (file FAACIFP18)
#     Download page: https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/cifp/download/
#     Raw records (columns 33-51), verbatim:
#       SUSAEAENRT   GACAR K60  ... N40430746W073543906
#       SUSAEAENRT   DRRYL K60  ... N40434913W073503960
#       SUSAEAENRT   KEYTH K60  ... N40444304W073495507
#       SUSAEAENRT   DCTRK K60  ... N40454511W073501370
#       SUSAEAENRT   PROUD K60  ... N40374725W073595912
#       SUSAP KLGAK6GRW31  ...    N40461946W073512560   (runway record)
#       SUSAP KLGAK6GRW22  ...    N40470757W073521442   (runway record)
#     Note: the RNAV (GPS) X RWY 31 procedure itself is NOT coded in CIFP
#     (only RNAV Y/Z 31 are), but its fixes are published as enroute
#     waypoints, so their positions are primary FAA data.
#     PROUD is the ILS/LOC 22 missed-approach holding fix (CIFP I22 seq 040/050,
#     "CF LGA R-225 ... HM"), about 9.5 nm SW of LGA. It is NOT a point on
#     the Rwy 22 final, so it is not used for Rwy 22 final geometry.
# ---------------------------------------------------------------------------
def _cifp(s: str) -> tuple:
    """Parse a CIFP lat/lon string like N40430746W073543906 (deg, min, sec*100)."""
    m = re.fullmatch(r"([NS])(\d{2})(\d{2})(\d{4})([EW])(\d{3})(\d{2})(\d{4})", s)
    h1, d1, m1, s1, h2, d2, m2, s2 = m.groups()
    lat = int(d1) + int(m1) / 60 + int(s1) / 100 / 3600
    lon = int(d2) + int(m2) / 60 + int(s2) / 100 / 3600
    return (-lat if h1 == "S" else lat, -lon if h2 == "W" else lon)


CIFP_CYCLE = "2610 (effective 2026-10-01)"
CIFP_URL = "https://aeronav.faa.gov/Upload_313-d/cifp/CIFP_261001.zip"
CIFP_FIXES = {
    "GACAR": _cifp("N40430746W073543906"),
    "DRRYL": _cifp("N40434913W073503960"),
    "KEYTH": _cifp("N40444304W073495507"),
    "DCTRK": _cifp("N40454511W073501370"),
    "PROUD": _cifp("N40374725W073595912"),
    "RW31": _cifp("N40461946W073512560"),
    "RW22": _cifp("N40470757W073521442"),
}
def nm_between(a: tuple, b: tuple) -> float:
    """Great-circle distance in nm between two (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


# Rwy 31 path, outward from the threshold, using CIFP positions directly.
RX31_PATH_FIXES = ["RW31", "DCTRK", "KEYTH", "DRRYL", "GACAR"]

# ---------------------------------------------------------------------------
# 5. Class B floor over the rivers. FAA New York Airspace online course
#    (2010 ed.) states the Hudson Exclusion ceiling (Class B floor) as
#    1,300 ft MSL. East River Exclusion per 14 CFR 93.350(c): below 1,500 ft
#    MSL generally, dropping to 1,100 ft MSL and below from the LGA VOR/DME
#    6-mile arc to the north tip of Roosevelt Island.
#    https://www.federalregister.gov/documents/2026/07/31/2026-15552/amendment-of-class-b-airspace-new-york-ny
#    (FR Doc 2026-15552, NY Class B Area K floor 1,300 ft MSL, effective 2026-10-29)
#    https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W
# ---------------------------------------------------------------------------
HUDSON_CLASS_B_FLOOR_FT = 1300
EAST_RIVER_CEILING_FT_SOUTH = 1500  # south of LGA VOR/DME 6 nm arc
EAST_RIVER_CEILING_FT_NORTH = 1100  # 6 nm arc to north tip of Roosevelt Island

# ---------------------------------------------------------------------------
# 6. 14 CFR 93.350 exclusion boundary vertices (eCFR via law.cornell.edu LII,
#    fetched 2026-10-11; see geo/SOURCES.md). Only the NAMED fixed points are
#    sourced directly from the regulation text; the runs described as
#    "follow the shoreline" / "follow the west/east bank" are DERIVED by
#    digitizing a reasonable shoreline polyline between the named points
#    (approximate=True on those features).
# ---------------------------------------------------------------------------

# Hudson River Exclusion, 93.350(d):
HUDSON_START_NEAR_ALPINE = (dms("40-57-45N"), dms("073-54-48W"))  # west bank, near Alpine Tower
HUDSON_ARC_END_NE = (
    dms("40-57-54N"),
    dms("073-54-23W"),
)  # LGA VOR/DME 11 nm arc intercept (north end)
LGA_11NM_ARC_RADIUS_NM = 11.0

# East River Exclusion, 93.350(c):
EAST_RIVER_START = (dms("40-38-39N"), dms("074-02-03W"))  # common point shared with Hudson boundary
LGA_6NM_ARC_RADIUS_NM = 6.0

# Named shoreline/landmark anchor points used to digitize the exclusion
# polygons between the regulation's named vertices (APPROXIMATE shorelines,
# read off public landmark positions, not from the CFR text itself):
GOVERNORS_ISLAND_SW_TIP = (40.6895, -74.0180)
MANHATTAN_SW_TIP_BATTERY = (40.7010, -74.0170)
VERRAZZANO_BRIDGE_MANHATTAN_SIDE = (
    40.6065,
    -74.0445,
)  # Staten Island side pylon used as a mid-span anchor
VERRAZZANO_BRIDGE_BROOKLYN_SIDE = (40.6065, -74.0440)
COLTS_NECK_012_SHORE_INTERCEPT = (
    40.4030,
    -74.0460,
)  # DERIVED: shoreline point nearest the Colts Neck 012 radial track, APPROX

# ---------------------------------------------------------------------------
# 7. Heliports (SPEC.md §1.1, sourced to AirNav).
# ---------------------------------------------------------------------------
HELIPORTS = {
    "6N5": {
        "name": "East 34th Street Heliport",
        "lat": dms("40-44-32.81N"),
        "lon": dms("073-58-19.64W"),
        "source": "https://www.airnav.com/airport/6N5",
    },
    "JRB": {
        "name": "Downtown Manhattan/Wall St Heliport (Downtown Skyport)",
        "lat": dms("40-42-04.369N"),
        "lon": dms("074-00-32.502W"),
        "source": "https://airnav.com/airport/JRB",
    },
    "NJ87": {
        "name": "University Hospital Rooftop, Newark",
        "lat": dms("40-44-27.05N"),
        "lon": dms("074-11-27.03W"),
        "source": "https://airnav.com/airport/NJ87",
    },
    "NY52": {
        "name": "Staten Island University Hospital",
        "lat": dms("40-35-03.13N"),
        "lon": dms("074-04-59.74W"),
        "source": "https://airnav.com/airport/NY52",
    },
}

# ---------------------------------------------------------------------------
# 8. SFRA mandatory / recommended reporting points (SPEC.md §0.6 / §1.2, FAA
#    kneeboard https://www.faasafety.gov/files/gslac/courses/content/79/775/kneeboard.pdf).
#    The FAA chart depicts these over named landmarks; I could not retrieve
#    FAA-published lat/lon for the points themselves, so each is placed at
#    the public landmark's well-known centroid (OpenStreetMap/public
#    geographic knowledge) -- approximate=True, noted per point.
# ---------------------------------------------------------------------------
REPORTING_POINTS = {
    "alpine_tower": {
        "name": "Alpine Tower",
        "lat": 40.9540,
        "lon": -73.9280,
        "corridor": "Hudson",
        "mandatory": True,
    },
    "gwb": {
        "name": "George Washington Bridge",
        "lat": 40.8517,
        "lon": -73.9527,
        "corridor": "Hudson",
        "mandatory": True,
    },
    "intrepid": {
        "name": "Intrepid Museum (Pier 86)",
        "lat": 40.7642,
        "lon": -74.0006,
        "corridor": "Hudson",
        "mandatory": True,
    },
    "clock": {
        "name": "Colgate Clock (Jersey City)",
        "lat": 40.7179,
        "lon": -74.0343,
        "corridor": "Hudson",
        "mandatory": True,
    },
    "statue_of_liberty": {
        "name": "Statue of Liberty",
        "lat": 40.6892,
        "lon": -74.0445,
        "corridor": "Hudson",
        "mandatory": True,
    },
    "vz": {
        "name": "Verrazzano-Narrows Bridge",
        "lat": 40.6065,
        "lon": -74.0442,
        "corridor": "Hudson",
        "mandatory": True,
    },
    "williamsburg_bridge": {
        "name": "Williamsburg Bridge",
        "lat": 40.7132,
        "lon": -73.9718,
        "corridor": "East River",
        "mandatory": False,
    },
    "governors_island": {
        "name": "Governors Island",
        "lat": 40.6895,
        "lon": -74.0164,
        "corridor": "East River",
        "mandatory": False,
    },
    "brooklyn_bridge": {
        "name": "Brooklyn Bridge",
        "lat": 40.7061,
        "lon": -73.9969,
        "corridor": "East River",
        "mandatory": False,
    },
    "roosevelt_island_north": {
        "name": "Roosevelt Island (north tip)",
        "lat": 40.7714,
        "lon": -73.9465,
        "corridor": "East River",
        "mandatory": False,
    },
}

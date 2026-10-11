"""Assembles real OSM tidal-water multipolygon relations into cached, dissolved
water polygons for the Hudson River and East River: water_hudson.geojson and
water_eastriver.geojson. Reads the raw Overpass relation dumps already saved
in water_cache/ (fetched one-off via the public Overpass API, overpass-api.de,
using `rel(<id>);(._;>;);out geom qt;` for each relation below -- re-fetching
needs the `Referer: https://overpass-turbo.eu/` header, or overpass-api.de
answers every plain request with HTTP 406; even with that header the public
instance is frequently saturated and returns HTTP 504, so fetching needed
several retries per relation). No network calls happen when this file (or
build.py, which imports its output) runs normally -- it only re-parses the
cached JSON.

Data: (c) OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
Relations used (each tagged natural=water, water=river, type=multipolygon;
found via `relation(around:400,<lat>,<lon>)["natural"="water"]` probes along
the two rivers, since neither river is a single relation end to end):

  Hudson River (adjacent to Manhattan):
    - 2389611 -- covers roughly 40.707N-40.795N (Battery/West Village to ~79th St)
    - 2389521 -- covers roughly 40.791N-40.884N (~79th St to north of the GWB)
  East River:
    - 2389633 -- "waterway:name=East River", roughly 40.688N-40.748N (Governors
      Island/Brooklyn Bridge to the south end of Roosevelt Island)
    - 2389563 "West Channel" / 2389581 "East Channel" -- the two channels
      around Roosevelt Island
    - 20805948 -- "waterway:name=East River", roughly 40.773N-40.798N (north
      of Roosevelt Island, Queensboro/Hell Gate area)

These relations do NOT reach the regulation's named endpoints (Hudson: near
Alpine Tower in the north, the Verrazzano-Narrows area in the south; East
River: the 93.350(c) start vertex in the south). The public Overpass API was
too saturated (repeated HTTP 504s) to retrieve the additional relations (if
any even exist as simple `water=river` polygons -- the wider harbor/bay south
of the Battery and north of the GWB may be tagged as a bay/sea feature
instead) covering those extensions within the time available. build.py fills
those short extensions with a constant-width buffer around a hand-placed
centerline (same technique as the original approximation), clearly flagged
`approximate: true`; everywhere the real OSM polygons apply, build.py uses
them directly and does NOT set `approximate` for the shoreline itself.
"""

import json
from pathlib import Path

from shapely.geometry import LineString, mapping
from shapely.ops import polygonize, unary_union

HERE = Path(__file__).resolve().parent
CACHE = HERE / "water_cache"

HUDSON_RELS = ["hudson_rel_2389611.json", "hudson_rel_2389521.json"]
EAST_RIVER_RELS = [
    "eastriver_rel_2389633.json",
    "eastriver_rel_2389563_westchannel.json",
    "eastriver_rel_2389581_eastchannel.json",
    "eastriver_rel_20805948.json",
]


def polygon_from_relation_dump(path: Path):
    data = json.loads(path.read_text())
    ways = {e["id"]: e for e in data["elements"] if e["type"] == "way"}
    rel = next(e for e in data["elements"] if e["type"] == "relation")
    outer = []
    for m in rel["members"]:
        if m["type"] != "way" or m["role"] != "outer":
            continue
        w = ways.get(m["ref"])
        if not w or "geometry" not in w:
            continue
        coords = [(p["lon"], p["lat"]) for p in w["geometry"]]
        if len(coords) >= 2:
            outer.append(LineString(coords))
    polys = list(polygonize(outer))
    if not polys:
        return None
    return max(polys, key=lambda p: p.area)


def build_river(rel_files: list[str]):
    polys = []
    for fname in rel_files:
        p = polygon_from_relation_dump(CACHE / fname)
        if p is not None:
            polys.append(p)
    return unary_union(polys)


def main() -> None:
    hudson = build_river(HUDSON_RELS)
    east_river = build_river(EAST_RIVER_RELS)
    for name, geom in [("water_hudson.geojson", hudson), ("water_eastriver.geojson", east_river)]:
        out = {
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "source": "OpenStreetMap contributors via Overpass API, ODbL 1.0",
                "relations": HUDSON_RELS if "hudson" in name else EAST_RIVER_RELS,
            },
        }
        (HERE / name).write_text(json.dumps(out))
        print(f"wrote {HERE / name}: area={geom.area:.6f} deg^2, bounds={geom.bounds}")


if __name__ == "__main__":
    main()

"""One-off fetch: downloads OSM administrative-boundary polygons (via the public
Nominatim search API, polygon_geojson=1) for every landmass bordering the
Hudson River and East River SFRA corridors, unions them, and caches the result
as land_union.geojson. build.py reads this cache at build time (no network
calls there, keeping the pipeline deterministic); re-run this file only when
the cached land polygon needs refreshing.

Data: (c) OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
Source API: https://nominatim.openstreetmap.org/ (usage policy: max 1 req/s,
identifying User-Agent, no bulk geocoding -- this script makes ~20 one-off
requests with a 1.1 s delay between them, for research/demo use).

Why admin boundaries instead of water polygons: the public Overpass API
mirrors reachable from this environment were either down, anti-bot blocked,
or an empty test instance (see SOURCES.md); Nominatim's place-boundary search
was reachable and NYC-area municipal boundaries in OSM are digitized to the
actual shoreline (confirmed by inspection against real ADS-B helicopter
tracks in check.png), so "water between these shoreline-accurate land
polygons" is a faithful proxy for the legal from-shoreline-to-shoreline
exclusion, more accurate than a hand-drawn centerline buffer.
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
CACHE = HERE / "land_cache"
CACHE.mkdir(exist_ok=True)

PLACES = [
    "Manhattan, New York",
    "Brooklyn, New York",
    "Queens, New York",
    "The Bronx, New York",
    "Staten Island, New York",
    "Roosevelt Island, New York",
    "Governors Island, New York",
    "Yonkers, New York",
    "Hoboken, New Jersey",
    "Jersey City, New Jersey",
    "Weehawken, New Jersey",
    "Union City, New Jersey",
    "West New York, New Jersey",
    "North Bergen, New Jersey",
    "Edgewater, New Jersey",
    "Fort Lee, New Jersey",
    "Englewood Cliffs, New Jersey",
    "Tenafly, New Jersey",
    "Alpine, New Jersey",
    "Bayonne, New Jersey",
]

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "LandedGeo-hackathon-research/1.0 (track-B geometry, one-off fetch)"


def fetch_one(place: str) -> dict | None:
    slug = place.replace(", ", "_").replace(" ", "_")
    cache_path = CACHE / f"{slug}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    url = f"{NOMINATIM}?{urllib.parse.urlencode({'q': place, 'format': 'json', 'polygon_geojson': 1, 'limit': 1})}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf8"))
    cache_path.write_text(json.dumps(data))
    time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    return data


def main() -> None:
    geoms = []
    for place in PLACES:
        data = fetch_one(place)
        if not data:
            print(f"WARNING: no result for {place!r}")
            continue
        geoms.append(shape(data[0]["geojson"]))
        print(f"{place}: {data[0]['display_name']} ({data[0]['geojson']['type']})")
    land_union = unary_union(geoms)
    out = {
        "type": "Feature",
        "geometry": mapping(land_union),
        "properties": {
            "source": "OpenStreetMap contributors via Nominatim (https://nominatim.openstreetmap.org/), ODbL 1.0",
            "places": PLACES,
        },
    }
    (HERE / "land_union.geojson").write_text(json.dumps(out))
    print(f"wrote {HERE / 'land_union.geojson'} ({len(geoms)} source polygons unioned)")


if __name__ == "__main__":
    main()

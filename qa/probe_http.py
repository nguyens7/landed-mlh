"""Check a running Landed server and the data assets needed by the replay desk."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

REPLAY_PATHS = ("saturday", "sim_medevac")
GEO_PATHS = ("corridors", "protected_volumes", "approach_paths", "reference_points")


def fetch(base_url: str, path: str) -> bytes:
    with urlopen(f"{base_url.rstrip('/')}{path}", timeout=10) as response:
        if response.status != 200:
            raise ValueError(f"{path}: expected HTTP 200, got {response.status}")
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:4180")
    args = parser.parse_args()
    try:
        page = fetch(args.base_url, "/").decode()
        if '<div id="root">' not in page or "Landed" not in page:
            raise ValueError("/: response is not the Landed app shell")
        print("PASS /: Landed app shell")
        for name in REPLAY_PATHS:
            path = f"/data/replay/{name}.json"
            data = json.loads(fetch(args.base_url, path))
            aircraft = data["aircraft"]
            if not aircraft or any(not ac["points"] for ac in aircraft):
                raise ValueError(f"{path}: replay must have aircraft with points")
            print(f"PASS {path}: {len(aircraft)} aircraft")
        for name in GEO_PATHS:
            path = f"/data/geo/{name}.geojson"
            data = json.loads(fetch(args.base_url, path))
            if data["type"] != "FeatureCollection" or not data["features"]:
                raise ValueError(f"{path}: expected a nonempty FeatureCollection")
            print(f"PASS {path}: {len(data['features'])} features")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

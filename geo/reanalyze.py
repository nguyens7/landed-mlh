"""Re-run the EDA corridor-membership / approach-proximity analysis using the
new sourced Track B geometry, and report what changed vs. the OLD approximate
numbers from eda/scripts/analyze.py (whose hand-drawn corridors/approaches are
copied here read-only for comparison -- eda/ itself is not modified).

Run from this directory: `uv run python reanalyze.py`. Reads the same raw
traces as check.py (absolute path, 177 MB, never committed). Writes
geo/figures/corridor_membership_new.png and geo/figures/alt_vs_ceilings_new.png.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from altitude import baro_to_msl

TRACES = Path(
    os.environ.get(
        "LANDED_TRACES",
        Path(__file__).resolve().parent.parent / "eda/data/history_nyc_traces.jsonl",
    )
)
GEO_OUT = Path(__file__).resolve().parent.parent / "app/public/data/geo"
FIGDIR = Path(__file__).resolve().parent / "figures"
FIGDIR.mkdir(exist_ok=True)

NM = 1852.0

# --- OLD approximate geometry, copied read-only from eda/scripts/analyze.py
# (not imported, so a change there can't silently change this comparison) ---
OLD_HUDSON = [
    (40.607, -74.040),
    (40.689, -74.046),
    (40.703, -74.022),
    (40.765, -74.002),
    (40.851, -73.955),
    (40.962, -73.913),
]
OLD_EAST = [
    (40.689, -74.016),
    (40.706, -73.997),
    (40.713, -73.972),
    (40.742, -73.969),
    (40.772, -73.940),
]


def xy(lat, lon, lat0=40.75):
    return (
        (np.asarray(lon) + 73.95) * 60 * math.cos(math.radians(lat0)),
        (np.asarray(lat) - lat0) * 60,
    )


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / l2, 0, 1)
    return np.hypot(px - (ax + t * dx), py - (ay + t * dy))


def poly_dist(px, py, line):
    xs, ys = xy([p[0] for p in line], [p[1] for p in line])
    return np.min(
        [seg_dist(px, py, xs[i], ys[i], xs[i + 1], ys[i + 1]) for i in range(len(xs) - 1)], axis=0
    )


def load_history():
    rows = []
    with open(TRACES) as f:
        for line in f:
            d = json.loads(line)
            cat = None
            for p in d["pts"]:
                if len(p) > 8 and isinstance(p[8], dict):
                    cat = cat or p[8].get("category")
            if cat != "A7":
                continue
            for p in d["pts"]:
                alt = p[3]
                geom = p[10] if len(p) > 10 else None
                rows.append(
                    {
                        "icao": d["icao"],
                        "ts": d["base_ts"] + p[0],
                        "lat": p[1],
                        "lon": p[2],
                        "alt_baro": None if alt in (None, "ground") else alt,
                        "ground": alt == "ground",
                        "alt_geom": geom,
                    }
                )
    h = pd.DataFrame(rows)
    h["t"] = pd.to_datetime(h.ts, unit="s", utc=True).dt.tz_convert("America/New_York")
    return h


def nearest_altimeter(ts_epoch, rows):
    best, best_dt = None, None
    for row in rows:
        t = datetime.fromisoformat(row["time"]).timestamp()
        dt = abs(t - ts_epoch)
        if best_dt is None or dt < best_dt:
            best, best_dt = row["altimeter_inhg"], dt
    return best


def main() -> None:
    h = load_history()
    print(f"loaded {len(h)} points, {h.icao.nunique()} helicopters")

    px, py = xy(h.lat.values, h.lon.values)

    # --- OLD corridor membership: distance-threshold vs hand-drawn centerlines
    h["d_hudson_old"] = poly_dist(px, py, OLD_HUDSON)
    h["d_east_old"] = poly_dist(px, py, OLD_EAST)
    h["corridor_old"] = np.where(
        h.d_hudson_old < 0.35, "Hudson", np.where(h.d_east_old < 0.25, "East River", "other")
    )

    # --- NEW corridor membership: point-in-polygon vs the sourced geometry
    corridors = json.loads((GEO_OUT / "corridors.geojson").read_text())
    by_id = {f["properties"]["id"]: shape(f["geometry"]) for f in corridors["features"]}
    hudson_poly = by_id["sfra_hudson"]
    east_poly = unary_union([by_id["sfra_east_river_south"], by_id["sfra_east_river_north"]])

    def classify_new(lat, lon):
        pt = Point(lon, lat)
        if hudson_poly.contains(pt):
            return "Hudson"
        if east_poly.contains(pt):
            return "East River"
        return "other"

    h["corridor_new"] = [classify_new(lat, lon) for lat, lon in zip(h.lat, h.lon, strict=False)]

    print(
        "\n--- Corridor membership: OLD (hand-drawn centerline buffer) vs NEW (real shoreline polygon) ---"
    )
    old_counts = h.corridor_old.value_counts()
    new_counts = h.corridor_new.value_counts()
    print("OLD:", old_counts.to_dict())
    print("NEW:", new_counts.to_dict())
    agree = (h.corridor_old == h.corridor_new).mean() * 100
    print(f"OLD/NEW classification agreement: {agree:.1f}% of all points")
    for c in ("Hudson", "East River"):
        old_in_c = h.corridor_old == c
        new_in_c = h.corridor_new == c
        both = (old_in_c & new_in_c).sum()
        only_old = (old_in_c & ~new_in_c).sum()
        only_new = (~old_in_c & new_in_c).sum()
        print(
            f"{c}: both={both}, old-only={only_old} (now classified as new-'{h.corridor_new[old_in_c & ~new_in_c].mode().iat[0] if only_old else '-'}'), new-only={only_new}"
        )

    # --- Altitude correction: OLD (alt_geom - 105 ft) vs NEW (baro_to_msl with real METAR)
    altimeter_rows = json.loads((GEO_OUT / "altimeter_KLGA_2026-10-10.json").read_text())
    h["alt_geom_msl_old"] = h.alt_geom - 105
    h["setting"] = h.ts.map(lambda ts: nearest_altimeter(ts, altimeter_rows))
    h["alt_baro_msl_new"] = h.apply(
        lambda r: baro_to_msl(r.alt_baro, r.setting) if pd.notna(r.alt_baro) else np.nan, axis=1
    )

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for a, (c, ceil) in zip(ax, [("Hudson", [1300]), ("East River", [1500, 1100])], strict=False):
        s_new = h[h.corridor_new == c]
        a.hist(
            s_new.alt_baro_msl_new.dropna(),
            bins=range(0, 3000, 100),
            alpha=0.6,
            label="NEW: baro_to_msl (real METAR)",
        )
        a.hist(
            s_new.alt_geom_msl_old.dropna(),
            bins=range(0, 3000, 100),
            alpha=0.6,
            label="OLD: alt_geom - 105 ft",
        )
        for v in ceil:
            a.axvline(v, color="r", ls="--")
            a.text(v + 20, a.get_ylim()[1] * 0.9, f"{v} ft", color="r")
        a.set_title(f"{c} corridor (NEW membership), n={len(s_new)} pts")
        a.set_xlabel("ft MSL")
        a.legend(fontsize=7)
    fig.suptitle("Helicopter altitudes vs SFRA ceilings: old vs new MSL correction, 2026-10-10")
    fig.tight_layout()
    fig.savefig(FIGDIR / "alt_vs_ceilings_new.png", dpi=130)
    print(f"\nwrote {FIGDIR / 'alt_vs_ceilings_new.png'}")

    for c, ceil in [("Hudson", 1300), ("East River", 1500)]:
        s = h[h.corridor_new == c]
        pct_old = (s.alt_geom_msl_old > ceil).mean() * 100
        pct_new = (s.alt_baro_msl_new > ceil).mean() * 100
        print(
            f"{c}: pct points > {ceil} ft MSL -- OLD correction {pct_old:.1f}%, NEW correction {pct_new:.1f}%"
        )

    # --- Map figure ---
    fig, a = plt.subplots(figsize=(8, 9))
    for ic, s in h.groupby("icao"):
        a.plot(s.lon, s.lat, "-", lw=0.5, alpha=0.6, color="tab:blue")
    for name, poly in [("Hudson (new)", hudson_poly), ("East River (new)", east_poly)]:
        geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            xs, ys = g.exterior.xy
            a.fill(xs, ys, alpha=0.3, label=name if g == geoms[0] else None)
    a.set_xlim(-74.25, -73.70)
    a.set_ylim(40.55, 40.95)
    a.set_aspect(1 / math.cos(math.radians(40.75)))
    a.set_title("Corridor membership (NEW sourced geometry), 2026-10-10")
    a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGDIR / "corridor_membership_new.png", dpi=130)
    print(f"wrote {FIGDIR / 'corridor_membership_new.png'}")


if __name__ == "__main__":
    main()

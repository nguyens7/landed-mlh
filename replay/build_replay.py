"""Builds the Track A replay data for the Landed app.

Writes:
- ../app/public/data/replay/saturday.json  -- real Sat 2026-10-10 helicopter
  traffic for the busiest ~15-minute window, downsampled to ~2s.
- ../app/public/data/replay/sim_medevac.json -- a scripted fictional medevac
  track (N312LM, EC35/H135) from the E 34th St heliport (6N5) direct toward the
  College Point area at 600 ft MSL, timed so it enters the LGA Rwy 22 final's
  sourced glidepath volume (the real segmented polygons + floor/ceiling bands in
  app/public/data/geo/protected_volumes.geojson) mid-window (SPEC.md section 4,
  scenario S2). Flying low under the arrival path is the DCA-style conflict.

Run: `uv run python build_replay.py` from this directory. Pass `--sim-only` to
regenerate only sim_medevac.json (no 177 MB trace file needed).

Input (NOT in this worktree, NEVER commit it -- see SPEC.md and the global
.gitignore): ../eda/data (read-only; this script never writes there) plus the
full-day trace file passed via --traces, or the LANDED_TRACES environment
variable (falls back to the original local path only if that file exists).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import os
from pathlib import Path

from landed_geo import (
    R22_THR,
    SIM_MEDEVAC_ROUTE,
    great_circle_dist_nm,
)
from landed_timing import route_positions

HERE = Path(__file__).resolve().parent
APP_DATA = HERE.parent / "app" / "public" / "data"
EDA_DATA = HERE.parent / "eda" / "data"
# Default full-day trace capture; only used when it exists. Override with --traces or the
# LANDED_TRACES environment variable.
_LOCAL_TRACES = Path(__file__).resolve().parent.parent / "eda/data/history_nyc_traces.jsonl"
DEFAULT_TRACES = _LOCAL_TRACES if _LOCAL_TRACES.exists() else None

WINDOW_START_LOCAL = "2026-10-10T11:00:00-04:00"
WINDOW_SECONDS = 15 * 60
DOWNSAMPLE_S = 2.0
HEX_MEDEVAC = "SIM312LM"

# Display-only fixed-wing layer (airliners on LGA approaches/departures).
LGA_ARP = (40.7769, -73.8740)
FW_CATEGORIES = {"A1", "A2", "A3", "A4", "A5"}
FW_RADIUS_NM = 12.0
FW_CEILING_FT = 4000
FW_DOWNSAMPLE_S = 4.0


def load_role_guesses() -> dict[str, dict]:
    """Owner/role_guess metadata from the EDA CSV (read-only; eda/ is not ours to modify).
    The CSV's first column is the pandas row index (icao hex) with an empty header name."""
    path = EDA_DATA / "helicopters_2026-10-10.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        print(f"WARNING: {path} not found; aircraft metadata will be sparse")
        return out
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            d = dict(zip(header, row, strict=False))
            out[row[0]] = d
    return out


def load_altimeter(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def altimeter_at(series: list[dict], epoch_s: float) -> float | None:
    """Nearest altimeter_inhg reading (by time) to epoch_s. series sorted by time."""
    import datetime

    target = datetime.datetime.fromtimestamp(epoch_s, datetime.UTC)
    best = None
    best_dt = None
    for row in series:
        t = datetime.datetime.fromisoformat(row["time"])
        dt = abs((t - target).total_seconds())
        if best_dt is None or dt < best_dt:
            best_dt, best = dt, row["altimeter_inhg"]
    return best


def extract_real_traffic(
    traces_path: Path,
    window_start_epoch: float,
    role_guesses: dict,
    fixed_wing_out: list[dict] | None = None,
) -> list[dict]:
    """Returns the A7 helicopters. When fixed_wing_out is a list, also appends fixed-wing
    aircraft (category A1-A5) within FW_RADIUS_NM of LGA and below FW_CEILING_FT MSL
    (display-only; never fed to the conflict engine)."""
    altimeter_path = APP_DATA / "geo" / "altimeter_KLGA_2026-10-10.json"
    altimeter_series = load_altimeter(altimeter_path)
    if altimeter_series is None:
        print(
            "WARNING: no altimeter_KLGA_2026-10-10.json from Track B yet; "
            "falling back to alt_geom - 105 ft (see eda/scripts/analyze.py) for alt_ft_msl"
        )

    window_end_epoch = window_start_epoch + WINDOW_SECONDS
    aircraft: list[dict] = []
    n_scanned = 0
    with open(traces_path) as f:
        for line in f:
            n_scanned += 1
            d = json.loads(line)
            cat = None
            for p in d["pts"]:
                if len(p) > 8 and isinstance(p[8], dict):
                    cat = cat or p[8].get("category")
            is_fw = cat in FW_CATEGORIES and fixed_wing_out is not None
            if cat != "A7" and not is_fw:
                continue

            raw_points = []
            for p in d["pts"]:
                t = d["base_ts"] + p[0]
                if not (window_start_epoch <= t < window_end_epoch):
                    continue
                alt_baro = p[3]
                alt_geom = p[10] if len(p) > 10 else None
                if alt_baro in (None, "ground") or alt_geom is None:
                    continue
                if is_fw and not _near_lga(p[1], p[2]):
                    continue
                if altimeter_series is not None:
                    inhg = altimeter_at(altimeter_series, t)
                    alt_msl = alt_baro + (inhg - 29.92) * 1000
                else:
                    alt_msl = alt_geom - 105
                if is_fw and alt_msl >= FW_CEILING_FT:
                    continue
                raw_points.append(
                    {
                        "t": t - window_start_epoch,
                        "lat": p[1],
                        "lon": p[2],
                        "alt_ft_msl": round(alt_msl),
                        "gs_kt": p[4],
                        "track_deg": p[5],
                    }
                )
            if not raw_points:
                continue
            raw_points.sort(key=lambda r: r["t"])
            raw_points = repair_points(raw_points)
            if not raw_points:
                continue
            if is_fw:
                fixed_wing_out.append(
                    {
                        "hex": d["icao"],
                        "reg": d.get("r") or d["icao"].upper(),
                        "type": d.get("t"),
                        "owner": None,
                        "role_guess": "airliner" if cat in ("A3", "A4", "A5") else "fixed_wing",
                        "simulated": False,
                        "kind": "fixed_wing",
                        "points": downsample(raw_points, FW_DOWNSAMPLE_S),
                    }
                )
                continue
            points = downsample(raw_points, DOWNSAMPLE_S)
            meta = role_guesses.get(d["icao"], {})
            aircraft.append(
                {
                    "hex": d["icao"],
                    "reg": d.get("r"),
                    "type": d.get("t"),
                    "owner": meta.get("owner") or None,
                    "role_guess": meta.get("role_guess") or "other/charter/tour/private",
                    "simulated": False,
                    "points": [{k: v for k, v in r.items()} for r in points],
                }
            )
    print(
        f"scanned {n_scanned} global traces; kept {len(aircraft)} A7 helicopters active in window"
    )
    return aircraft


def _near_lga(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return great_circle_dist_nm(lat, lon, *LGA_ARP) <= FW_RADIUS_NM


def _bearing_deg(a: dict, b: dict) -> float:
    dlon = math.radians(b["lon"] - a["lon"])
    la, lb = math.radians(a["lat"]), math.radians(b["lat"])
    y = math.sin(dlon) * math.cos(lb)
    x = math.cos(la) * math.sin(lb) - math.sin(la) * math.cos(lb) * math.cos(dlon)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360, 1)


def repair_points(points: list[dict]) -> list[dict]:
    """Fix points with null gs_kt / track_deg (the app would read null as 0 and project a
    stationary aircraft). Derive them from the neighbouring points when possible, else drop
    the point. Points with a null position or altitude are dropped."""
    out: list[dict] = []
    n_fixed = n_dropped = 0
    for i, p in enumerate(points):
        if any(p[k] is None for k in ("lat", "lon", "alt_ft_msl")):
            n_dropped += 1
            continue
        if p["gs_kt"] is None or p["track_deg"] is None:
            prev = next((q for q in reversed(points[:i]) if q["lat"] is not None), None)
            nxt = next((q for q in points[i + 1 :] if q["lat"] is not None), None)
            a, b = (prev, nxt) if prev and nxt else (prev, p) if prev else (p, nxt)
            dt = (b["t"] - a["t"]) if a and b else 0
            if not a or not b or dt <= 0 or dt > 30:
                n_dropped += 1
                continue
            dist_nm = great_circle_dist_nm(a["lat"], a["lon"], b["lat"], b["lon"])
            p = dict(p)
            if p["gs_kt"] is None:
                p["gs_kt"] = round(dist_nm / dt * 3600, 1)
            if p["track_deg"] is None:
                p["track_deg"] = _bearing_deg(a, b)
            n_fixed += 1
        out.append(p)
    if n_fixed or n_dropped:
        print(f"  repaired {n_fixed} and dropped {n_dropped} null-gs/track points")
    return out


def downsample(points: list[dict], step_s: float) -> list[dict]:
    out = []
    next_t = -1.0
    for p in points:
        if p["t"] >= next_t:
            out.append(p)
            next_t = p["t"] + step_s
    return out


def load_protected_volumes() -> list[dict]:
    """The sourced, segmented protected volumes the app's conflict engine actually uses."""
    path = APP_DATA / "geo" / "protected_volumes.geojson"
    fc = json.loads(path.read_text())
    return [
        {**f["properties"], "ring": [tuple(c) for c in f["geometry"]["coordinates"][0]]}
        for f in fc["features"]
    ]


def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon; ring is (lon, lat) pairs like GeoJSON."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def first_rwy22_entry(samples: list[dict]) -> tuple[dict, dict] | None:
    """First track sample inside any lga22_final_seg* polygon AND its floor/ceiling band."""
    segs = [v for v in load_protected_volumes() if v["id"].startswith("lga22_final_seg")]
    for s in samples:
        for v in segs:
            if v["floor_ft_msl"] <= s["alt_ft"] <= v["ceiling_ft_msl"] and point_in_ring(
                s["lat"], s["lon"], v["ring"]
            ):
                return s, v
    return None


def build_sim_medevac(window_seconds: int) -> dict:
    """Scripted multi-leg track at 600 ft MSL, ~110 kt cruise, ~800 fpm climb (levels after
    45 s): 6N5 north up the East River, past the north side of Rikers Island, then direct
    College Point, which crosses a real Rwy 22 final glidepath segment (sourced polygon +
    altitude band). Liftoff is timed so that entry lands at roughly the window's midpoint."""
    route = SIM_MEDEVAC_ROUTE
    total_dist_nm = sum(great_circle_dist_nm(*a, *b) for a, b in itertools.pairwise(route))

    cruise_alt_ft = 600.0
    cruise_kt = 110.0
    climb_fpm = 800.0
    climb_time_s = (cruise_alt_ft / climb_fpm) * 60.0

    # Generate the track from liftoff (t=0), find the real-volume entry time, then shift
    # liftoff so the entry lands at window mid.
    samples = route_positions(
        route=route,
        climb_time_s=climb_time_s,
        cruise_alt_ft=cruise_alt_ft,
        cruise_kt=cruise_kt,
        step_s=DOWNSAMPLE_S,
    )
    found = first_rwy22_entry(samples)
    if found is None:
        raise RuntimeError(
            "sim medevac track never enters a Rwy 22 final segment's polygon + altitude band; "
            "adjust SIM_MEDEVAC_ROUTE or the cruise altitude"
        )
    entry, seg = found
    target_entry_t = window_seconds / 2.0
    liftoff_t = max(5.0, target_entry_t - entry["t"])

    points = [
        {
            "t": round(liftoff_t + s["t"], 1),
            "lat": s["lat"],
            "lon": s["lon"],
            "alt_ft_msl": round(s["alt_ft"]),
            "gs_kt": round(s["gs_kt"], 1),
            "track_deg": round(s["track_deg"], 1),
        }
        for s in samples
        if 0 <= liftoff_t + s["t"] <= window_seconds + 120  # a little slack past the window edge
    ]

    entry_t = liftoff_t + entry["t"]
    thr_dist = great_circle_dist_nm(*R22_THR, entry["lat"], entry["lon"])
    print(
        f"sim medevac: liftoff t={liftoff_t:.0f}s, {len(route) - 1} legs, "
        f"total dist={total_dist_nm:.1f} nm, climb {climb_fpm:.0f} fpm to {cruise_alt_ft:.0f} ft"
    )
    print(
        f"  enters {seg['id']} ({seg['name']}) at t={entry_t:.0f}s "
        f"(window mid={window_seconds / 2:.0f}s), {thr_dist:.1f} nm from the Rwy 22 threshold, "
        f"medevac {entry['alt_ft']:.0f} ft vs band {seg['floor_ft_msl']}-{seg['ceiling_ft_msl']} ft"
    )

    return {
        "hex": HEX_MEDEVAC,
        "reg": "N312LM",
        "type": "EC35",
        "owner": "SIMULATED",
        "role_guess": "medevac",
        "simulated": True,
        "points": points,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--traces",
        type=Path,
        default=Path(os.environ["LANDED_TRACES"]) if os.environ.get("LANDED_TRACES") else DEFAULT_TRACES,
        help="full-day traces JSONL (env LANDED_TRACES; local default used only if it exists)",
    )
    parser.add_argument(
        "--window-start-epoch", type=float, default=None, help="override window start (unix s)"
    )
    parser.add_argument(
        "--no-fixed-wing",
        action="store_true",
        help="skip writing saturday_fixedwing.json (display-only airliner layer)",
    )
    parser.add_argument("--sim-only", action="store_true", help="only regenerate sim_medevac.json")
    args = parser.parse_args()

    if args.sim_only:
        write_sim_only()
        return

    if args.window_start_epoch is not None:
        window_start_epoch = args.window_start_epoch
    else:
        import datetime

        window_start_epoch = datetime.datetime.fromisoformat(WINDOW_START_LOCAL).timestamp()

    if args.traces is None or not args.traces.exists():
        raise SystemExit(
            f"traces file not found: {args.traces}\n"
            "Pass --traces or set LANDED_TRACES to the 177 MB full-day ADS-B capture "
            "(kept outside the repo)."
        )

    role_guesses = load_role_guesses()
    fixed_wing: list[dict] | None = None if args.no_fixed_wing else []
    real_aircraft = extract_real_traffic(args.traces, window_start_epoch, role_guesses, fixed_wing)
    sim_aircraft = build_sim_medevac(WINDOW_SECONDS)

    out_dir = APP_DATA / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)

    saturday = {
        "metadata": {
            "window_start_utc": _iso_utc(window_start_epoch),
            "window_start_local": WINDOW_START_LOCAL,
            "window_seconds": WINDOW_SECONDS,
            "source": "adsb.lol globe_history 2026-10-10, ODbL",
            "downsample_s": DOWNSAMPLE_S,
            "altitude_correction": (
                "alt_baro + (altimeter_inhg - 29.92) * 1000, from geo/altimeter_KLGA_2026-10-10.json"
                if (APP_DATA / "geo" / "altimeter_KLGA_2026-10-10.json").exists()
                else "FALLBACK: alt_geom - 105 ft (no altimeter file found at build time)"
            ),
        },
        "aircraft": real_aircraft,
    }
    saturday_path = out_dir / "saturday.json"
    saturday_path.write_text(json.dumps(saturday))
    size_mb = saturday_path.stat().st_size / 1e6
    print(f"wrote {saturday_path} ({size_mb:.2f} MB, {len(real_aircraft)} aircraft)")
    if size_mb > 5:
        print("WARNING: saturday.json exceeds ~5 MB target; consider coarser downsampling")

    if fixed_wing is not None:
        fixed_wing = [a for a in fixed_wing if a["points"]]
        fw_path = out_dir / "saturday_fixedwing.json"
        fw_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        **saturday["metadata"],
                        "downsample_s": FW_DOWNSAMPLE_S,
                        "kind": "fixed_wing",
                        "filter": f"within {FW_RADIUS_NM:g} nm of KLGA, below {FW_CEILING_FT} ft MSL",
                        "note": "Display-only. Never passed to the conflict engine.",
                    },
                    "aircraft": fixed_wing,
                }
            )
        )
        print(f"wrote {fw_path} ({fw_path.stat().st_size / 1e6:.2f} MB, {len(fixed_wing)} aircraft)")

    _write_sim(out_dir, sim_aircraft)


def write_sim_only() -> None:
    out_dir = APP_DATA / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_sim(out_dir, build_sim_medevac(WINDOW_SECONDS))


def _write_sim(out_dir: Path, sim_aircraft: dict) -> None:
    sim_path = out_dir / "sim_medevac.json"
    sim_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "window_seconds": WINDOW_SECONDS,
                    "note": "Fictional scripted track for SPEC.md section 4 scenario S2. Not real ADS-B.",
                },
                "aircraft": [sim_aircraft],
            }
        )
    )
    print(f"wrote {sim_path} ({len(sim_aircraft['points'])} points)")


def _iso_utc(epoch_s: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(epoch_s, datetime.UTC).isoformat()


if __name__ == "__main__":
    main()

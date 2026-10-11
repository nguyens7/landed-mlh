# Landed: starter EDA (NYC helicopters vs LGA approaches)
Run: `python3 scripts/analyze.py` (from this folder). Inputs are already in `data/`.

## Data collected (all real, nothing synthetic)
| Source | What | Result | Terms |
|---|---|---|---|
| adsb.lol globe_history (GitHub release `v2026.10.10-planes-readsb-prod-0`, ~3.5 GB, streamed + filtered by `scripts/extract_globe_history.py`) | Full-day traces for **Sat 2026-10-10**, box 40.55–40.95N, 74.25–73.70W | 67,471 global traces scanned, **2,326 aircraft** in the box, **39 rotorcraft (A7)**, 78k helicopter points → `data/history_nyc_traces.jsonl` | ODbL 1.0 (attribute "adsb.lol, ODbL"); https://api.adsb.lol/docs |
| adsb.lol live `/v2/point/40.75/-73.95/20`, polled every 10 s for 25 min (`scripts/poll_adsblol.py`) | Sun 2026-10-11 ~09:45–10:10 EDT | 60 polls, 0 errors, 163 aircraft, **only 3 helicopters** | same; "contact for production use" |
| OpenSky REST `/api/states/all` | — | **Failed**: connection timed out from the box (twice) | Non-profit research/education only; operational use needs a written license: https://opensky-network.org/about/terms-of-use |
| FAA Aircraft Registry (public lookup) | Owner names for helicopter N-numbers | worked → `data/faa_owner_cache.json` | public record |
| LiveATC archives | — | **Not downloaded**: the box gets a Cloudflare JS challenge (not bypassed) | Archives last 7 days (FAQ https://www.liveatc.net/faq/). Terms (https://www.liveatc.net/legal/): personal, non-commercial; no redistribution; "Audio streams may not be used in any third-party products." |

## Outputs
- `figures/map_tracks.png`, `figures/map_tracks_lga_zoom.png`: helicopter tracks, approximate corridors, LGA 22/31 approach lines, heliports.
- `figures/alt_vs_ceilings.png`: corridor altitudes vs 1,300 / 1,500 / 1,100 ft.
- `figures/approach_proximity.png`: lateral distance vs vertical offset from a 3° glidepath.
- `figures/update_interval.png`: trace point spacing.
- `data/helicopters_2026-10-10.csv`, `data/approach_proximity.csv`, `data/quality.json`.

## Key caveats (read before quoting numbers)
- **Corridors are APPROXIMATE hand-drawn centerlines** (landmark points), not the legal SFRA polygons. The Hudson line sits west of where traffic actually flies, so corridor membership (≤0.35 nm Hudson, ≤0.25 nm East River) is rough. Next step: digitize the §93.350 boundaries.
- **Approach paths:** the runway ends and true bearings come from AirNav KLGA. 22 is modeled as a straight-in final for 10 nm. **31 (RNAV X) is actually a curved visual final**, but it's modeled here as a straight 3 nm line, which understates its footprint. The glidepath is a generic 3° from TDZE ≈ 12 ft.
- **Altitude:** `alt_baro` is *pressure altitude* (29.92 setting), **not MSL**, so it reads low on high-pressure days (East River median −25 ft). `alt_geom` is GNSS height above the ellipsoid; I subtracted about 105 ft (NYC geoid ≈ −32 m, approximate) to get roughly MSL. Neither is QNH-corrected. A proper conversion needs the METAR altimeter setting.
- **Medevac identification:** ADS-B has no MEDEVAC flag. Callsigns are just tail numbers. Owner-name keywords found **zero medevac-looking operators** on 2026-10-10 in this box. Police: NYPD N918PD/N919PD/N920PD, NY State Police N761NY ("GRYDR1"), Westchester County Public Safety N592PD (labeled other by the regex; it's actually public safety). Medevac ships may be outside the box, use privacy/anonymized addresses, or be registered to leasing LLCs. **Unverified either way.**

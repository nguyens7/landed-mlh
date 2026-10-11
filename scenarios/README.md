# Scenarios S1-S6 (issue #5)

Scripted, repeatable demo scenarios for the Landed helo desk. SIMULATION ONLY: fictional registrations, frequency
shown as "SIM DESK", nothing is transmitted.

| id | file | what it shows |
|---|---|---|
| S1 | `s1.yaml` | JRB to 6N5 on the East River at 500 ft: four autonomous transmissions, no handoff |
| S2 | `s2.yaml` | N312LM direct College Point at 600 ft crosses the Rwy 22 final: standby plus engine handoff (same track as `replay/sim_medevac.json`) |
| S3A | `s3.yaml` | Hudson southbound weather request to descend to 600: handoff |
| S3B | `s3b.yaml` | Silent drift from the west to the east Hudson shoreline with opposing traffic |
| S4 | `s4.yaml` | Confusable callsigns 2646X / 2464X, garbled low-SNR readback: SAY_AGAIN then handoff |
| S5 | `s5.yaml` | MAYDAY plus squawk 7700: one "controller taking over", then locked silent |
| S6 | `s6.yaml` | Fourth helicopter checks in: newest is handed off (cap of three) |

## Run

```sh
cd scenarios
uv sync
uv run python build.py                  # tracks.json, lines.json, index.json, manifest.json (no network)
uv run python build.py --audio          # pilot audio: Gemini TTS + radio filter (Charon/Kore/Fenrir), cached
uv run python build.py --prewarm        # start the server, play S1-S6 once: caches picker answers + agent TTS audio
uv run python run.py --all --spawn-server --repeat 3   # the real thing: server in the loop, 3 runs each
uv run python run.py --all --dry-run --repeat 3        # speech + engine only; server checks are "pending server"
uv run python scoreboard.py             # SCOREBOARD.md + app/public/data/scenarios/scoreboard.json
uv run pytest                           # schema, route-vs-volume, scoring, adapter tests
```

`--spawn-server` runs `server/scripts/with_gemini_key.sh uv run --project server uvicorn landed_server.app:app` on
port 8787 (key from Secret Manager, environment only). To use your own server pass `--server URL`.

## Determinism ("3 out of 3")

* Tracks are generated from the YAML with `replay/landed_timing.route_positions`; nothing is hand-edited.
* ASR + parse: `pins/asr_pins.json` (committed) pins Gemini ASR text, ASR confidence and the parsed transmission per
  line, keyed by a hash of text, voice, SNR and rotor. `--mode pinned` (default) needs no network;
  `--mode refresh` re-transcribes and re-pins; `--mode live --fresh-asr` bypasses the cache (stability probe).
* Server: the Gemini template picker already runs at temperature 0 and caches every answer on disk keyed by
  (model, prompt). `run.py` points `LANDED_CACHE_DIR` at `scenarios/server_cache/`; `server_cache/llm/` is committed,
  `server_cache/tts/` is not. `run.py --curate` rebuilds `llm/`: it replays a scenario and, for every line where the
  picker fell back or picked a template that does not match the expectation, drops that cache entry and asks again
  (up to 6 attempts), recording the attempts in the result file. So the cache is a curated replay, and the number of
  attempts is the picker's first-try miss rate.

## Expectations (YAML)

Per line: `expect.parse` (callsign snap/ambiguity, intent, slots with +-50 ft on `altitude_ft`, emergency) and
`expect.response` (`mode` speak|card|handoff|silent|locked_silent, `template_id`, `tier` auto|approval|handoff,
`triggers`, `spoken_contains`, `card_contains`). Per event (`events:`): `engine_alert` (volume prefix, severity, min
confidence, lead time), `shoreline` (S3B), `squawk`, `position_match`, `desk_count`, `no_alerts`. `known_gap` marks a
response the server does not implement yet; a mismatch is reported as `gap`, not a failure.
Statuses: `pass`, `partial` (trigger set overlaps but differs), `fail`, `pending` (server unreachable), `gap`.

Trigger names are the server's (`path_protected_volume`, `altitude_class_b`, `out_of_whitelist`, `emergency`,
`asr_low_twice`, `callsign_ambiguity`, `weather`, `desk_over_capacity`, `low_confidence`).

## Engine and geometry

`scn_engine.py` is a Python port of `app/src/engine/conflictEngine.ts` (one alert per aircraft, `also_volumes`,
refined time-to-entry). `tests/test_scenarios.py` pins the S2 numbers (handoff 392 s, 83 s lead, confidence 1.0).
`scn_checks.py` holds the checks the engine does not produce yet: the Hudson shoreline rule (centre line calibrated
from the Saturday replay; tolerance 0.15 nm, 15 s), ADS-B position match, squawk 7700, desk count.
Tracks for helicopters that start at a heliport are generated `airborne: true` (already at cruise altitude): the engine
fits a climb rate over 25 s, so a climb-out near JRB/6N5 raises a Class B caution or a Rwy 31 advisory. S2 keeps the
real climb-out because it is the replay's own track.

## Adapter (`adapter.py`)

The only file that knows the server wire format (`POST /reset /desk /adsb /transmission /alerts /decision`,
`GET /tts/{id} /health`). It maps the speech parser's place names to the agent's position ids and normalises the
proposal list to `{mode, template_id, tier, triggers, spoken_text, card_text, ...}`.

## Outputs

* `results/<id>-<timestamp>.json|.log`: all runs, the expected-vs-actual log, per-check pass counts, latency.
* `SCOREBOARD.md` and `app/public/data/scenarios/scoreboard.json` (no UI built).

### scoreboard.json

```json
{
  "generated_at": "ISO time", "simulation": true,
  "totals": {"scenarios": 7, "three_of_three": 7, "judged_pass": 0, "judged_fail": 0, "gaps": 0, "pending": 0},
  "scenarios": [{
    "id": "S1", "title": "", "timestamp": "", "file": "S1-....json", "mode": "pinned",
    "server_in_loop": true, "repeat": 3, "three_of_three": true, "all_judged_passed_every_run": true,
    "tally": {"pass": 0, "fail": 0, "partial": 0, "pending": 0, "gap": 0, "total": 0},
    "counts": {"autonomous": 4, "approval_cards": 0, "handed_off": 0, "silent": 0},
    "latency_ms": {"server_median": 0, "server_max": 0, "speech_median": 0, "n_auto": 0},
    "curation": {"attempts": 1, "misses_before": []},
    "checks": [{"id": "S1.L1.response.template_id", "expected": "ACK_CHECKIN", "actual": "ACK_CHECKIN",
                "status": "pass", "passes": 3, "runs": 3, "pending": 0, "gap": 0, "stable": true}]
  }]
}
```

`app/public/data/scenarios/<id>/tracks.json` uses the `sim_medevac.json` schema (plus `squawk`, `spoken`, `desk`);
`lines.json` has the timed pilot lines with `audio` paths (copied next to it, gitignored) and the expected outcomes.

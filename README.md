# Landed

An AI voice agent and safety net for medevac helicopters in NYC airspace. Simulation and replay only; never transmits on aviation frequencies. See SPEC.md.

> **Safety disclaimer.** Landed is a simulation and replay prototype. It is not for operational use, it never transmits on aviation frequencies, and it uses no LiveATC audio.

## Run the demo

### Prerequisites
- Node 24, Python 3.13, [`uv`](https://docs.astral.sh/uv/), Google Chrome.

### 1. Map and alert demo (no keys needed)
```bash
npm --prefix app ci
npm --prefix app run dev
```
Open http://localhost:5173, press **Play**, then **Jump to conflict**. A simulated medevac (N312LM, not a real flight) at 600 ft crosses the LGA Rwy 22 final 1.1 nm out; the alert card shows a reason, a confidence score and a countdown (about 84 s before entry). Choose **Acknowledge** or **Take over**.

All replay and geo data is bundled in `app/public/data/`. The base map tiles need internet.

### 2. Voice agent (Gemini key required)
Set `GEMINI_API_KEY` in your shell, then in a second terminal:
```bash
LANDED_CACHE_DIR="$PWD/scenarios/server_cache" uv run --project server uvicorn landed_server.app:app --port 8787
```
Keep `npm --prefix app run dev` running in the first terminal. `LANDED_CACHE_DIR` points the agent at the cached, validated replies the scenarios use, so the in-app scenario picker (the SIM control at the right of the bottom bar) plays the same way every time. Optional: also export `OPENAI_API_KEY` to show the OpenAI Decisions router line (shadow mode) on cards; with only a Gemini key, a Gemini router is used instead.

### 3. Scenarios S1 to S6
Gemini key required (`GEMINI_API_KEY` in your shell). From the repo root:
```bash
cd scenarios && uv sync
uv run python build.py --audio        # synthesize pilot audio (Gemini TTS); cached, not committed
uv run python build.py --prewarm      # pre-generate agent replies so responses are instant
uv run python run.py --all --spawn-server --repeat 3
uv run python scoreboard.py           # writes scenarios/SCOREBOARD.md
```
No key? `uv run python run.py --all --dry-run --repeat 3` scores the speech and engine side only and marks server checks as pending.

Result: S1 to S6 pass 3 out of 3 with the server: 7/7, 236 checks, 0 failures, 0 gaps, using cached, validated agent choices.

Every radio call is also routed by a typed decision model (OpenAI Decisions) that returns a label with a probability in about a third of a second. It runs in shadow mode while we calibrate thresholds; hard safety rules stay in code.

### Tests
Checked on Oct 11, 2026 from a fresh worktree on Node 20: app 58, agent 73, server 12, speech 81 tests passing. The README and CI target Node 24.
```bash
npm --prefix app test
(cd agent && uv run pytest -q)
(cd server && uv run pytest -q)
(cd speech && uv run pytest -q)
```

## Repository layout
| Folder | What it is |
|---|---|
| `app/` | Vite + React + MapLibre controller desk: replay, conflict engine (90 s projection), alert and approval cards |
| `replay/` | Builds the replay file from the Sat Oct 10, 2026 adsb.lol traces plus the simulated medevac |
| `geo/` | Builds corridors (OSM shoreline within 14 CFR 93.350), LGA approach volumes (FAA plates and CIFP) and the KLGA altimeter series |
| `speech/` | Gemini transcription, grammar plus Gemini parser, callsign snapping, evaluation (`speech/RESULTS.md`) |
| `agent/` | Bounded voice agent: fixed phrase templates, Gemini function calling, handoff rules, emergency lock |
| `server/` | FastAPI server that holds keys server side and connects the parser, agent and engine alerts |
| `scenarios/` | Scripted demo scenarios S1 to S6: pilot audio, run, and scoreboard (`scenarios/SCOREBOARD.md`) |
| `docs/` | Figures, architecture diagram, QA notes |
| `eda/` | Starter exploratory analysis of the ADS-B data |

## Data credits and licenses
- **ADS-B:** data © adsb.lol contributors, from https://www.adsb.lol/, licensed under the Open Database License (ODbL) 1.0: https://opendatacommons.org/licenses/odbl/1-0/ (license stated in the adsb.lol API docs, https://api.adsb.lol/docs). The derived replay file `app/public/data/replay/saturday.json` is a derived database and is likewise made available under ODbL 1.0 (share-alike, ODbL section 4.4).
- **Shorelines:** © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
- **ATCO2:** 1-hour test set (www.atco2.org), used for evaluation only. License pending (#29). No ATCO2 audio or transcripts are redistributed here. Required acknowledgement: Kocour, M., Veselý, K., Blatt, A., Gomez, J.Z., Szöke, I., Černocký, J., Klakow, D., Motlicek, P. (2021) Boosting of Contextual Information in ASR for Air-Traffic Call-Sign Recognition. Proc. Interspeech 2021, 3301-3305, doi:10.21437/Interspeech.2021-1619.
- **Regulations and procedures:** 14 CFR 93 Subpart W; FAA JO 7110.65BB; FAA d-TPP and CIFP. Geometry is approximate and for simulation only.
- **No LiveATC audio** is used anywhere in Landed.

## Prior art and credits

The current tree contains no code from these projects.

- MayDay, UC Berkeley AI Hackathon 2025: https://devpost.com/software/mayday-l74dub
- Squawk, Devpost 2026: https://devpost.com/software/atc
- ACRP miscommunication detection (2022 ACRP Design Competition): https://github.com/andrewda/acrp-miscommunication-detection
- SESAR HAAWAII readback error research: https://www.sesarju.eu/projects/haawaii

Borrowed ideas only, no code copied: an approval gate before any action (MayDay), callsign snapping and a bounded tool loop (Squawk), parser and detector design (ACRP).


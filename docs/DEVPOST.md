# Devpost submission: Landed

MLH AI Engineer NYC 2026, Oct 11. Copy describes what is merged; anything not yet merged is labeled **In progress** or **Planned**. Update the labels as PRs land.

## Checklist
- [ ] Project created, all teammates added
- [ ] Prize categories: **Best Overall** (automatic). **"Best Use of Gemini API": opt in once the integration branch (Gemini speech and voice agent) is on main** (#24 schedule: 3:00 PM)
- [ ] Description, How we built it, Challenges, What's next (drafts below)
- [ ] Built with: Gemini API, Python, FastAPI, Vite/React, MapLibre GL, adsb.lol
- [ ] Attribution on Devpost, in README.md (lands with PR #13) and in the app footer: **"ADS-B data © adsb.lol contributors (https://www.adsb.lol/), ODbL 1.0."** The current footer reads "ADS-B data: adsb.lol (ODbL)"; ask the app owner (#1) to use the full line with the link
- [ ] Dataset credits, only for datasets actually used in the submission
- [ ] Safety disclaimer and no-LiveATC statement (in Attribution below)
- [ ] Demo video: link pending (not yet recorded; storyboard in pitch/video-script.md, PR #11)
- [ ] Screenshots
- [ ] Repo link only after #7 is fully done (history purge)
- [ ] Every claim checked against SPEC.md; anything marked [UNVERIFIED] removed or labeled

## Inspiration
On January 29, 2025, an Army Black Hawk (PAT25) and PSA Airlines flight 5342 (American Eagle) collided near Reagan National Airport. 67 people died. The NTSB found that one tower controller was working local and helicopter control combined, and cited the tower team's degraded performance under high workload, which resulted in "inadequate traffic advisories, and the lack of safety alerts to both flight crews" (NTSB AIR-26-02, https://www.ntsb.gov/investigations/Pages/DCA25MA108.aspx).

A commenter on r/ATC suggested a low-risk first trial for AI: "Repetitive task with low risk" (https://www.reddit.com/r/ATC/comments/1vmyqe1/comment/p3gkv7x/). We built toward that trial.

## What it does
**Built:**
- Replays real NYC helicopter traffic from ADS-B on a map.
- Projects each aircraft's path 90 seconds ahead. The engine checks LGA approach/departure volumes and the Hudson Class B floor; corridor altitude and shoreline rules are planned (#15).
- Measured on the Saturday replay: 0 false approach or departure handoffs across 17 real helicopters in the demo window (Sat Oct 10, 11:00 to 11:15 ET); six helicopters above the Hudson Class B floor were flagged for the controller.
- When a path will enter a protected volume, shows an alert card with a plain English reason, a confidence score, a countdown, and Acknowledge or Take over.
- Demo: a simulated medevac (N312LM, not a real flight) flies at 600 ft up the East River toward the College Point area and crosses the LGA Rwy 22 final 1.1 nm out. Landed alerts about 84 seconds before entry. A DCA-like situation: a helicopter crossing an airliner's short final.

**Built (#4):** on a simulated desk, a voice agent handles routine medevac check-ins from a fixed phrase list, with controller approval cards for anything non-routine, slot validation, an emergency lock, and an append-only audit log. When the engine hands off, the agent says "standby, controller will be with you" and the controller gets a card with the reason and a live countdown.

**In progress (#10):** citing the pilot's Gemini-parsed request on that card.

**Decision router (shadow mode):** Every radio call is also routed by a typed decision model (OpenAI Decisions) that returns a label with a probability in about a third of a second. It runs in shadow mode while we calibrate thresholds; hard safety rules stay in code.

**Scenarios:** S1 to S6 pass 3 out of 3 with the server: 7/7, 236 checks, 0 failures, 0 gaps, using cached, validated agent choices.

**Planned:** using the stated destination and altitude to extend the 90 s projection.

## How we built it
- **Data:** a full day of real ADS-B traces (Sat Oct 10, 2026) from the adsb.lol open archive: 39 helicopters and about 78,000 points. The demo replays 17 of them in the 11:00 to 11:15 ET window.
- **Geometry:** river corridors follow the real OSM shoreline (ODbL) within the 14 CFR 93.350 limits; LGA approach volumes are derived from FAA plates and split into glidepath segments; the Rwy 31 path is still approximate (#2). Simulation only. Altitudes corrected to MSL with the KLGA altimeter setting.
- **Conflict engine:** 90 second path projection against protected volumes, with time to entry, entry altitude, and a confidence score.
- **UI:** Vite/React map with alert cards.
- **Gemini, built:** `gemini-3.8-flash` audio transcription (33.2% word error on 100 real ATCO2 clips vs 34.6% for OpenAI gpt-4o-transcribe), `gemini-3.5-flash-lite` structured parser (100% valid JSON, median 0.89 s), and `gemini-3.8-flash-lite-tts` pilot voices.
- **Gemini, built (#4):** function calling that can only pick a reply template (`gemini-3.5-flash-lite`), and Gemini TTS that speaks exactly the approved words (0.6 to 1.3 s round trip warm).

## Challenges we ran into
- ADS-B altitude is pressure altitude, not height above sea level, so the checks needed the local altimeter setting.
- Public ADS-B has no medevac flag. Callsigns are just tail numbers, so the demo medevac is simulated.
- We do not use LiveATC audio. Its terms say audio streams may not be used in third-party products (https://www.liveatc.net/legal/). Speech is tested on synthetic clips and the ATCO2 set.
- Designing a voice agent that cannot improvise on air: a fixed phrase list with Gemini choosing, never composing, and a test that TTS input equals the rendered template.

## Accomplishments that we're proud of
- A working loop from real NYC ADS-B traffic to a handoff alert: a 90 second path projection, a countdown, a plain English reason, and an acknowledge or take-over step.
- Every alert carries a confidence score and a reason a controller can read at a glance.

## What we learned
Priority is not autonomy. FAA JO 7110.65BB paragraph 2-1-4b(1) tells controllers to give priority handling to civil air ambulance flights when the pilot says "MEDEVAC" on the radio (https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap2_section_1.html), but trading that priority against airliners is a human call. The useful AI is the one that knows when to stop talking.

## What's next for Landed
- Cut cold-start voice latency (3.4 to 4.6 s cold, 0.6 to 1.3 s warm).
- Verify and replace the approximate geometry with exact legal boundaries.
- Pull weekday data to study real medevac traffic, and measure false alarm rates across many replay days.
- Trial at a quiet non-towered field before anywhere busy.

## Attribution
- Landed is a simulation and replay prototype. It is not for operational use and never transmits on aviation frequencies.
- No LiveATC audio is used in Landed.
- ADS-B data © adsb.lol contributors, from https://www.adsb.lol/, licensed under the Open Database License (ODbL) 1.0: https://opendatacommons.org/licenses/odbl/1-0/ (license stated in the adsb.lol API docs, https://api.adsb.lol/docs). The derived replay file `app/public/data/replay/saturday.json` is a derived database and is likewise made available under ODbL 1.0 (share-alike, ODbL section 4.4).
- River shorelines from OpenStreetMap, © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
- Prior art: MayDay (UC Berkeley AI Hackathon 2025), an AI safety net for ATC that used LiveATC audio; Squawk (Devpost 2026); ACRP miscommunication detection; SESAR HAAWAII. Ideas only, no code.
- Facts: NTSB DCA25MA108 (final report AIR-26-02, adopted Jan 27, 2026), 14 CFR 93 Subpart W, FAA JO 7110.65BB paragraph 2-1-4b(1); FAA New York VFR Helicopter Route Chart (Sep 3, 2026 edition) for the river CTAFs 123.05 (Hudson) and 123.075 (East River).
- ATCO2 1-hour test set (www.atco2.org; Hugging Face Jzuluaga/atco2_corpus_1h), used for evaluation only. License pending (#29); confirm before submission. No ATCO2 audio or transcripts are redistributed in this repo or the submission. Required acknowledgement: Kocour, M., Veselý, K., Blatt, A., Gomez, J.Z., Szöke, I., Černocký, J., Klakow, D., Motlicek, P. (2021) Boosting of Contextual Information in ASR for Air-Traffic Call-Sign Recognition. Proc. Interspeech 2021, 3301-3305, doi:10.21437/Interspeech.2021-1619, and www.atco2.org. Corpus paper: Zuluaga-Gomez et al., ATCO2 corpus, arXiv:2211.04054.

# Judge Q&A prep

Closes #20. Short, honest answers. Numbers come from `speech/RESULTS.md` and `app/src/engine/conflictEngine.ts` on the integration branch `claude/helicopter-conflict-detection-fc6cce`, or from the cited URL. If a judge asks about something marked planned, say so plainly.

## Safety and scope

**1. Does Landed talk on real frequencies?**
No. It is simulation and replay only and never transmits. The demo uses recorded ADS-B and a simulated medevac.

**2. Who is liable if it gets something wrong?**
The controller stays in charge. On the simulated desk, the voice agent (#4, merged to the integration branch) only sends routine template replies, and anything non-routine goes to an approval card the controller must confirm (A/E/R keys, 1 s arm delay, 10 s expiry, never auto-sent). Priority, sequencing and clearances stay human.

**3. Why not just rely on TCAS or the existing conflict alert?**
At DCA the controller received a conflict alert beginning at 2047:33, 26 seconds before the collision (NTSB AIR-26-02, PDF p. 38). Landed looks 90 seconds ahead against protected volumes. On the NYC river routes, pilots self-announce on a shared frequency with no ATC contact required (14 CFR 93.351, https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-93/subpart-W). Landed adds earlier warning; it does not replace TCAS or the existing conflict alert.

**4. How would this ever get certified?**
Honestly, a long way off. The path is advisory-only shadow mode, measured false alarm rates over many days, then a trial at a quiet non-towered field. Today it is a research prototype.

**5. Why medevac first?**
It is repetitive and low risk when the helicopter stays clear of arrival and departure paths. A commenter on r/ATC called it "Repetitive task with low risk, seems like a good trial" (https://www.reddit.com/r/ATC/comments/1vmyqe1/comment/p3gkv7x/).

## The DCA accident

**6. Are you saying Landed would have prevented DCA?**
No. Landed is designed to raise an earlier alert, but nobody has tested what would have happened at DCA. The NTSB probable cause cites "inadequate traffic advisories, and the lack of safety alerts to both flight crews" (https://www.ntsb.gov/investigations/Pages/DCA25MA108.aspx).

**7. Was one controller really doing both jobs?**
Yes. The DCA tower controller "was working combined local control and helicopter control positions" (NTSB AIR-26-02, PDF p. 22); the LC and HC positions were combined, as the tower's SOP allowed (PDF p. 92). Final report adopted Jan 27, 2026.

**8. Is your demo the same geometry as DCA?**
No. It is a DCA-like situation: a helicopter crossing an airliner's short final. At DCA the collision was at about 278 ft msl (NTSB AIR-26-02, PDF p. 23). Our sim crosses at 600 ft, 1.1 nm out, above a 3 degree glidepath and inside the modeled 0 to 730 ft protected band.

## Conflict engine

**9. How does the conflict check work?**
Every aircraft's path is projected 90 seconds ahead and intersected with LGA approach, departure and Class B floor volumes. Entering the volume and altitude band raises a handoff alert with time to entry and entry altitude (`app/src/engine/conflictEngine.ts`).

**10. Where does the confidence number come from?**
Confidence is data freshness times a weighted sum: 0.65 for penetration depth and 0.35 for track stability, each clamped to [0, 1]. Stale tracks fall to 0 at 10 s (`combineConfidence` in `app/src/engine/conflictEngine.ts`).

**11. How much warning does the demo get?**
About 84 seconds before N312LM enters the Rwy 22 final volume.

**12. How accurate is the geometry?**
Approximate, for simulation. River corridors were rebuilt from OpenStreetMap shoreline water polygons; 99.6% of real low Hudson traffic and 97.0% of East River traffic falls inside them. The Rwy 31 path is being moved onto FAA CIFP fix positions (PR #33). Exact legal corridor boundaries from 14 CFR 93.350 are not yet digitized.

**13. How many false alarms on real traffic?**
0 false approach or departure handoffs across 17 real helicopters in the demo window (Sat Oct 10, 11:00 to 11:15 ET); six helicopters above the Hudson Class B floor were flagged for the controller. Five more climbing helicopters got Class B floor cautions. We call the six "flagged for the controller", not violations: we cannot see their clearances. Source: the engine's real-traffic snapshot test.

**14. Altitudes from ADS-B are pressure altitude. Did you correct them?**
Yes. `alt_msl = alt_baro + (altimeter - 29.92) x 1000`, using the KLGA altimeter setting for Oct 10, 2026.

**15. Corridors are drawn. Are they enforced?**
Not yet. Corridor altitude and direction rules are planned (#15).

## Speech and AI

**16. How well does it transcribe radio?**
On synthetic radio clips with Gemini TTS voices, WER is 2.4% clean, 5.5% at 5 dB SNR, 20.3% at 0 dB. On real European ATC audio (ATCO2, 100 clips) WER is 33.2%. The synthetic numbers are an optimistic, in-distribution bound (`speech/RESULTS.md`).

**17. How fast is parsing?**
A grammar parser runs first (0.4 ms median over 400 clips) and calls Gemini only when unsure (17.2% of clips). A forced Gemini call has a 0.89 s median, 1.13 s p95. Gemini returned valid JSON on 100% of the 50-utterance bank.

**18. Does the confidence score mean anything?**
Yes, measured. ASR confidence predicts end-to-end errors with AUROC 0.939. Error rate is 87.5% below 0.5 confidence and 1.6% at 0.95 to 0.98. Handing off below 0.8 would catch 92.9% of critical errors at a 32% handoff rate.

**19. What about confusable callsigns?**
On truncated callsigns (true near-ties) the parser flags ambiguity 87.5% of the time, and the true aircraft is in the candidate list 91.7% of the time. On full callsigns it wrongly flags only 1.1%.

**20. What if the speech model mishears a MAYDAY?**
At -5 dB SNR, emergency recall falls to 40% (2 of 5). Built (#16): squawk 7700/7600/7500 is treated as an emergency regardless of the radio parse.

## Gemini

**21. Where is Gemini used?**
Built (merged to the integration branch): Gemini `gemini-3.8-flash` for transcription; `gemini-3.5-flash-lite` with a response schema as the parser fallback; `gemini-3.5-flash-lite` function calling (forced `choose_template` / `handoff`) in the voice agent; and Gemini TTS (`gemini-3.8-flash-lite-tts`) for the agent voice and the synthetic pilot voices. Alert reasons come from code templates, not Gemini.

**22. Is there anything besides Gemini making decisions?**
Every radio call is also routed by a typed decision model (OpenAI Decisions) that returns a label with a probability in about a third of a second. It runs in shadow mode while we calibrate thresholds; hard safety rules stay in code.

**23. Why Gemini and not another model?**
On real ATCO2 audio, Gemini had 33.2% WER against 34.6% for OpenAI `gpt-4o-transcribe`, and better identifier matching (42.4% vs 36.4%). We chose models by measurement.

**24. How do you stop the voice agent making things up on air?**
The model never composes speech. Gemini function calling picks a template and slots, code validates every slot, and a test asserts the TTS input equals the rendered template. Agent round trip is 0.6 to 1.3 s with TTS warm and 3.4 to 4.6 s cold; a prewarm fix is in progress (#4, #5).

## Data and legal


**25. Where does the data come from?**
adsb.lol, ODbL 1.0 ("The license for the API as well as all data ADSB.lol makes public is ODbL", https://api.adsb.lol/docs). Full Saturday Oct 10, 2026: 39 helicopters and about 78,000 points; the demo replays 17 of them. The derived replay file is also released under ODbL (share-alike).

**26. Did you use LiveATC audio?**
No. Their terms restrict audio streams from use in third-party products (https://www.liveatc.net/legal/). Speech tests use synthetic clips and the ATCO2 1-hour test set, used for evaluation only; its license is pending confirmation (#29), and no ATCO2 audio or transcripts are redistributed.

**27. Is any of this copied from MayDay?**
No code. We borrowed the idea of an approval gate before any action. The reference clone is no longer tracked in the repo.

**28. Does a MEDEVAC really get priority?**
Yes, when the pilot says it on the radio. FAA JO 7110.65BB para 2-1-4b(1): "Provide priority handling to civil air ambulance flights when the pilot, in radio transmissions, verbally identifies the flight by stating 'MEDEVAC'...". Flight plan entries alone are informational only. https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap2_section_1.html

## Hard questions we cannot fully answer yet

- Real NYC helicopter radio audio performance: not measured (ATCO2 is European, and synthetic audio is in-distribution).
- False alarm rate across many days of real traffic: not measured yet.
- Weekday medevac volumes: our sample is one Saturday; public ADS-B has no medevac flag.
- Whether controllers would trust it: needs user research with real controllers.

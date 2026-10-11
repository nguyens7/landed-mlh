# Backup demo video: script and storyboard

Target length: 2:30. Record after the app runs end to end (needs #1, #4, #5). Screen capture at 1080p, with system audio for the TTS voices.

| Time | Screen | Voiceover |
|---|---|---|
| 0:00 to 0:15 | Title card "Landed", then a black slide with "January 29, 2025, Washington, DC" | "In January 2025, one controller at Reagan National was working helicopters and runway traffic on a combined position. A conflict alert had been active for about 26 seconds before the collision." |
| 0:15 to 0:30 | NYC map, REPLAY label: 17 real helicopters, Sat Oct 10 2026, 11:00 to 11:15 ET | "Real traffic, replayed from public ADS-B. On a simulated desk, Landed handles routine medevac check-ins and hands anything risky to the controller. It never transmits." |
| 0:30 to 1:00 | S1: MEDEVAC 2646X lifts from Downtown Skyport, transcript lines appear with confidence, Landed replies | "A clean flight up the East River. Landed handles the routine check-in and acknowledgement. Priority, sequencing and clearances stay with the controller." |
| 1:00 to 1:40 | S2 (SIM): N312LM heads for the College Point area at 600 ft, crossing the Rwy 22 final 1.1 nm out. Red projection, countdown from the measured lead time (~84 s), alert card slides in | "This one, at 600 feet, will cross the runway 22 final about a mile out. A DCA-like situation: a helicopter crossing an airliner's short final. Landed alerts about 84 seconds before entry, with a plain English reason, and hands it to the controller." |
| 1:40 to 2:05 | S5: MAYDAY call, 7700 badge, Landed says "controller taking over", transmit lock icon | "In an emergency, Landed speaks once on the sim channel and goes silent. The human owns the frequency." |
| 2:05 to 2:20 | Gemini slide over a JSON panel and the approval card | "Gemini parses each call, picks replies from a fixed phrase list, and speaks them word for word." (Only record this beat once the Gemini work is merged; otherwise say "in progress".) |
| 2:20 to 2:30 | End card: "Takes the routine. Flags trouble early. The human makes every hard call." plus "Simulation only. ADS-B data from adsb.lol, ODbL 1.0." | (silence) |

Checklist
- Label every screen SIM or REPLAY.
- Fictional registrations only (2646X, N312LM), labeled SIM.
- No wreck imagery. No claim that Landed would have prevented the DCA accident.
- Export MP4, upload unlisted, link it in docs/DEVPOST.md.
- Do not publish this storyboard as the demo. Record only after #1, #4, #5 land; beats for unmerged features get cut or labeled in progress.

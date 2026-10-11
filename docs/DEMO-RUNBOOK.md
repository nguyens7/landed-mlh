# Demo runbook and fallback plan

Closes #19. For the MLH AI Engineer NYC 2026 demo. Applies to the integration branch `claude/helicopter-conflict-detection-fc6cce` until it merges to main (#24). Landed is simulation and replay only; it never transmits.

Demo numbers (from #9): replay of Sat Oct 10 2026, 11:00 to 11:15 ET, 17 real helicopters. Simulated medevac N312LM at 600 ft toward the College Point area crosses the LGA Rwy 22 final 1.1 nm out. Alert about 84 s before entry. Say "a DCA-like situation: a helicopter crossing an airliner's short final".

## 1. Startup (clean checkout)

```bash
# Clone the repo you have access to (it is private), then:
git checkout claude/helicopter-conflict-detection-fc6cce   # or main after the 3:00 merge
npm --prefix app ci
npm --prefix app test          # vitest: conflict engine, geometry, store
npm --prefix app run dev -- --port 5173
```

Expected: Vite prints `Local: http://localhost:5173/`. Open it in Chrome, full screen (F11). The map loads NYC with corridors, LGA approach volumes and heliports, and the replay controls along the bottom.

Data is bundled in `app/public/data/` (replay and geo), so no API key and no live ADS-B feed is needed for the S2 beat. The base map tiles do need internet (see failure table).

## 2. Click path (S2 beat, target 60 to 75 s)

| Step | Action | What the audience sees | Say |
|---|---|---|---|
| 1 | Press Play, speed 4x | 17 real helicopters moving on the Hudson and East River, REPLAY label | "Real traffic from last Saturday, public ADS-B." |
| 2 | Wait for N312LM to appear (SIM) | Simulated medevac lifts off and heads up the East River at 600 ft | "A simulated medevac, heading for College Point." |
| 3 | Click **Jump to conflict** if it is running late | Red 90 s projection reaches the Rwy 22 final | "Landed projects every aircraft 90 seconds ahead." |
| 4 | Pause on the alert card | Handoff alert: reason, confidence, countdown (~84 s) | Read the reason aloud. "About 84 seconds of warning." |
| 5 | Click **Take over** (or Acknowledge) | Card shows the decision and the controller's latency | "The human makes the call. Landed logs it." |

Speeds available: 1x, 4x, 16x. The timeline slider can seek directly.

## 2b. Voice agent beat (Gemini key required)

In a second terminal, with `GEMINI_API_KEY` set in the shell (never on screen, never in a file):

```bash
uv run --project server uvicorn landed_server.app:app --port 8787
```

Expected: `Uvicorn running on http://127.0.0.1:8787` (banner seen on the integration branch, Oct 11 12:27 ET; recheck in the dry run, #19 step 7). The voice agent (#4) is merged to the integration branch: Gemini function calling picks a fixed template, Gemini TTS speaks it on the sim channel, and anything non-routine raises an approval card (A/E/R keys, 1 s arm delay, 10 s expiry, never auto-sent). In S2 the pilot's request is parsed by Gemini. Citing the parsed call on the handoff card is in progress (#10).

Every radio call is also routed by a typed decision model (OpenAI Decisions) that returns a label with a probability in about a third of a second. It runs in shadow mode while we calibrate thresholds; hard safety rules stay in code.

Latency: 0.6 to 1.3 s with TTS warm, 3.4 to 4.6 s cold. **Warm it up**: trigger one scripted response before going on stage. A prewarm fix is in progress with #5.

Scenarios S1 to S6: use the scenario picker (#17, merged): the SIM control at the right of the bottom bar, then **Play scenario**. S1 to S6 pass 3 out of 3 with the server: 7/7, 236 checks, 0 failures, 0 gaps.

## 3. Beat timing (matches pitch/live-script.md, PR #11)

| Time | Beat | Screen |
|---|---|---|
| 0:00 to 0:50 | DC opener, the gap (slides 1 and 2) | Deck |
| 0:50 to 1:10 | Landed (slide 3) | Deck |
| 1:10 to 2:20 | Live demo, S2 click path above | App |
| 2:20 to 2:50 | Trust, Gemini, what's next | Deck |

S1 (clean flight), S4 (callsign confusion) and S5 (MAYDAY, goes silent) run from the scenario picker (SIM control at the right of the bottom bar, then Play scenario).

## 4. Failure table

| Failure | Detect | Action (under 15 s) | Fallback |
|---|---|---|---|
| `npm ci` fails or no network at venue | Error on install | Use the laptop that already has `app/node_modules` | Recorded video |
| Dev server will not start | No `Local:` line | `npm --prefix app run build && npm --prefix app run preview` | Recorded video |
| Base map tiles do not load (offline) | Grey map, tracks still draw | Keep going: tracks, volumes and the alert still render; say "map tiles are offline" | Screenshots |
| Browser crash or freeze | Unresponsive | Reopen tab at localhost:5173, Jump to conflict | Recorded video |
| Alert does not fire | No card after Jump to conflict | Reload, Play, Jump to conflict once more | Screenshot of the alert card (`app/docs/alert.png`) |
| Projector resolution clips the card | Card off screen | Ctrl/Cmd minus to 80%, or move the card into view | Screenshots |
| Audio (TTS) fails | No sound | Read the line aloud; transcripts show on screen | Video |
| Gemini key or quota error | Server log error, no agent reply | The S2 map beat does not need Gemini; skip the voice beat | Video, and show `speech/RESULTS.md` |
| Voice reply slow (cold TTS, 3.4 to 4.6 s) | Pause after the pilot call | Say "first call warms the voice"; prewarm before the demo next time | Video |

## 5. Fallback ladder

1. Live app (dev server).
2. Local production build (`vite preview`), started in a second terminal before the demo.
3. Recorded backup video (#6; not recorded yet, needs #4 and #5).
4. Screenshots: map with replay, the alert card, the Take over state. Keep them in the deck as hidden slides.

## 6. Checklists

T minus 30 minutes:
- [ ] Laptop on power, notifications off, Do Not Disturb on
- [ ] Dev server running and `vite preview` running on a second port
- [ ] Voice server running on 8787 and warmed with one scripted response
- [ ] Ran the S2 click path once end to end; alert fired
- [ ] Deck open on slide 1; video file downloaded locally (not streaming)
- [ ] Browser zoom checked on the projector

T minus 5 minutes:
- [ ] Replay reset to start, speed 4x selected, paused
- [ ] Tab order: deck, app, video
- [ ] One person drives, one person talks

## 6b. Numbers to quote

0 false approach or departure handoffs across 17 real helicopters in the demo window (Sat Oct 10, 11:00 to 11:15 ET); six helicopters above the Hudson Class B floor were flagged for the controller. (Engine real-traffic snapshot test, Saturday replay. Say "flagged for the controller", never "false alarms" or "violations".)

## 7. Open items

- #19 step 7 (open): dry run on the integration branch and replace the target timings above with measured ones.
- #19 step 8 (open): add the S1, S4, S5 beats to the timing table after the step 7 dry run, using the scenario picker (#17).

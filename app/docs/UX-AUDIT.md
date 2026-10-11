# Demo UX audit

Captured at 1920x1080 against `main` (4900581), headless Chrome, with the voice
server running. Three moments: on load, about 3 seconds after **Jump to
conflict** (replay clock 6:38), and about 20 seconds later (6:55).

## What a judge sees first

- **On load:** a dark map with large red approach volumes and the Hudson
  exclusion outline, no aircraft (the replay is paused at 0:00), an empty alert
  log, and a 340 px column of audit rows from earlier server sessions. Nothing
  says what the product does or what to press.
- **After Jump to conflict:** the red handoff card at the top of the map is
  the strongest element, which is correct. Its countdown is 22 px and its
  headline is the raw engine sentence ("N312LM: Projected path crosses LGA Rwy
  22 final 2.3 nm from threshold at 600 ft, inside the arrival glidepath band
  ..."), 14 px. A judge must read two lines of aviation jargon to get the
  story.
- **20 seconds later:** a second red card ("LANDED SAID (STANDBY)") appears at
  the bottom of the map. Both cards say HANDOFF and MEDEVAC N312LM, so the eye
  ping-pongs between two equal red boxes.

## What competes with the medevac handoff

1. **Red approach volumes.** The LGA volumes use the same red as the handoff
   severity, so "red" means both "airspace" and "emergency".
2. **Duplicate handoff cards.** The engine card (top) and the voice card
   (bottom) tell the same story in two places.
3. **The audit log column.** Twenty-plus dense monospace rows with colored
   event names (`auto_speak`, `suppressed_by_lock`, `reject_take_over`) scroll
   beside the map at 12 px. It is the busiest region on screen.
4. **The alert log.** Five rows of `6:05 N62ZA HANDOFF 0.00` read as five
   emergencies, including one at confidence 0.00.
5. **The bottom bar.** Eleven controls at equal weight: Play, three speed
   buttons, a clock, a full-width scrubber, Jump to conflict, a SIM picker,
   Play scenario, Reset, and Scoreboard.
6. **Red helicopter icons** elsewhere on the Hudson also read as "the
   emergency".

## Prioritized fixes

### P0

- **One hero card.** Merge the engine handoff and the "Landed said" line into
  one card with a plain-English headline ("Medevac heading into LaGuardia
  arrivals"). The story must read in one glance, not two lines of jargon.
- **Big countdown.** Make the seconds-to-entry the largest number on screen.
  Urgency is the hook, and 22 px is lost at projector distance.
- **Plain status word.** Show "Handed to controller", "Caution", or "Normal"
  on the card in the map's colors. Judges do not know what HANDOFF means.
- **Quiet the side column.** Collapse the alert and audit logs to one line
  each, expandable. They are evidence, not the headline, and they currently
  out-weigh the map.
- **Say what to do on load.** An idle card ("Watching NYC helicopter traffic
  around LaGuardia" plus a pointer to Jump to conflict) fills the empty first
  screen.

### P1

- **Bottom bar hierarchy.** Keep Jump to conflict, Play, the SIM picker, and
  Reset prominent; tuck speed and the scrubber into a compact group. Fewer
  equal-weight targets during a live demo.
- **Readable card text.** Minimum 20 px body text on cards at 1920 wide. The
  current 14 px reason text fails at projector distance.
- **Header noise.** Hide "Helo Desk: replay"; keep the logo and the SIMULATION
  banner (required).

### P2 (map, owned by the runway and legend work)

- **Volumes off the alarm red.** Render approach volumes in a neutral or
  desaturated tone at rest and light only the volume the medevac is about to
  enter in red. Red should mean "handoff" only.
- **Entry point marker.** Mark the projected entry point on the Rwy 22 final
  with the countdown, so the card and the map point at the same spot.
- **Confidence 0.00 rows.** Consider hiding handoff rows with 0.00 confidence
  from the log, or label them "low confidence" (engine decision, not a UI
  change).
- **Fresh audit on load.** The audit log shows rows from earlier server
  sessions; a reset on page load would make the demo start clean (server
  decision).

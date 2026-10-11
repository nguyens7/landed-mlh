# Scenario scoreboard

Generated 2026-10-11 17:02 UTC by `scoreboard.py` from `scenarios/results/`. SIMULATION ONLY: fictional registrations, frequency shown as SIM DESK.

Verdict `3/3` = every judged expectation matched in all 3 runs with the voice-agent server in the loop. `gap` = the expectation is known to be unimplemented in the server (reported, not counted as a failure). `pending` = could not be judged (no server).

| scenario | title | verdict | server | pass | fail | partial | gap | pending | autonomous | cards | handed off | server ms (median / max) | ASR+parse ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | Clean autonomous run, JRB to 6N5 | 3/3 | yes | 45 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 1 / 3 | 4276 |
| S2 | Medevac crosses the LGA Rwy 22 final, handoff | 3/3 | yes | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | n/a |
| S3A | Weather, descend below the Hudson minimum | 3/3 | yes | 25 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 1 / 3 | 4320 |
| S3B | Silent drift to the wrong Hudson shoreline | 3/3 | yes | 20 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 / 2 | 3095 |
| S4 | Confusable callsigns, say again then handoff | 3/3 | yes | 53 | 0 | 0 | 0 | 0 | 3 | 0 | 1 | 1 / 2 | 3348 |
| S5 | MAYDAY and 7700, agent goes silent | 3/3 | yes | 27 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | n/a | n/a |
| S6 | Volume cap, the fourth helicopter is handed off | 3/3 | yes | 45 | 0 | 0 | 0 | 0 | 3 | 0 | 1 | 2 / 3 | 5844 |

Latency columns cover auto-tier transmissions only. `server ms` is ParsedTransmission in -> agent audio ready (the issue #4 budget is 3000 ms); `ASR+parse ms` is Gemini ASR + the speech parser, on top of that.

## S1: Clean autonomous run, JRB to 6N5

3/3 | result file `S1-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.no_alert>=advisory | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L1.parse.emergency | false | false | pass | 3/3 |
| L1.parse.intent | checkin | checkin | pass | 3/3 |
| L1.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L1.parse.slots.corridor | East River | East River | pass | 3/3 |
| L1.parse.slots.direction | northbound | northbound | pass | 3/3 |
| L1.parse.slots.origin | Downtown Skyport | Downtown Skyport | pass | 3/3 |
| L1.parse.slots.position | Downtown Skyport | Downtown Skyport | pass | 3/3 |
| L1.response.latency_ms | <=3000 | 3 | pass | 3/3 |
| L1.response.mode | speak | speak | pass | 3/3 |
| L1.response.spoken_contains | ["Landed advisory", "radar contact", "Downtown Skyport"] | MEDEVAC Two Six Four Six X-Ray, Landed advisory, radar conta | pass | 3/3 |
| L1.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L1.response.tier | auto | auto | pass | 3/3 |
| L2.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L2.parse.intent | position_report | position_report | pass | 3/3 |
| L2.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L2.parse.slots.position | Brooklyn Bridge | Brooklyn Bridge | pass | 3/3 |
| L2.response.latency_ms | <=3000 | 1 | pass | 3/3 |
| L2.response.mode | speak | speak | pass | 3/3 |
| L2.response.spoken_contains | ["roger"] | MEDEVAC Two Six Four Six X-Ray, roger | pass | 3/3 |
| L2.response.template_id | REPORT_ACK | REPORT_ACK | pass | 3/3 |
| L2.response.tier | auto | auto | pass | 3/3 |
| L3.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L3.parse.intent | position_report | position_report | pass | 3/3 |
| L3.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L3.parse.slots.destination | East 34th | East 34th | pass | 3/3 |
| L3.parse.slots.position | Williamsburg Bridge | Williamsburg Bridge | pass | 3/3 |
| L3.response.latency_ms | <=3000 | 2 | pass | 3/3 |
| L3.response.mode | speak | speak | pass | 3/3 |
| L3.response.spoken_contains | ["traffic"] | MEDEVAC Two Six Four Six X-Ray, traffic ten o'clock three po | pass | 3/3 |
| L3.response.template_id | TRAFFIC | TRAFFIC | pass | 3/3 |
| L3.response.tier | auto | auto | pass | 3/3 |
| L4.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L4.parse.intent | position_report | position_report | pass | 3/3 |
| L4.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L4.parse.slots.position | East 34th | East 34th | pass | 3/3 |
| L4.response.latency_ms | <=3000 | 3 | pass | 3/3 |
| L4.response.mode | speak | speak | pass | 3/3 |
| L4.response.spoken_contains | ["roger"] | MEDEVAC Two Six Four Six X-Ray, roger | pass | 3/3 |
| L4.response.template_id | REPORT_ACK | REPORT_ACK | pass | 3/3 |
| L4.response.tier | auto | auto | pass | 3/3 |
| summary.auto_transmissions | 4 | 4 | pass | 3/3 |
| summary.cards | 0 | 0 | pass | 3/3 |
| summary.handoffs | 0 | 0 | pass | 3/3 |

## S2: Medevac crosses the LGA Rwy 22 final, handoff

3/3 | result file `S2-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.confidence>= | 0.8 | 1.0 | pass | 3/3 |
| E1.geometry.exists | handoff lga22_final_seg* | lga22_final_seg2 | pass | 3/3 |
| E1.geometry.lead_s | [80.0, 90.0] | 83.109375 | pass | 3/3 |
| E1.geometry.t_first | [380.0, 400.0] | 392.0 | pass | 3/3 |
| E1.response.card_contains | ["Rwy 22"] | N312LM: Projected path crosses LGA Rwy 22 final at 600 ft -  | pass | 3/3 |
| E1.response.mode | handoff | handoff | pass | 3/3 |
| E1.response.tier | handoff | handoff | pass | 3/3 |
| E1.response.triggers | ["path_protected_volume"] | ["path_protected_volume"] | pass | 3/3 |
| ENGINE.geometry.no_unexpected_alert | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N312LM | N312LM | pass | 3/3 |
| L1.parse.emergency | false | false | pass | 3/3 |
| L1.parse.intent | request_route | request_route | pass | 3/3 |
| L1.parse.slots.altitude_ft | 600 | 600 | pass | 3/3 |
| L1.parse.slots.destination | College Point | College Point | pass | 3/3 |
| L1.parse.slots.position | East 34th | East 34th | pass | 3/3 |
| L1.response.mode | handoff | handoff | pass | 3/3 |
| L1.response.spoken_contains | ["standby", "controller will be with you"] | MEDEVAC Three One Two Lima Mike, standby, controller will be | pass | 3/3 |
| L1.response.template_id | STANDBY_HANDOFF | STANDBY_HANDOFF | pass | 3/3 |
| L1.response.tier | handoff | handoff | pass | 3/3 |
| L1.response.triggers | ["out_of_whitelist"] | ["out_of_whitelist"] | pass | 3/3 |
| summary.handoffs | 1 | 1 | pass | 3/3 |

## S3A: Weather, descend below the Hudson minimum

3/3 | result file `S3A-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.no_alert>=advisory | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L1.parse.emergency | false | false | pass | 3/3 |
| L1.parse.slots.altitude_ft | 1000 | 1000 | pass | 3/3 |
| L1.parse.slots.corridor | Hudson | Hudson | pass | 3/3 |
| L1.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L1.response.latency_ms | <=3000 | 3 | pass | 3/3 |
| L1.response.mode | speak | speak | pass | 3/3 |
| L1.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L1.response.tier | auto | auto | pass | 3/3 |
| L2.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L2.parse.emergency | false | false | pass | 3/3 |
| L2.parse.intent | request_altitude | request_altitude | pass | 3/3 |
| L2.parse.slots.altitude_ft | 600 | 600 | pass | 3/3 |
| L2.parse.slots.corridor | Hudson | Hudson | pass | 3/3 |
| L2.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L2.parse.slots.weather_phrase | ceilings coming down | ceilings coming down | pass | 3/3 |
| L2.response.card_contains | ["ceilings", "Hudson"] | Mandatory handoff: out_of_whitelist, below_transit_min, weat | pass | 3/3 |
| L2.response.mode | handoff | handoff | pass | 3/3 |
| L2.response.spoken_contains | ["standby", "controller will be with you"] | MEDEVAC Two Six Four Six X-Ray, standby, controller will be  | pass | 3/3 |
| L2.response.template_id | STANDBY_HANDOFF | STANDBY_HANDOFF | pass | 3/3 |
| L2.response.tier | handoff | handoff | pass | 3/3 |
| L2.response.triggers | ["weather", "below_transit_min", "out_of_whitelist"] | ["out_of_whitelist", "below_transit_min", "weather"] | pass | 3/3 |
| summary.auto_transmissions | 1 | 1 | pass | 3/3 |
| summary.handoffs | 1 | 1 | pass | 3/3 |

## S3B: Silent drift to the wrong Hudson shoreline

3/3 | result file `S3B-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.confidence>= | 0.8 | 1.0 | pass | 3/3 |
| E1.geometry.exists | shoreline alert | N2646X: southbound aircraft on the east shoreline (0.30 nm e | pass | 3/3 |
| E1.geometry.first_seen_t | [40.0, 100.0] | 83.0 | pass | 3/3 |
| E1.geometry.opposing_traffic_nm | [0.5, 3.5] | 1.91 | pass | 3/3 |
| E1.response.latency_ms | <=3000 | 1 | pass | 3/3 |
| E1.response.mode | speak | speak | pass | 3/3 |
| E1.response.spoken_contains | ["traffic"] | MEDEVAC Two Six Four Six X-Ray, traffic twelve o'clock two m | pass | 3/3 |
| E1.response.template_id | TRAFFIC | TRAFFIC | pass | 3/3 |
| E1.response.tier | auto | auto | pass | 3/3 |
| E2.geometry.no_alert>=advisory | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L1.parse.emergency | false | false | pass | 3/3 |
| L1.parse.slots.altitude_ft | 1000 | 1000 | pass | 3/3 |
| L1.parse.slots.corridor | Hudson | Hudson | pass | 3/3 |
| L1.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L1.response.latency_ms | <=3000 | 2 | pass | 3/3 |
| L1.response.mode | speak | speak | pass | 3/3 |
| L1.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L1.response.tier | auto | auto | pass | 3/3 |
| summary.handoffs | 0 | 0 | pass | 3/3 |

## S4: Confusable callsigns, say again then handoff

3/3 | result file `S4-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.best_match | N2646X | N2646X | pass | 3/3 |
| E1.geometry.score>= | 0.85 | 0.979 | pass | 3/3 |
| E1.geometry.unique | true | true | pass | 3/3 |
| E2.geometry.best_match | N2646X | N2646X | pass | 3/3 |
| E2.geometry.score>= | 0.8 | 0.871 | pass | 3/3 |
| E2.geometry.unique | true | true | pass | 3/3 |
| E3.geometry.no_alert>=advisory | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N2464X | N2464X | pass | 3/3 |
| L1.parse.intent | checkin | checkin | pass | 3/3 |
| L1.parse.slots.altitude_ft | 1000 | 1000 | pass | 3/3 |
| L1.parse.slots.corridor | Hudson | Hudson | pass | 3/3 |
| L1.parse.slots.direction | northbound | northbound | pass | 3/3 |
| L1.parse.slots.origin | Downtown Skyport | Downtown Skyport | pass | 3/3 |
| L1.parse.slots.position | Downtown Skyport | Downtown Skyport | pass | 3/3 |
| L1.response.latency_ms | <=3000 | 2 | pass | 3/3 |
| L1.response.mode | speak | speak | pass | 3/3 |
| L1.response.spoken_contains | ["Downtown Skyport"] | MEDEVAC Two Four Six Four X-Ray, Landed advisory, radar cont | pass | 3/3 |
| L1.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L1.response.tier | auto | auto | pass | 3/3 |
| L2.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L2.parse.intent | checkin | checkin | pass | 3/3 |
| L2.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L2.parse.slots.corridor | East River | East River | pass | 3/3 |
| L2.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L2.parse.slots.origin | East 34th | East 34th | pass | 3/3 |
| L2.parse.slots.position | East 34th | East 34th | pass | 3/3 |
| L2.response.latency_ms | <=3000 | 2 | pass | 3/3 |
| L2.response.mode | speak | speak | pass | 3/3 |
| L2.response.spoken_contains | ["East 34th"] | MEDEVAC Two Six Four Six X-Ray, Landed advisory, radar conta | pass | 3/3 |
| L2.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L2.response.tier | auto | auto | pass | 3/3 |
| L3.parse.callsign.ambiguous | true | true | pass | 3/3 |
| L3.parse.callsign.candidates | ["N2646X", "N2464X"] | ["N2464X", "N2646X"] | pass | 3/3 |
| L3.parse.intent | position_report | position_report | pass | 3/3 |
| L3.parse.slots.position | Brooklyn Bridge | Brooklyn Bridge | pass | 3/3 |
| L3.response.latency_ms | <=3000 | 1 | pass | 3/3 |
| L3.response.mode | speak | speak | pass | 3/3 |
| L3.response.spoken_contains | ["say again"] | Aircraft calling Landed desk, say again callsign | pass | 3/3 |
| L3.response.template_id | SAY_AGAIN | SAY_AGAIN | pass | 3/3 |
| L3.response.tier | auto | auto | pass | 3/3 |
| L4.parse.callsign.ambiguous | true | true | pass | 3/3 |
| L4.parse.callsign.candidates | ["N2646X", "N2464X"] | ["N2464X", "N2646X"] | pass | 3/3 |
| L4.parse.intent | position_report | position_report | pass | 3/3 |
| L4.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L4.parse.slots.position | Brooklyn Bridge | Brooklyn Bridge | pass | 3/3 |
| L4.response.card_contains | ["2646X", "ADS-B position match"] | Mandatory handoff: callsign_ambiguity. callsign ambiguous wi | pass | 3/3 |
| L4.response.mode | handoff | handoff | pass | 3/3 |
| L4.response.spoken_contains | ["standby", "controller will be with you"] | MEDEVAC Two Four Six Four X-Ray, standby, controller will be | pass | 3/3 |
| L4.response.template_id | STANDBY_HANDOFF | STANDBY_HANDOFF | pass | 3/3 |
| L4.response.tier | handoff | handoff | pass | 3/3 |
| L4.response.triggers | ["callsign_ambiguity"] | ["callsign_ambiguity"] | pass | 3/3 |
| summary.auto_transmissions | 3 | 3 | pass | 3/3 |
| summary.handoffs | 1 | 1 | pass | 3/3 |

## S5: MAYDAY and 7700, agent goes silent

3/3 | result file `S5-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.exists | 7700 | 7700 | pass | 3/3 |
| E1.geometry.t | [72.0, 80.0] | 75.0 | pass | 3/3 |
| E1.response.mode | locked_silent | locked_silent | pass | 3/3 |
| E2.geometry.no_alert>=advisory | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N312LM | N312LM | pass | 3/3 |
| L1.parse.emergency | true | true | pass | 3/3 |
| L1.parse.intent | emergency | emergency | pass | 3/3 |
| L1.parse.slots.destination | East 34th | East 34th | pass | 3/3 |
| L1.response.card_contains | ["heliport ops"] | Emergency declared or squawk 7700/7600/7500. Agent speaks on | pass | 3/3 |
| L1.response.mode | handoff | handoff | pass | 3/3 |
| L1.response.spoken_contains | ["controller taking over"] | MEDEVAC Three One Two Lima Mike, controller taking over | pass | 3/3 |
| L1.response.template_id | CONTROLLER_TAKING_OVER | CONTROLLER_TAKING_OVER | pass | 3/3 |
| L1.response.tier | handoff | handoff | pass | 3/3 |
| L1.response.triggers | ["emergency"] | ["emergency"] | pass | 3/3 |
| L2.parse.callsign.snapped_to | N312LM | N312LM | pass | 3/3 |
| L2.parse.intent | position_report | position_report | pass | 3/3 |
| L2.parse.slots.position | East 34th | East 34th | pass | 3/3 |
| L2.response.mode | locked_silent | locked_silent | pass | 3/3 |
| L3.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L3.parse.intent | position_report | position_report | pass | 3/3 |
| L3.parse.slots.altitude_ft | 800 | 800 | pass | 3/3 |
| L3.parse.slots.corridor | East River | East River | pass | 3/3 |
| L3.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L3.parse.slots.position | Williamsburg Bridge | Williamsburg Bridge | pass | 3/3 |
| L3.response.mode | locked_silent | locked_silent | pass | 3/3 |
| summary.transmissions | 1 | 1 | pass | 3/3 |
| summary.transmissions_after_lock | 0 | 0 | pass | 3/3 |

## S6: Volume cap, the fourth helicopter is handed off

3/3 | result file `S6-20261011T170214Z.json` | ASR mode `pinned` | 3 run(s)

| expectation | expected | actual (last run) | status | passed |
|---|---|---|---|---|
| E1.geometry.count | 4 | 4 | pass | 3/3 |
| E2.geometry.no_alert>=advisory | none | none | pass | 3/3 |
| L1.parse.callsign.snapped_to | N2646X | N2646X | pass | 3/3 |
| L1.parse.intent | checkin | checkin | pass | 3/3 |
| L1.parse.slots.altitude_ft | 400 | 400 | pass | 3/3 |
| L1.parse.slots.corridor | East River | East River | pass | 3/3 |
| L1.parse.slots.direction | northbound | northbound | pass | 3/3 |
| L1.parse.slots.origin | Downtown Skyport | Downtown Skyport | pass | 3/3 |
| L1.response.latency_ms | <=3000 | 2 | pass | 3/3 |
| L1.response.mode | speak | speak | pass | 3/3 |
| L1.response.spoken_contains | ["Downtown Skyport"] | MEDEVAC Two Six Four Six X-Ray, Landed advisory, radar conta | pass | 3/3 |
| L1.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L1.response.tier | auto | auto | pass | 3/3 |
| L2.parse.callsign.snapped_to | N38BL | N38BL | pass | 3/3 |
| L2.parse.intent | checkin | checkin | pass | 3/3 |
| L2.parse.slots.altitude_ft | 1000 | 1000 | pass | 3/3 |
| L2.parse.slots.corridor | Hudson | Hudson | pass | 3/3 |
| L2.parse.slots.direction | northbound | northbound | pass | 3/3 |
| L2.parse.slots.origin | Downtown Skyport | Downtown Skyport | pass | 3/3 |
| L2.response.latency_ms | <=3000 | 2 | pass | 3/3 |
| L2.response.mode | speak | speak | pass | 3/3 |
| L2.response.spoken_contains | ["Downtown Skyport"] | MEDEVAC Three Eight Bravo Lima, Landed advisory, radar conta | pass | 3/3 |
| L2.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L2.response.tier | auto | auto | pass | 3/3 |
| L3.parse.callsign.snapped_to | N312LM | N312LM | pass | 3/3 |
| L3.parse.slots.altitude_ft | 1000 | 1000 | pass | 3/3 |
| L3.parse.slots.corridor | Hudson | Hudson | pass | 3/3 |
| L3.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L3.response.latency_ms | <=3000 | 3 | pass | 3/3 |
| L3.response.mode | speak | speak | pass | 3/3 |
| L3.response.template_id | ACK_CHECKIN | ACK_CHECKIN | pass | 3/3 |
| L3.response.tier | auto | auto | pass | 3/3 |
| L4.parse.callsign.snapped_to | N761NY | N761NY | pass | 3/3 |
| L4.parse.intent | checkin | checkin | pass | 3/3 |
| L4.parse.slots.altitude_ft | 500 | 500 | pass | 3/3 |
| L4.parse.slots.corridor | East River | East River | pass | 3/3 |
| L4.parse.slots.direction | southbound | southbound | pass | 3/3 |
| L4.parse.slots.origin | East 34th | East 34th | pass | 3/3 |
| L4.response.mode | handoff | handoff | pass | 3/3 |
| L4.response.spoken_contains | ["standby", "controller will be with you"] | MEDEVAC Seven Six One November Yankee, standby, controller w | pass | 3/3 |
| L4.response.template_id | STANDBY_HANDOFF | STANDBY_HANDOFF | pass | 3/3 |
| L4.response.tier | handoff | handoff | pass | 3/3 |
| L4.response.triggers | ["desk_over_capacity"] | ["desk_over_capacity"] | pass | 3/3 |
| summary.auto_transmissions | 3 | 3 | pass | 3/3 |
| summary.handoffs | 1 | 1 | pass | 3/3 |


# Additional dataset survey

Research by the delegated dataset agent on 2026-10-11. No additional audio or
provider calls were used for this survey. The UWB evaluation is tracked in
#34.

| Dataset | Additive coverage | Recommended use and limits |
|---|---|---|
| [TartanAviation, CMU](https://theairlab.org/tartanaviation/) | US regional airports: towered KAGC and non-towered KBTP; concurrent radio and ADS-B. Official release reports 3,374 hours of speech and 661 days of ADS-B. | Best mission fit for roster/context evaluation and synchronized radio/trajectory visualizations. Original audio/timing metadata is not a gold transcript benchmark. Verify the actual data license before use; the repository's BSD software license is insufficient. |
| [ATCOSIM, TU Graz / EUROCONTROL](https://www.spsc.tugraz.at/databases-and-tools/atcosim-air-traffic-control-simulation-speech-corpus.html) | Human controller speech and manual transcripts, independent of UWB/ATCO2. Speaker/session metadata enables grouped testing. | Easiest controlled human-voice ASR follow-up. Clean headset simulation, not real radio or helicopter validation. The [custom license](https://www2.spsc.tugraz.at/databases/ATCOSIM/DOC/license.txt) permits R&D including commercial R&D; redistribution permission is limited to one's own organization with notice. |
| [LDC ATC0, LDC94S14A](https://catalog.ldc.upenn.edu/LDC94S14A) | Approximately 70 hours of real US radio from BOS, DFW and DCA; 8 kHz audio, timed transcripts, flight identifiers. | Strong US-domain benchmark, subject to LDC access/agreement. Airport traffic still does not establish NYC helicopter accuracy. Distinct from the Czech UWB-ATCC corpus despite similar names. |
| [NASA ASRS helicopter reports](https://asrs.arc.nasa.gov/docs/rpsts/helo.pdf) | Helicopter safety narratives for weather, ambiguity and near-conflict scenarios. | Useful to design classifier/adversarial test cases. Text narratives are not audio, verbatim radio labels, or incident-rate evidence. NASA identifies reports as [voluntary and unverified](https://asrs.arc.nasa.gov/search/database.html?textSearchType=contains). |

For TartanAviation, see the [dataset paper](https://www.nature.com/articles/s41597-025-04775-6)
and [official audio instructions](https://github.com/castacks/TartanAviation/blob/main/audio/README.md).
The sample is listed as 314 MB compressed across 13 files. A useful bounded next
step is license verification followed by manual labeling of 50–100 US utterances
for spoken callsign, altitude, intent and speaker role. ADS-B candidate aircraft
are context, not proof of the spoken callsign.

## Actual metadata EDA: ATCOSIM

The subagent downloaded only the official
[utterance CSV](https://www2.spsc.tugraz.at/databases/ATCOSIM/TXTdata/fulldata.csv).
SHA-256: `e4dffacf8ddab03c6c0dfa7f80bc6d3e711b75ba6d473ae89437d0ab5d0418b9`.
The aggregate results are saved in `atcosim-metadata-summary.json`; the source CSV
and transcripts are not committed.

- 10,078 utterances; summed segment duration 10.686 hours.
- 10 speaker IDs and 50 sessions; median segment duration 3.719 seconds.
- 12 recordings flagged corrupt; 7,597 distinct lowercased/trimmed transcripts.
- Exact keyword searches: no `helicopter`, `heli`, `VFR`, `visual`, `mayday`, or
  `emergency`; 43 utterances contain `say again`.
- `climb`: 1,408 utterances; `descend`: 638; `flight level`: 2,189.

These are lexical counts, not semantic annotations. They support using ATCOSIM
for independent human-voice coverage, not helicopter or emergency coverage.

Do not count another ATCO2-derived release as independent audio evidence without
checking its original recordings. The same caution applies to UWB-trained
fine-tuned models tested on UWB. Additional sources should broaden the domain
and validate specific failure modes rather than simply increase clip counts.

Reproduce the metadata aggregates from a private local copy of the official CSV:

```sh
uv run --project speech --offline --no-sync python qa/uwb/atcosim_eda.py /absolute/path/to/fulldata.csv
```

The parent agent independently reproduced every saved aggregate from that CSV.

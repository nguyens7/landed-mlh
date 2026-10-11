# UWB research evaluation: 150 additional real-radio clips

**The recordings add exact-audio coverage beyond the existing ATCO2 sample, but
the current ASR baseline struggles on this test.** These results support further
failure analysis, not a claim of operational or NYC helicopter accuracy.

Run on 2026-10-11 using `gemini-3.8-flash`, the existing generic ATC prompt and
existing `speech/asr.py` implementation. One primary transcription per clip,
`resamples=0`, four concurrent workers, Sean's confirmed paid Gemini project.
No OpenAI calls. All 150 clips were uncached; all completed successfully.

## Sample and overlap

| Check | Result |
|---|---|
| Source | UWB-only `Jzuluaga/uwb_atcc`, pinned test revision `1e8270beb8c1643c8735dddb7229fffb0e399f74` |
| Source test rows scanned | 2,822 |
| Exact decoded-audio matches against existing 100 ATCO2 clips | 0 across the full UWB test split |
| Exact duplicate waveforms within UWB test split | 0 |
| Frozen sample | 150 distinct clips, seed 34, across 150 source recording IDs |
| Eligible source recording IDs | 656 |
| Duration | 9.965 minutes; median 3.59 s; range 2.00–7.86 s |
| Published role labels | 80 controller (`AT`), 48 pilot (`PI`), 22 mixed (`PIAT`) |
| Normalized reference-text matches against ATCO2 baseline | 0 in selected sample |

The round-robin sample favors coverage of source recording IDs. It is not a
population-weighted sample or proof of 150 independent speakers/sessions.
Exact waveform hashes do not detect resegmented or transformed duplicates.
Gemini pretraining overlap is unknown. Published UWB train/test session separation
was not established; this is not an independent test for a model trained on UWB.

## Recognition and latency

| Metric | Result |
|---|---|
| Corpus normalized WER | **47.05%** |
| Word errors | 338 substitutions + 89 deletions + 188 insertions / 1,307 reference tokens |
| Median clip normalized WER | 40.00% |
| Exact normalized transcripts | 11 / 150 (7.33%) |
| Empty hypotheses | 0 / 150 |
| Uncached primary ASR latency, median | **3.60 s** |
| Uncached primary ASR latency, p95 | **22.01 s** (nearest-rank percentile) |
| Batch wall time | 232.40 s with four workers |
| Controller-labeled clips, corpus WER | 38.96% (80 clips) |
| Pilot-labeled clips, corpus WER | 58.18% (48 clips) |
| Mixed-role clips, corpus WER | 56.05% (22 clips) |

WER uses Landed's existing normalization, including digit/phonetic-run collapsing.
Eligibility uses at least four whitespace-delimited reference words before that
normalization; a spoken callsign can collapse to one token. Individual clip WER
can exceed 100% when there are insertions. No outliers were removed. These are
errors against published references; manual audio review is needed to distinguish
recognition errors from reference or segmentation issues. The selected references
have no bracket/tag markers or explicit `unintelligible` markers.

Latency measures the primary transcription call only, including its request
handling; it excludes consistency resamples, parser, policy, TTS and playback.
The median ASR call alone exceeds the three-second full voice-loop goal on this
sample. This does not measure the current demo's scripted or synthetic scenario
latency. Neither compare nor pool these scores directly with a different corpus
and claim a model regression or improvement.

Callsign/altitude/intent field accuracy, emergency recall, handoff accuracy and
confidence calibration are **not measured**: the references have no manually
verified Landed field labels, and `resamples=0` omits the deployed consistency
component. Self-reported confidence must not be interpreted as a calibrated
handoff score.

## Reproducibility and next steps

See [README.md](README.md) for source licensing, hashes, sampling and commands;
`sample-summary.json` and `evaluation-summary.json` contain aggregate provenance.
Audio, reference transcripts, model transcripts and caches remain private and
untracked. The evaluation is noncommercial research under the upstream UWB
CC BY-NC-SA 4.0 terms; this does not grant commercial training/deployment rights.
Attribution: Luboš Šmídl, University of West Bohemia; source release prepared by
Juan Pablo Zuluaga. No raw corpus material is redistributed in this PR.

Offline verification checks every result against the frozen manifest, recomputes
aggregate WER, and stamps manifest/source/results hashes. Repeated preparation
must yield the same sample. The manifest hash includes local file paths and is a
run-specific audit hash; the committed source IDs/audio hashes allow sample
comparison across machines. Two injected failure checks verified that changed
manifest bytes are rejected and a failed rerun removes a stale success summary.

Recommended follow-up: manually review a small error sample and annotate critical
fields, then test conservative abstention with the full confidence pipeline.
Prioritize US towered/non-towered data for domain coverage; see the delegated
[dataset survey and ATCOSIM metadata EDA](DATASETS.md). Avoid advertising these
numbers as NYC helicopter accuracy or using raw UWB audio in pitch playback.

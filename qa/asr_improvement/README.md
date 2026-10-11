# Cost-bounded ASR improvement experiment

Tracked and claimed in [#41](https://github.com/nguyens7/landed/issues/41). This research compares prompting, conservative segmentation, and an independent local model. All changes are confined to `qa/asr_improvement/`; no speech default, app, server, or pitch behavior changes. The speech owner was contacted on #3 before any proposed shared-path change. No reply or shared-path permission is assumed.

## Decision

**Do not switch the demo's ASR prompt on these results.** A nonbinding Prague vocabulary prompt lowers confirmation WER against a fresh control, but worsens the numeric-sequence proxy and has an uncertainty interval crossing zero. A longer literal prompt regresses; conservative outer trimming does not beat the control on the development set. The independent general English Whisper-medium.en model regresses substantially on both subsets, so it is not a justified replacement or fallback on this sample.

The positive result is a reproducible comparison and a narrower diagnosis, not a demonstrated portable improvement. The original 150-clip UWB benchmark remains **47.05%**. No corrected gold labels, post-hoc sample exclusions, fine-tuning, or new OpenAI calls were used.

## Audit and partition

The original #34 UWB manifest/results are pinned by SHA-256 in `plan.json`. Seed 41 selects 25 audit/development clips, 75 separate confirmation clips, and 50 held aside from prompt comparisons. Selection deliberately enriches the audit for errors, numeric mismatches, exact matches, and random cases. The development subset's WER is therefore much higher than the corpus average.

All 150 source filename prefixes are distinct; these are lineage proxies, not established distinct speakers or independent recording sessions. The full UWB corpus had already informed #34/#37 diagnostics. Confirmation is held out from this prompt-development round, **not a pristine external test**. Preserve a separately annotated US regional-airport test for later claims.

`audit.json` records a review of 25 cached transcript/reference pairs plus duration, clipping, and outer-boundary measurements. Tags overlap: nine callsign differences, six numeric differences, nine language/reference-coverage listening flags, and six exact normalized baseline matches. This is a **signal/text audit, not a human listening audit**. Gold references remain unchanged. Czech-looking output beside very short references is a reason to check audio and annotation scope, not proof of reference mistakes or hallucinations. No full transcripts or raw audio are committed.

Outer trim opportunities are small: median 60 ms and maximum 215 ms across the audit. UWB clips are already segmented. This does not test voice activity detection on continuous radio, split-turn reconstruction, or lost words outside clip boundaries.

## Comparisons

All paid arms use `gemini-3.8-flash`, temperature zero, low thinking, the same transcript/uncertain-words/quality schema, and a single request per uncached input. SDK automatic retries are disabled. Maximum output is 8,192 tokens, allowing thinking and JSON completion. This differs from the old baseline's 2,000-token cap, so a fresh original-prompt control is included. Control and domain confirmation jobs ran contemporaneously with three workers each; network/provider variation remains possible.

| Development arm (25 clips, 152 reference tokens) | Corpus WER | Exact numeric-sequence proxy | Provider failures |
| --- | --- | --- | --- |
| Historical cached baseline | 90.13% | 6/18 | 0 |
| Fresh original-prompt control | 86.18% | 6/18 | 0 |
| Longer literal prompt | 99.34% | 4/18 | 1 |
| Literal + padded outer trim | 86.84% | 5/18 | 1 |
| Nonbinding Prague vocabulary | 76.97% | 7/18 | 0 |
| Local general Whisper-medium.en | 134.21% | 7/18 | 0 |

The regional vocabulary was developed from the audit (airline/airport names, no gold callsign numbers). It is expressly optional, never a roster to force. Its exact string is in `experiment.py`. Candidate selection was declared before confirmation runs; `selection.json` was saved after fixing its import environment and before confirmation scoring. No further tuning followed confirmation.

| Confirmation arm (75 clips, 678 reference tokens) | Corpus WER | Exact numeric-sequence proxy | Provider failures |
| --- | --- | --- | --- |
| Historical cached baseline | 41.45% | 31/68 | 0 |
| Fresh original-prompt control | 45.87% | 33/68 | 1 |
| Nonbinding Prague vocabulary | 41.59% | 29/68 | 0 |
| Local general Whisper-medium.en | 75.52% | 18/68 | 0 |

The regional prompt changes WER by **−4.28 percentage points** versus the fresh control. It improves 35 clips, worsens 21, and ties 19. Its exploratory paired clip-bootstrap 95% interval is **−9.86 to +1.37 points**, crossing zero. The numeric proxy gains eight exact matches and loses 12. It also approximately matches the historical baseline, illustrating why a single cached comparison is insufficient. See `paired-summary.json`.

The numeric proxy compares ordered standalone integer tokens only on references containing at least one such token. It does not label callsigns, headings, altitudes, or frequencies; alphanumeric callsigns and normalization effects limit its meaning. It is not operational field accuracy. Provider failures remain explicit errors and count as empty hypotheses in WER; they are not successful silence or silently excluded cases. One fresh control failure also affects the comparison.

Latency fields in `results.json` distinguish stored successful observations from successful uncached requests and count cache reuse and failures separately. Failed calls never enter successful latency percentiles. Gemini timing is request latency; local timing includes decoding but excludes model initialization. Neither is full-pipeline latency. Exact-input segmented cache hits inherit old observations rather than generating new timing measurements.

## Independent model

The selected general model is [Systran/faster-whisper-medium.en](https://huggingface.co/Systran/faster-whisper-medium.en), revision `a29b04bd15381511a9af671baec01072039215e3`, an MIT-licensed CTranslate2 conversion of general OpenAI Whisper-medium.en. Inference is local on CPU with int8, four threads, beam size five, language English, no previous-text conditioning, and no VAD. SoundFile loads verified mono float32 PCM; SciPy polyphase resampling converts the source 8 kHz to 16 kHz for Whisper. There is no ATC fine-tuning in this checkpoint's stated lineage; original pretraining overlap is unknown. English-only decoding is a limitation for mixed-language radio.

The repaired fixed run completed all 100 development/confirmation clips with zero errors. Confirmation WER is **75.52%** versus fresh Gemini control **45.87%**; the numeric proxy is **18/68** versus **33/68**. Development WER is **134.21%** (WER can exceed 100% because insertions add errors). This general English model is not a justified replacement on this sample; its language restriction and original training overlap limit interpretation. Setup first failed on a missing checkpoint vocabulary file, before any clip results. After adding the pinned vocabulary, all 100 file-decoder attempts failed before transcription because installed PyAV 19 rejects faster-whisper 1.2.1’s `metadata_errors` keyword. That failed artifact/seal is retained privately as `decoder-failed-*`; no failed text output was used for selection. The repaired PCM-input path starts a separately sealed run with identical model/decoding settings. This is a setup repair, not model tuning. No private audio is uploaded for this arm. Successful model initialization took 1.08 s; the sum of 100 clip inference times was 339.64 s. Public checkpoint download time is excluded from inference timings and was slow in this environment. Confirmation decode median/p95 is 3.16/3.81 s; fresh Gemini control request median/p95 is 2.58/5.94 s across 74 successful requests, and regional Gemini is 2.44/6.95 s across 75. These are different execution paths, not full-pipeline performance or a reliable deployment ranking. Dependencies are locked in the experiment's own `uv.lock` and do not modify `speech/`. Before inference, `local-identity.json` seals streamed SHA-256 hashes of model/config/tokenizer files, inference settings, package versions, Python, and architecture. Resume rejects changed identities, duplicate/unexpected clip IDs, changed PCM fingerprints, and inconsistent normalized text. A process lock prevents simultaneous local append; reports publish the sealed provenance.

## Cost and licensing

Sean authorized a **$10 API ceiling**, not a spending target. Before each request, a process-locked ledger reserves $0.033792 using 4,096 input and 8,192 output tokens at the [2026-10-11 standard rates](https://ai.google.dev/gemini-api/docs/pricing): $0.75/M input and $3.75/M output including thinking. Audio is capped at 20 s and prompt bytes at 3,000; the [audio guide](https://ai.google.dev/gemini-api/docs/audio) specifies 32 audio tokens/s. The reservation includes conservative input/schema headroom. Unknown/failed usage is never refunded and reruns retain the ledger.

242 paid requests were reserved: **$8.177664 maximum under the assumptions above**. Successful response metadata totals **$0.11352675 estimated**, with three failures retaining unknown actual usage at their full reservations. Estimates are not billing receipts. The harness caches exact audio/model/prompt/config identities, uses no confidence resampling, and rejects incomplete outputs explicitly. It stops before a request if the next reservation exceeds $10. Local inference has zero provider API charges; it still uses disk, download bandwidth, and CPU time.

An additional tuning round was rejected by automatic approval review because it would extend the declared frozen experiment with more audio uploads and spend. That round was not executed. This report uses the frozen comparison and local-model arm.

UWB's source license is CC BY-NC-SA 4.0; this remains bounded noncommercial research. Do not treat it as permission for commercial model training or raw-data redistribution. See #34/#36 for source licensing and exact ATCO2 audio-overlap checks. Tartan data is excluded because its raw-data license scope remains unresolved. An ATC-fine-tuned model trained on UWB was intentionally excluded as an independent baseline.

## Listening follow-up: model-assisted audit complete; human review pending

Sean requested an auditory review of the same 25 clips. After the capability limitation was disclosed, Sean explicitly selected a separate Gemini-assisted audio audit. That stage completed 25 attempts (24 structured reviews, one unretried failure) for $0.03146 known usage, with cumulative conservative reservations of $9.022464. See [the model-assisted findings and prioritized fixes](ASSISTED_AUDIT.md). It withheld references and prior outputs during each audio review; it did not produce validated gold. This agent session rejects audio input, so **no listening adjudication or critical-number validation was completed**. The earlier suggestion that this agent could listen directly was a capability mistake. No model consensus is substituted for listening, no references are corrected, and no metrics change.

`listening_review.py` prepares a private, self-contained worksheet from the sealed inputs and cached outputs. It includes all 25 original WAV clips, raw and normalized references, model comparisons, and fields for independent hearing, callsign, heading, altitude, frequency, runway, other numbers, and timestamped evidence. Reference/model comparisons stay hidden until the reviewer records their hearing; that first-hearing text is then locked. Playback supports normal and 0.8× speed. Exported notes are explicitly pending a second independent review, even if all first-pass cases are filled. No inference or provider API calls run.

```sh
uv run --project qa/asr_improvement --offline --no-sync python qa/asr_improvement/listening_review.py /private/tmp/landed-asr-data /private/tmp/new-listening-review/review.html
```

Open the HTML locally. It embeds research audio and full transcripts, so keep it and exported notes outside Git. Do not publish them. The prepared private copy is available at `http://127.0.0.1:8126/listening.html` while the loopback-only server runs. Refreshing loses unsaved notes; use **Export review JSON** before closing. The worksheet sends no data externally.

What to fix next depends on actual hearing, not the existing text flags:

- If spoken callsign digits/letters are wrong in ASR, create frozen, field-labeled regression cases and evaluate an opt-in callsign treatment with the speech owner. Do not force a regional roster.
- If references omit audible words, version proposed coverage corrections separately with timestamps and two-reviewer approval. Preserve and report the original benchmark too.
- If only spelling/number rendering differs, change evaluation normalization after checking that it preserves leading zeros, alphanumeric callsigns, and frequency boundaries; do not call this an acoustic improvement.
- If language mismatch explains a case, label the language and score that slice separately before selecting a multilingual model.
- If the audio is ambiguous, retain uncertainty and evaluate safe abstention/handoff rather than inventing a gold number.

These are conditional work items, not conclusions about the audio. Twelve of 18 numeric-eligible audit cases disagree between the cached baseline and reference under the integer proxy; that prioritizes review but does not identify which side is right. The sample is error-enriched, so this is not a population estimate. No further provider spend is justified until this evidence gap is addressed.

## Next work justified by this evidence

1. Listen to and adjudicate the 25 flagged cases with a second reviewer, recording whether gold scope, language, numbers, or actual acoustic mistakes explain each mismatch. The current audit cannot resolve that.
2. Build a licensed US regional-airport holdout with manually labeled callsign, heading, altitude, frequency, and emergency outcomes. Tartan raw-data permission remains a prerequisite; do not infer it from code licenses.
3. Test padded turn segmentation on continuous radio, where it can materially change input boundaries; already segmented UWB clips provide little evidence for it.
4. If those labels support further experiments, compare a stronger independent general multilingual model locally and region-specific optional vocabulary on untouched recordings. Check model training overlap before evaluating ATC-tuned checkpoints, and licensing before fine-tuning.

No extra model run, fine-tuning, production prompt switch, or deployment is included in this PR. More spend alone is not justified by these results.

## Reproduce and verify

Use Python 3.13+ and the isolated locked environment:

```sh
uv sync --project qa/asr_improvement --locked
uv run --project qa/asr_improvement --offline --no-sync python qa/asr_improvement/experiment.py prepare /private/tmp/new-asr-experiment --source /private/tmp/landed-uwb-data
uv run --project qa/asr_improvement --offline --no-sync python -m unittest discover -s qa/asr_improvement -p 'test_*.py' -v
```

Keep provider runs explicit: `experiment.py gemini DIRECTORY --subset audit_development --variant control|literal|segmented|domain`. `--offline` blocks uv dependency resolution, not the provider request. The existing paid personal Gemini key is loaded by `speech/keys.py` through Secret Manager, only in process. No credential values are logged or committed. A deployed integration would need its own workload key; no deployment is part of this work.

`prepare` refuses a nonempty directory. `freeze.json` seals plan, manifest, and baseline digests; all run/report entry points verify them, complete disjoint membership, normalized references, and original per-clip PCM hashes. The existing run was retrospectively sealed after independent review, verifying original source hashes and the already declared plan hash before sealing. No source audio or references changed. Reproducing a different experiment uses a new directory, rather than overwriting results.

Download the selected checkpoint revision into a local directory, verify `model.bin` SHA-256 `11b220779aea4c6f3ce9d2549c8a95ea869ed84066864b999531ef53e594fe5b`, then run `experiment.py local DIRECTORY --model-path MODEL_DIRECTORY` for the 25 development and 75 confirmation clips. The 50 reserve clips receive no new inference.

With private inputs retained, `experiment.py report DIRECTORY --output results.json` recomputes the aggregates, and `paired.py DIRECTORY OUTPUT` recomputes the uncertainty analysis. Raw inputs and complete model outputs remain in `/private/tmp/landed-asr-data/`; the public aggregates alone cannot independently reproduce acoustic accuracy. Eight offline tests cover persistent budget rejection, segmentation padding/internal pauses, invalid PCM, frozen metadata/PCM tampering, preparation overwrite rejection, numeric denominators, mixed cached/failed latency accounting, and local resume identity/duplicate rejection.

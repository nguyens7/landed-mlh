# TartanAviation exploration and ASR diagnosis

Issue: #37. This is a bounded research inspection, not an app integration or an accuracy improvement. It makes no provider calls. Raw WAV, CSV, per-aircraft tracks, and full UWB transcripts stay outside Git.

## License finding

**The separately hosted raw-data license remains unresolved.** The [official project website](https://theairlab.org/tartanaviation/) describes an open dataset and links its download code, but does not state data-specific license terms. The [repository license](https://github.com/castacks/TartanAviation/blob/4065f5bb11c3d8e557dcaf20a56469e6b0738714/LICENSE) is BSD 3-Clause for the code repository.

The paper points to [Zenodo release 14699102](https://zenodo.org/records/14699102). Its [primary API metadata](https://zenodo.org/api/records/14699102), checked on 2026-10-11, says `cc-by-4.0`, but identifies the resource as **software** and contains only a 4,232,010-byte GitHub source archive (`md5:240bdf250ba46e1e80d3c22ef623d8c0`). This does not establish that CC BY 4.0 also covers the raw audio and ADS-B objects on CMU's separate server. The inspected raw ZIP directories contain no license/readme files. The paper's article license and a third-party Hugging Face mirror's license claim do not resolve that scope.

Ask the dataset authors to confirm whether CC BY 4.0 applies to the raw and filtered audio, transcripts, ADS-B, and any derived training data; whether commercial training and demo redistribution are permitted; and the required attribution. No author message has been sent. Until scope is confirmed, retain this private exploration and aggregate report, and do not embed or redistribute the recordings in a public pitch or train a commercial model on them. This is a provenance finding, not a legal determination.

## Sample and overlap

The default download scripts select **2020-11-02 audio** and **2022 ADS-B**. They are independent samples. The 2020 raw ADS-B archive has no 2020-11-02 member. The official radio object listing also has no 2020-11-13 radio archive (HTTP 404), although that date exists in ADS-B.

The first shared available November date after the default sample is **2020-11-14 at KBTP**. We inspected the day's ZIP directory, then downloaded two small radio recordings and one raw ADS-B CSV using HTTP byte ranges. Selection favors small files and is not representative or random. Both WAV files are 44.1 kHz mono. Source URLs and exact members are in `explore.py`; SHA-256 hashes are in the summaries. The bounded downloader records archive sizes and ETags privately in `provenance.json`.

| Measurement | Recording 6 | Recording 26 |
| --- | --- | --- |
| UTC metadata start | 13:53:43.494879 | 18:05:55.092715 |
| UTC metadata end | 13:55:04.630872 | 18:07:17.433580 |
| Decoded duration | 81.041 s | 82.269 s |
| ADS-B rows within metadata window | 114 | 413 |
| Distinct aircraft IDs within window | 2 | 6 |
| Distinct aircraft/position/time tuples | 18 | 213 |
| ADS-B age range | 0.396–59.491 s | 0.018–59.420 s |
| 100 ms audio windows above −30 dBFS RMS | 6 / 811 | 142 / 823 |

The CSV contains 76,684 usable rows, 314 completely blank rows, and one other invalid row, spanning 2020-11-14 12:49:15.637105 through 2020-11-15 03:59:30.882259 UTC with 41 aircraft IDs. Do not drop next-day records solely because the archive folder has the preceding date. Legacy date and time cells are Python-list strings; the repository's newer processing script expects a different format. Parse the legacy cells as literals, never executable code.

The [official audio recorder](https://github.com/castacks/TartanAviation/blob/4065f5bb11c3d8e557dcaf20a56469e6b0738714/audio/recording/run_adsb_audio.py) writes metadata using `datetime.utcnow()`. The [ADS-B recorder](https://github.com/castacks/TartanAviation/blob/4065f5bb11c3d8e557dcaf20a56469e6b0738714/adsb/recording/run_recorder.py) splits receiver timestamps and compares them with UTC. This supports UTC interval matching. It does **not** establish clock calibration, accurate transmission boundaries, or that a particular aircraft spoke. Metadata spans exceed decoded WAV duration by about 95 ms and 72 ms, respectively. Receiver reports are repeated in the CSV and age can approach 60 s; neither row count nor interval overlap proves fresh independent observations.

Recording 26 has more high-energy windows and is a better candidate for manual listening and utterance annotation. Energy is not speech recognition: no word counts, emergency labels, helicopter identities, transcripts, or field accuracy have been established for either recording. No pickle deserialization or downloaded script execution was used.

## What strengthens the demo and pitch

1. **Real regional-airport replay:** after license confirmation and manual annotation, pair a short radio exchange with a map and timeline. Show reported track time, observation age, and missing-data intervals. Label the airport KBTP; this is not NYC SFRA evidence.
2. **Honest abstention:** replay a noisy or ambiguous call while the map exposes several candidate aircraft. Keep the association unresolved unless the audio and evidence support it. ADS-B is context, not a transcript label.
3. **Stale-traffic visualization:** fade old reports and show a freshness badge. Deduplicate receiver reports before interpolation and do not animate a stale position as fresh telemetry.
4. **Evidence panel:** show real-audio benchmark results separately from synthetic demonstrations, including critical-field error rates and latency. Do not equate plausible replay with validated collision prevention or certified emergency detection.

The official dataset covers a towered airport (KAGC) and a non-towered airport (KBTP), making it a useful US terminal-airspace complement to the European UWB/ATCO2 evaluations. These two KBTP samples do not establish helicopter, medevac, or emergency coverage. A later KAGC sample could test that hypothesis, once license scope is confirmed.

## Why UWB word error rate is high

The cached #34 evaluation remains **47.05% corpus normalized WER**: 338 substitutions, 89 deletions, and 188 insertions over 1,307 reference tokens. No ASR improvement was implemented here.

- The 139 clips with at least four normalized reference tokens still score **43.15%**. Eleven short references have many insertions, but excluding them does not explain the main gap. Keep all 150 in the headline result.
- Symmetric, post-hoc spelling aliases for `takeoff`, `startup`, `goodbye`, and `lineup` yield **43.93%** on all 150. This isolates a scoring convention effect; it is not a better recognizer and must not replace the preregistered baseline.
- Single-token substitution examples include `clear`/`cleared`, airport/airline vocabulary, and `060` → `020`. Some variants could be reference or spelling issues; number and callsign errors can change operational meaning. Only a listening audit can adjudicate them.
- Of 87 clips with single-call self-score ≥0.8, 57 have clip WER >0.25. This is evidence against trusting that self-score alone; it does not evaluate the deployed resampling confidence, emergency recall, or callsign accuracy.

`uwb-diagnostics.json` contains recomputed aggregates and input hashes. It does not publish full utterances. UWB accent/region mismatch, noise, clipped speech, and prompt behavior are plausible causes to test, not established causal explanations from this sample.

## Improvement sequence

1. **Audit labels and critical fields first.** Listen to 20–30 stratified error cases and label reference mistakes, clipped audio, noise, callsign, altitude, heading, runway, and emergency intent. Use a second annotator for consequential disagreements. Preserve the original benchmark and report corrected-reference results separately.
2. **Create a development set and an untouched recording-level holdout.** The 150 UWB clips have already informed diagnostics; they are a regression set, not an untouched final test. Split by source recording and, where metadata permits, speaker. Build a separately annotated US regional-airport holdout after license confirmation. Synthetic phrase-bank results remain separate.
3. **Run controlled audio/prompt experiments.** Compare the generic ATC prompt with literal transcription instructions and nonbinding aviation vocabulary. Preserve unknown words; do not supply the answer or force a known roster callsign. Test voice activity detection with boundary padding and merged fragments; our 82-second sample includes extensive low-energy audio. Blindly denoising or clipping can erase numbers and must earn its place through paired evaluation.
4. **Compare an independent ASR baseline.** Evaluate a general Whisper model locally against the existing Gemini baseline before adopting domain fine-tuning. Audit training data for any ATC-tuned candidate: a model trained on UWB cannot demonstrate independent improvement on the same corpus. [Google's audio guide](https://ai.google.dev/gemini-api/docs/audio) also distinguishes general Gemini audio understanding from dedicated Cloud Speech-to-Text. [Whisper's official repository](https://github.com/openai/whisper) provides reproducible local model baselines. No additional model calls or key changes are part of this report.
5. **Choose using field risk and latency.** Report WER alongside exact callsign/heading/altitude accuracy, emergency recall, abstention coverage, false confident field errors, and median/p95 full-pipeline latency. A valid JSON response is not a correct transcript. Calibrate uncertainty on independent labeled data; use corroborating evidence and controller review for ambiguous fields.
6. **Fine-tune only after the baseline diagnosis.** Verify training and derived-model permissions, hold out whole recordings/speakers, and retain the independent US test set. A classifier can help route calls after transcription, but cannot recover an altitude or callsign erased upstream.

## Reproduce

Use the repository's locked speech environment (Python 3.13+ and `uv`). Keep private inputs in a temporary directory:

```sh
uv sync --project speech --locked
uv run --project speech --offline --no-sync python qa/tartan/explore.py fetch /private/tmp/landed-tartan-data
uv run --project speech --offline --no-sync python qa/tartan/explore.py summarize /private/tmp/landed-tartan-data --output qa/tartan/sample-summary.json
uv run --project speech --offline --no-sync python qa/tartan/explore.py summarize /private/tmp/landed-tartan-data --stem secondary-audio --member 11-14-20_audio/26.wav --output qa/tartan/secondary-summary.json
uv run --project speech --offline --no-sync python qa/tartan/diagnose_uwb.py /private/tmp/landed-uwb-data/private-results.jsonl /private/tmp/landed-uwb-data/manifest.jsonl qa/tartan/uwb-diagnostics.json
uv run --project speech --offline --no-sync ruff check qa/tartan
uv run --project speech --offline --no-sync python -m unittest discover -s qa/tartan -p 'test_*.py' -v
```

`--offline` prevents uv dependency resolution; only `fetch` itself uses the network. It limits each archive to 16 MiB transferred, validates exact HTTP ranges and ETags, and bounds selected member sizes. `summarize` and `diagnose_uwb` use local files only. The UWB diagnosis requires the private inputs retained by #34; it verifies selected IDs, references, and clip scores, then records their hashes. Without those inputs, the aggregate report remains inspectable but the benchmark cannot be independently recomputed from this PR alone.

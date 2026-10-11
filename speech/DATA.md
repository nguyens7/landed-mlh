# Data sources for the speech track

## No LiveATC audio

No LiveATC audio is used, recorded, streamed or referenced anywhere in this track. Landed never transmits on
or streams from a real aviation frequency. All audio is either synthetic (text-to-speech plus a simulated
radio channel) or the pre-recorded ATCO2 research corpus described below.

## ATCO2 test set (real ATC audio, evaluation only)

| Field | Value |
|---|---|
| Dataset | ATCO2-test-set-1h (free 1-hour subset of the ATCO2 4-hour test set) |
| URL | https://huggingface.co/datasets/Jzuluaga/atco2_corpus_1h (project page: https://www.atco2.org/data) |
| Paper | https://arxiv.org/abs/2211.04054 |
| License | "Available for research purposes" per the ATCO2 data page. The Hugging Face card carries no SPDX license and points to the "ATCO2-ASRdataset-v1_beta - End-User Data Agreement" from the ATCO2 homepage. We use it for internal evaluation only, never redistribute it, and never commit it. Review the End-User Data Agreement before any use beyond this hackathon evaluation. |
| Size | 113.5 MB parquet, 871 segments in the full 1h set. We extract 100 random clips (2 to 20 s, at least 4 words), 7.8 minutes |
| Local path | `speech/audio/atco2/` (raw parquet in `raw/`, clips in `clips/`, `manifest.jsonl`), git-ignored |
| Handling | Read as data only (pandas/soundfile). `atc_data_loader.py` from the dataset repo was not downloaded or run. |
| Content caveat | European ATC (Swiss and Czech airports; Sion, Zurich, Bern, Prague, Brno), airline telephony callsigns, non-native English. It is a stress test for noisy real radio, not NYC helicopter traffic. |
| Third-party processing | The clips were sent to the Gemini and OpenAI transcription APIs for evaluation. If the End-User Data Agreement forbids sending data to third-party services, delete the ATCO2 results and re-run locally. |

UWB-ATCC (the other public corpus mentioned in the brief) is attributed to Luboš Šmídl, University of West
Bohemia. Its LINDAT metadata lists it as public under **CC BY-NC-SA 4.0**, with no request or confirmation
step. This corrects the earlier statement that it needs a separate request. Source: the UWB-only test release
`Jzuluaga/uwb_atcc` at revision `1e8270beb8c1643c8735dddb7229fffb0e399f74`. The evaluation in `qa/uwb/` uses a
bounded 150-clip sample (9.965 minutes from 150 source recordings) for noncommercial ASR stress testing, sent
to the paid Gemini project. Attribution and ShareAlike terms apply to any sharing of adaptations. Raw audio,
reference transcripts and model outputs are untracked and not published. Results (see `qa/uwb/RESULTS.md`):
47.05% corpus WER, median primary ASR latency 3.60 s, p95 22.01 s. These are not NYC helicopter accuracy and
not full-pipeline latency.

## Synthetic audio

* Script bank: `speech/scripts/utterances.yaml`, 49 fictional pilot transmissions (scenarios S1 to S5 plus variants).
* TTS: Gemini `gemini-3.8-flash-lite-tts` (voices Charon, Kore, Fenrir); an earlier OpenAI `gpt-4o-mini-tts`
  voice set (onyx, nova, ash) is kept as an extra voice set. Raw TTS and rendered clips are git-ignored.
* Channel model: `speech/synth.py` (300 to 3,400 Hz band-pass, compression and clipping, AM-style fading noise
  floor at 20/10/5/0/-5 dB SNR, squelch clicks, optional rotor bed). `speech/manifest.jsonl` lists every clip with
  its ground truth.
* Tail numbers in the callsign roster come from `eda/data/helicopters_2026-10-10.csv` plus the simulated
  callsigns N312LM, N2646X and N2464X.

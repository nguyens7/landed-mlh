# Additional UWB ASR evaluation

This is a bounded noncommercial research evaluation of 150 real-radio UWB clips.
It does not establish operational accuracy, NYC helicopter accuracy, or commercial
training/deployment rights.

## Source and license gate

Use the UWB-only [`Jzuluaga/uwb_atcc`](https://huggingface.co/datasets/Jzuluaga/uwb_atcc)
test release, revision `1e8270beb8c1643c8735dddb7229fffb0e399f74`.
The pinned [test parquet](https://huggingface.co/datasets/Jzuluaga/uwb_atcc/resolve/1e8270beb8c1643c8735dddb7229fffb0e399f74/data/test-00000-of-00001-3a021115ca23c2a5.parquet)
is 131,266,472 bytes, SHA-256
`6a637e5b035c4e22bdf880554c900c3a775eac46c10dc9713e827dd6cbf38783`.

The original corpus is attributed to **Luboš Šmídl, University of West Bohemia**.
[LINDAT item metadata](https://lindat.mff.cuni.cz/repository/server/api/core/items/9d93d166-c18f-459e-bc3e-d71d89f7adf2)
identifies **CC BY-NC-SA 4.0** and public access. The
[license metadata](https://lindat.mff.cuni.cz/repository/server/api/core/clarinlicenses/41)
has no confirmation or additional-information requirement. This corrects the
older statement in `speech/DATA.md` that UWB needs a separate request.
[The license](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en)
permits noncommercial reproduction/adaptation; attribution and applicable
ShareAlike requirements apply when sharing licensed material/adaptations.

No express third-party-processor restriction was found. Treating a bounded
noncommercial ASR evaluation as permitted processing is an interpretation of these
terms, not an express license for commercial development. Sean confirmed the
existing Gemini key uses a paid project and authorized its use. Under
[Google's Gemini terms](https://ai.google.dev/gemini-api/terms), paid-service
inputs are not used to improve Google's products; limited abuse monitoring and
processing still apply. Do not run this data through an unverified free tier.
Do not publish raw audio, reference transcripts, or model transcript outputs in
Git, issue comments, PRs, or pitch playback.

## Why use this release

The proposed [jacktol combined dataset](https://huggingface.co/datasets/jacktol/ATC-ASR-Dataset)
contains UWB plus ATCO2. Landed already evaluates 100 ATCO2 clips. The
[preparation toolkit](https://github.com/jack-tol/atc-asr-dataset-preparation-toolkit)
replaces source IDs and splits utterances randomly, which makes source/recording
provenance harder to audit. The UWB-only release retains IDs, offsets and roles.

Exact duplicate checks compare decoded float32 PCM, sample rate, and shape against
the original 100 local ATCO2 baseline clips, and across the full 2,822-row UWB test
split. This detects exact waveform equality, not resegmented, resampled or noisy
versions of the same recording. Matching normalized text alone is not evidence of
shared audio: generic ATC phrases recur legitimately.

Eligible clips have 2–20 seconds of audio and at least four transcript words.
Seed 34 shuffles each source session, then samples in round-robin order across
sessions until 150 distinct clips are selected. This intentionally improves
recording coverage; it is not a population-weighted estimate. No training or
fine-tuning is performed. The published train/test split is not asserted to be
session-disjoint, and Gemini's pretraining overlap is unknown. Do not benchmark
UWB-trained ATC models on this sample as an independent held-out result.

## Reproduce

Keep the parquet, clips, manifest, and per-clip results in a private directory
outside the repository. The utility reads parquet as data; it does not download
or execute dataset-provided Python code.

```sh
uv sync --project speech --locked --python 3.13
uv run --project speech --offline --no-sync python qa/uwb/evaluate.py prepare \
  --directory /private/tmp/landed-uwb-data \
  --baseline-manifest /absolute/path/to/speech/audio/atco2/manifest.jsonl
uv run --project speech --offline --no-sync python qa/uwb/evaluate.py evaluate \
  --directory /private/tmp/landed-uwb-data --paid-gemini-confirmed --workers 4
```

The preparation step verifies the pinned parquet and freezes a private manifest
with source IDs, timestamps, roles and decoded-audio hashes. The evaluation uses
the existing `speech/asr.py` Gemini baseline and generic ATC prompt, with one
primary transcription per clip (`resamples=0`). It uses Sean's existing key from
Secret Manager in process memory only. OpenAI is not called. Gemini cache entries
remain in the ignored local cache; reruns reuse them. No evaluation runs in CI.

WER uses the same `normalize_for_wer` as the existing ATCO2 benchmark. Report
corpus WER, exact normalized transcripts, role/session breakdowns, and uncached
primary-call latency. Timing excludes the additional confidence-consistency
resamples and the downstream parser/talker, so it is not full-pipeline latency.
No callsign, altitude, intent, emergency-recall or handoff-accuracy claim is made
without manually verified labels. With consistency resamples disabled, the
self-reported confidence is not the deployed confidence score.

Audit a completed private run without model calls:

```sh
uv run --project speech --offline --no-sync python qa/uwb/evaluate.py verify \
  --directory /private/tmp/landed-uwb-data
```

Verification checks the frozen manifest hash, all 150 result IDs and their
reference/session/role lineage, normalized hypotheses and aggregate WER. It
records the manifest, source-revision and private-results hashes in the summary.
A failed new evaluation invalidates the previous summary before starting.

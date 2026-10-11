# Reference-blind Gemini-assisted audio audit

Sean selected this follow-up after the agent's direct audio-input limitation was disclosed. This is **model-assisted review, not human listening adjudication**. The agent inspected all 25 reference/output comparisons as text. No reference or critical number is certified as correct, no gold changed, and the original benchmark remains unchanged.

## Execution and cost

The same frozen 25 development clips received one attempt each from `gemini-3.8-flash`. Each request contained only the original WAV bytes and fixed review instructions/schema. References, filenames, prior transcripts, regional vocabulary, and experiment results were withheld. The protocol was saved before requests; SDK retries are disabled, completed/failed attempts are not rerun, and an unknown reserved attempt stops resume.

- 25 attempts: **24 structured reviews, one incomplete `NO_CANDIDATE` response**; failure was not retried.
- Added known usage estimate: **$0.03146175**, including available failed-response usage; no unknown usage in this stage.
- Added conservative reservations: **$0.8448**. Combined with the prior $8.177664, the cumulative reservation is **$9.022464**, below the $10 ceiling.
- Combined known usage estimate: **$0.1449885**; the original stage still has three unknown-usage failures. These are estimates, not billing receipts.
- Parent experiment ledger, prompts, inputs, and aggregate results remain unchanged. This is a separately authorized review stage, not the previously rejected tuning round.

`assisted-audit-protocol.json` contains the fixed prompt/schema and input/budget hashes. `assisted-audit-findings.json` contains per-case model-proposed fields, aggregate counts, and private result hashes, without full transcripts or audio. The complete private outputs remain in `/private/tmp/landed-asr-assisted-audit/`.

## What the evidence supports

Only four of 24 successful review transcripts match the reference after the existing normalization. That is disagreement, **not a finding that 20 references are wrong**. Ten extracted fields are model-marked uncertain. Neither the remaining `clear` labels nor model timestamps are validated. Proposed language counts overlap: English 17, Czech seven, Spanish two, Polish one, and Russian one. Unexpected language proposals require checking; they do not establish the language actually spoken.

The reviewed cases separate useful hypotheses:

| Case suffix | Comparison evidence | What to check or fix next |
| --- | --- | --- |
| `ybuLTX` | Gold contains only a callsign; cached ASR and blind review both propose additional non-English speech. The blind review proposes frequency `118.3`. | Timestamp and adjudicate reference scope/language before interpreting all extra words as ASR insertions. No automatic gold expansion. |
| `A91jjm` | Gold callsign digits are `296`; cached ASR merges the designator into a longer number. Blind review proposes `63906` with uncertainty, while QNH `1018` and time `17` agree across the compared text. | Prioritize callsign designator/digit separation and field-specific regression cases; a whole-utterance score hides the difference. |
| `VkJgsW` | Gold callsign digits are `904`; cached ASR has `23904`. Blind review proposes `904` but marks the callsign uncertain and does not recover the designator. | Adjudicate the prefix separately from digits. Agreement on digits does not validate the full callsign. |
| `XwCoKq` | Gold callsign suffix includes `68KP`; blind review proposes `68P` without `K` while marking the field clear. | Preserve alphanumeric suffix letters and test wrong-but-clear outputs. Do not use model certainty as verified correctness. |
| `HhPTbJ` | Gold callsign digits are `8500`; blind review proposes `500` while marking it clear. Its ending wind fragment is uncertain. | Adjudicate possible leading-digit loss; keep partial wind numbers unresolved instead of completing them from convention. |
| `xWBicz` | Existing normalization merges the gold's repeated frequency digit sequence into `12191219`. Blind review proposes two `121.900` frequency mentions with separate spans. | Use turn-aware, typed frequency comparison; keep literal speech and canonical numeric rendering separate. The decimal completion remains unverified. |
| `FxfhED` | The model review labels the transcript's wind `5 knots` as `speed`. This audit schema has no separate wind-speed kind. | Add distinct wind direction/speed types before calculating operational field accuracy. This is an audit-schema limitation, not proof of a deployed parser bug. |

These comparisons are proposed review targets, not auditory corrections. The same Gemini model family produced both evaluated ASR and the blind review; reference blindness reduces anchoring but does not create an independent judge. The six previously exact cached cases include the failed audit case; it remains a failure, not a newly wrong reference.

## Recommended order of fixes

1. **Add a typed critical-field evaluation layer.** Keep spoken form, canonical value, units, field type, turn, and uncertainty separate. Distinguish callsign, runway, heading, altitude, frequency, QNH, time, aircraft speed, wind direction, and wind speed. Preserve leading zeros and suffix letters. Keep airline aliases explicit; do not equate every guessed code automatically. The existing integer proxy remains a diagnostic, not field accuracy. No speech/ implementation is included here.
2. **Adjudicate the disputed labels and annotation scope.** Use the private listening worksheet and an audio-capable reviewer with aviation/Czech familiarity. Review the candidates above, including mixed-language coverage, before changing labels. Store proposed corrections as a separate version with timestamps and independent approval; report original and corrected scores separately.
3. **Build targeted callsign regression cases from adjudicated audio.** Focus on designator/digit concatenation, dropped leading digits, and omitted suffix letters. Measure exact full callsign and numeric-field accuracy plus abstention/handoff, rather than selecting on overall WER or self-confidence. Ask the speech owner before editing speech/.
4. **Then test one narrow opt-in treatment on untouched recordings.** A small callsign-aware treatment is a better candidate than another broad prompt round. A general multilingual model is a later comparator only after language labels and leakage checks. The present review does not select a replacement model or demonstrate an accuracy gain.

Do not spend on more trimming of these already segmented clips, fine-tuning, or another prompt sweep before those evaluation/label gaps are addressed. Continuous-radio segmentation remains a separate experiment. Tartan raw-data licensing remains unresolved.

## Reproduce without new calls

```sh
uv run --project qa/asr_improvement --offline --no-sync python qa/asr_improvement/assisted_audit_report.py /private/tmp/landed-asr-data /private/tmp/landed-asr-assisted-audit qa/asr_improvement/assisted-audit-findings.json
```

The report validates frozen source inputs, the stage protocol, 25 ordered unique result IDs, per-clip PCM/protocol bindings, and the attempt ledger. Raw audio and full transcripts stay private. Running `assisted_audit.py` is an explicit provider operation; it is not required to recompute results. Existing completed/failed artifacts are never retried. Starting a new directory is a new paid experiment requiring its own declared combined budget.

Ten offline tests pass: the original eight guards plus reference-blind request/resume and unknown-attempt rejection tests with a mocked provider. No test makes a provider call.

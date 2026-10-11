# Run-to-run agreement

Inputs: 50 pilot lines from `speech/scripts/utterances.yaml` (read-only). Each input is sent 10 times per provider with every
demo cache OFF. Agreement means all runs returned the same value. This measures the *service*, not a
claim of determinism: neither vendor documents determinism.

| Provider | Inputs | All runs agree: id / label | slots / label prob + attention | full output | Distinct full outputs (count: inputs) | Latency ms p50 / p95 | Calls over 800 ms | Fallbacks or abstentions |
|---|---|---|---|---|---|---|---|---|
| Gemini template picker (gemini-3.5-flash-lite) | 13 | 100.0% | 100.0% | 100.0% | {1: 13} | 671 / 856 | 15.4% | 0 |
| OpenAI Decisions router (gpt-6-luna) | 50 | 100.0% | 100.0% | 100.0% | {1: 50} | 326 / 488 | 1.2% | 0 |
| TypeSafe Jev router (jev-latest) | 50 | 100.0% | 6.0% | 6.0% | {1: 3, 2: 2, 3: 3, 5: 1, 6: 2, 7: 4, 8: 9, 9: 13, 10: 13} | 338 / 421 | 0.4% | 0 |
| Gemini enum router (gemini-3.5-flash-lite) | 50 | 100.0% | 100.0% | 100.0% | {1: 50} | 661 / 1053 | 18.2% | 0 |

Picker rows count `template_id` (or `handoff`) and the validated slot dict; router rows count the label,
the label probability and attention probability rounded to 2 decimals (slots column) or 4 decimals
(full output column). The picker is measured only on inputs the policy would hand to the model
(13 of 50); policy-forced inputs never reach it.

## Settings

- Gemini picker: model `gemini-3.5-flash-lite`, `temperature=0.0`, `seed=7`, `thinking_level=low`, forced function calling
  (`mode=ANY`), prompt and tools from `gemini_agent.SYSTEM` / `TOOLS` unchanged, cache OFF. The seed is passed from
  `measure_agreement.py` because `gemini_agent.gemini_model_call` does not expose one (not edited).
- Decisions router: `POST /v1/decisions`, model `gpt-6-luna`, a `choice` over 4 labels plus a `predicate`,
  client timeout 10 s for the measurement (production timeout is 800 ms), cache OFF.
  The Decisions API exposes no temperature or seed.
- Gemini enum router: `gemini-3.5-flash-lite`, `temperature=0`, `seed=7`, JSON schema with an enum label.
  Its probabilities are self-reported by the model, not calibrated.
- Jev router: `POST /v1/systemone`, model `jev-latest`, a `choice` over 4 labels plus a `noul`, client timeout 10 s for the measurement, cache OFF. No temperature or seed is exposed.
- Desk state: roster N2646X / N312LM / N405LP, altimeter 29.92, one traffic entry, N2646X on ADS-B at JRB,
  ASR 0.95, parse 0.97, callsign snap 0.95 (0.60 and ambiguous when the bank marks it ambiguous).


## Default router

Rule: highest label agreement among routers with p95 under 800 ms. Winner: `decisions` (label agreement 100.0%, full-output agreement 100.0%, p95 488 ms). Select with `LANDED_ROUTER=decisions|jev|gemini`. Thresholds are provisional until validated on our own labeled data.


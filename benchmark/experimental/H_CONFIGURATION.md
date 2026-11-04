# Strategy H — as-run configuration

Everything here is the configuration that produced `results/h_comparison.json`.
It was fixed before the first Strategy H accuracy number existed (`PLAN.md`).

## Roles and models

| Role | Model | Why |
|---|---|---|
| A stage (base marking) | `gemini-3.6-flash` | The preserved live A2/A3 response; no new whole-document request was issued |
| Escalation ("C") | `gemini-3.6-flash` | The only model that passed the earlier live escalation; `gemini-3.1-pro-preview` was quota-limited in the historical run and was not re-probed |
| No Lite model | — | H never does routine batch marking, so it needs no Lite role |

No model probe was spent for this experiment. Generation settings are inherited from the
benchmark (`temperature 0`, `topP 0.95`, thinking budget 0, identical response schema and
examiner system prompt).

## Inputs per request

| Request | Document upload | Evidence sent |
|---|---|---|
| A stage (replayed) | 7 student pages + 21 scheme pages, once | unchanged historical request |
| Escalation (live) | none | 1 student page + 1 scheme page for that item, plus the printed question text |

Escalations never include A's previous mark. That removes anchoring and makes one live
response reusable by every base run that flags the same item, so the same item is never
bought twice.

## Policies

| Policy | Signals | Cap / run | Max attempts | Provider-failure stop |
|---|---|---|---|---|
| h-low | S1, S2, S3 | 3 | 2 | 2 consecutive |
| h-medium | S1, S2, S3, S4a, S4b, S4c, S5a, S5b, S6 | 6 | 2 | 2 consecutive |
| h-high | all of the above + S7 (confidence < 0.80) + S8 | 8 | 2 | 2 consecutive |

Signal codes and severity are in `PLAN.md` §3 and `strategy_h/config.py`.

## Validation gate (accept or keep A)

A response replaces A's mark only when all of these hold:

1. JSON parses and `schema.validate_marking` reports no problems (no unknown id, no
   duplicate id, integer award, `0 ≤ awarded ≤ max_marks`, cap injected from the
   reference rather than trusted from the response).
2. Exactly one item is returned and its id matches the request.
3. `max_marks` equals the reference maximum.
4. Criterion count equals `max_marks`; every awarded criterion has a non-empty reason.
5. `awarded` equals the number of criteria marked awarded.
6. A positive award has visible transcribed evidence (its own answer or A's).

On rejection the run keeps A's mark, records the rejection reason and adds the item to
`unresolved_for_review`. A rejected or failed response is never partially applied.

## Accounting

- Every live request is written to `results/h_usage.jsonl` (separate from the historical
  ledger) with provider-reported tokens, model, key label, pool, latency, HTTP status and
  cost.
- H cost per submission = preserved A row cost for that run + the cost of each escalation
  the policy would issue. Actual spend counts each live row once; attribution counts a
  shared response once per run that uses it. Both numbers are reported separately.
- Nothing was written to `benchmark/results/`; the 91 frozen artifacts still hash-match
  `frozen_snapshot.json` (verified after the experiment).

## Reproduction

```
# offline: signals on the preserved live A runs (no provider calls)
python -m benchmark.experimental.run_experiment --signals

# live: bounded, one request per selected item, reuse valid stored responses
python -m benchmark.experimental.run_experiment --escalate --max-requests 8

# offline: score A, C and every H policy with the unchanged evaluator
python -m benchmark.experimental.run_experiment --evaluate

# offline tests
python -m pytest benchmark/tests benchmark/experimental/tests -q
```

The interpreter used here is the project-local `.tools/python/python.exe` (Python 3.13.7,
SymPy 1.14.0).

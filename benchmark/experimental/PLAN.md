# Strategy H — architecture and experiment plan

**Status:** written before the Strategy H implementation and before any Strategy H
accuracy number existed. The escalation policies below are fixed here so they cannot
be tuned to the final evaluation labels.

## 1. What the existing benchmark establishes

Facts taken from the frozen artefacts (`results/comparison.json`, `results/raw/`,
`results/api_usage.jsonl`, `reports/FINAL_AUDIT.md`), not re-derived:

| Strategy | Paper scores /87 (ref 80) | Criterion F1 | Requests | Cost USD | Main failure |
|---|---|---|---|---|---|
| A | 77, 72 | 0.9479 | 2 | 0.070251 | Q23 false deduction in both runs; Q21/Q26/Q28/Q30/Q32/Q36 disagreements in A3 |
| B | 74, 74 | 0.9610 | 33 | 0.191967 | Q7/Q8/Q19 blank extraction |
| C | 78, 82 | 0.9875 | 23 | 0.151344 | Q26/Q30: C5 under-awards both, C6 over-awards both |

C is the most accurate and the most expensive *per correct mark*; A is the cheapest
and fails on a small number of items. C's specialist branch never fired in the selected
pair (`0` raw `different` checks, `0` escalations); one targeted live single-item
escalation (C5/Q30, one student page + one scheme page, `gemini-3.6-flash`, 2,595 input
tokens, USD 0.003772) changed 1 → 2. That single proven mechanism is the atomic unit
Strategy H reuses.

## 2. Representation available today

- A criterion-level result is `{id, student_answer, awarded, max_marks, criteria[];
  confidence; flags; reason}` (`benchmark/code/schema.py`). `max_marks` is overwritten
  from the reference on validation, so a model cannot change the cap.
- Uncertainty today is *only* model self-report: `confidence` and `flags`. Verified on
  the two current A runs: A2 uses `{0.9, 0.95, 1.0}`, A3 uses `{1.0}` only. There is no
  calibration data to justify a confidence threshold, and the values are saturated.
  **Conclusion: self-reported confidence is not a usable signal in this dataset** and is
  therefore excluded from the conservative and medium policies. It appears only in
  H-high, where its effect is reported as a negative control.
- Deterministic evidence exists and is unused by any strategy: A transcribes the
  student's final answer; the printed scheme's accuracy-criterion text *is* the expected
  answer; `verifier.equivalent()` decides algebraic equivalence with SymPy. That gives a
  label-free, zero-request contradiction test.
- Exclusions (`12`, `16d`) and teacher overrides live in `ground_truth/paper-01.json`
  (`status != scored`) and are already respected by `loader.item_ids()`.

## 3. Strategy H design

```
document ──► Stage 1: Strategy A whole-paper request (unchanged, one document upload)
                 │
                 ├─ preserve A's criterion-level result verbatim (a_original)
                 ▼
           Stage 2: deterministic signal extraction (local, no requests, no labels)
                 │   S1…S7, each with a defined reason and severity
                 ▼
           Stage 3: policy selects eligible items (dedupe, severity order, cap)
                 │
                 ▼
           Stage 4: targeted escalation, one item per request
                 │   input = 1 student page image + 1 scheme page image + question text
                 │   model = A's primary model (strong tier is unavailable)
                 ├─ provider failure budget exceeded → stop, mark unresolved for review
                 ▼
           Stage 5: validation gate (schema, criterion count, award coherence,
                 │   evidence present, marks unchanged, single matching id)
                 ├─ reject → keep A's mark, flag human review, record reason
                 └─ accept → replace final mark, keep a_original + escalation record
                 ▼
           Stage 6: audit trail per item: A result, signals, request row, C result,
                    validation outcome, final decision
```

### Why the escalation input is item-independent

The escalation prompt deliberately does **not** contain A's previous mark: anchoring is
removed, and the same live response is a legitimate, cache-like reuse for every base run
that flags the item. This is what prevents duplicate escalation requests (one request
per item per document, not per configuration per run).

### Escalation signals (defined here, frozen)

| Code | Signal | Severity | Deterministic? |
|---|---|---|---|
| S1 | Structure: criterion count ≠ `max_marks`, empty/duplicate criterion codes, award outside `0..max` | 3 | yes |
| S2 | Evidence gap: marks awarded while no student answer is transcribed | 3 | yes |
| S3 | Aggregation: `awarded` ≠ number of criteria marked awarded | 3 | yes |
| S4a | Accuracy mark awarded while no method mark is awarded (multi-mark item) | 2 | yes |
| S4b | Full marks awarded while at least one criterion is unawarded | 3 | yes |
| S4c | Partial total while every criterion is marked awarded | 2 | yes |
| S5a | Answer is SymPy-equivalent to the printed accuracy answer but full marks were not awarded (under-award contradiction) | 2 | yes |
| S5b | Answer is SymPy-different from the printed answer but full marks were awarded (over-award contradiction) | 2 | yes |
| S6 | Model flags ambiguity/illegibility/scheme mismatch | 1 | model-reported, reason-tagged |
| S7 | `confidence < 0.80` | 1 | model-reported, uncalibrated |
| S8 | S5 SymPy `different` regardless of award (broad divergence) | 1 | yes |

Ordering is `(severity desc, item order)`; the cap is applied after ordering so the
selection is deterministic and independent of which items are actually wrong.

### Policies (fixed before evaluation)

| Policy | Signals | Cap / run | Intent |
|---|---|---|---|
| **H-low** | S1, S2, S3 | 3 | integrity only: never spend on a marking-judgement question |
| **H-medium** | S1, S2, S3, S4a, S4b, S4c, S5a, S5b, S6 | 6 | rule-based contradictions; no model confidence |
| **H-high** | all of the above + S7, S8 | 8 | aggressive: every algebraic divergence |

H-medium is also the required "simple rule-based configuration that does not depend on
model-reported confidence".

### Safeguards implemented

1. `a_original` is stored for every escalated item; the final item carries it.
2. `max_marks` is never taken from the response; it is injected from the reference.
3. Validation problems (unknown id, duplicate id, non-integer or out-of-range award,
   duplicate criteria) reject the whole response.
4. Criterion count must equal `max_marks`; every awarded criterion needs a reason.
5. A positive award needs visible transcribed evidence (either the escalation's own
   `student_answer` or A's preserved transcription).
6. Rejected or failed escalation → A's mark stands and the item is marked
   `human_review`.
7. One request per item per document; a valid stored response is reused, never re-bought.
8. `max_attempts=2` per request, `max_consecutive_provider_failures=2` per run; after
   that the run stops escalating and reports the remaining items unresolved. No
   whole-document retry loop during 503 capacity failures.
9. Only the student page and the scheme page for the item are uploaded (≤ 2 images).

### Cost model

`cost(H) = cost(A stage) + Σ cost(escalation requests it would issue)`. The A stage cost
is the preserved live A ledger cost for the same run (A is not re-bought: the request,
document and model are identical). Escalation cost is the provider-reported token cost
of the real row. Because one live response serves both base runs, both the **actual
spend** (unique rows) and the **per-submission attribution** (one row counted once per
run that escalates the item) are reported; they are never mixed.

## 4. Experiment configurations

- **A-only** — preserved A2/A3 (live).
- **C-only** — preserved C5/C6 (live).
- **H-low / H-medium / H-high** — for each preserved A run, Stage 1 is replayed from the
  live A payload, Stage 2 is local, Stage 4 is a fresh live request. Labelled
  *live escalation on a replayed live base*; the A stage is not re-issued, so it is not
  a second independent A sample.
- If provider capacity allows, one fresh end-to-end live A→H request sequence is
  attempted as an end-to-end confirmation; a 503 is recorded as a failed request and
  reported, never replaced by a fabricated result.

## 5. Evaluation

Same reference, same exclusions, same scoring code (`evaluator.evaluate_run`) for every
configuration. Reported per configuration and per document: criterion P/R/F1, exact item
agreement, paper-total error, per-question accuracy, false awards/deductions, and the
same restricted to the ambiguous/difficult subset (items whose reference confidence is
`medium` or whose reference evidence records an ambiguity, plus the six items where A
disagrees with the reference in at least one run).

Cost: total, per submission, per criterion, incremental escalation cost, requests per
submission, % submissions escalated, % criteria escalated.

Reliability: schema rejections, unmatched/missing criteria, failed requests, 429/503
rates, human-review rate, unresolved rate.

Efficiency: wall time, model latency, full-document uploads, targeted requests, cache
reuse (cached input tokens on escalation rows).

Statistics: item-level paired bootstrap (2,000 resamples, seed 20261103) for criterion
F1 and paper-total error; per-item A→H transitions; explicit statement that one paper
supports no significance claim and that any gain driven by 1–2 items is not generalisable.

## 6. Deliverables and non-goals

Deliverables live under `benchmark/experimental/` and never rewrite
`benchmark/results/raw/`, `benchmark/results/api_usage.jsonl`, the C5/C6 runs, the Q30
live escalation, the 59 probes or the frozen reports.

Non-goals: MathChecker V5 changes, Classroom submission, grade publication, commits,
pushes, merges, threshold tuning after seeing H's accuracy.

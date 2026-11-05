# Final A/B/C benchmark — Ch2 L3

Paper: **ch2-l3-final-01** · 2026-11-05

> **Status: PARTIAL.** The requested design was two complete attempts per strategy
> (A1, B1, C1, A2, B2, C2). Four attempts were started (A1, B1, C1, A2); only
> **A2 and C1 are complete**. B1 is incomplete (25/38 items), A1 failed with no
> output, B2 was stopped without a raw payload, and C2 never ran. This report is a
> partial-result comparison, **not** the planned six-attempt final.

> Reference: **76 / 87** (11 marks lost), treated as a human tolerance band
> **74–78** (centre 76). Exact equality to 76 is reported separately. The
> reference is user-ruled, not teacher-signed.

## 0. Run status and provider conditions

- **Executed:** A1, B1, C1, A2. **Started but no raw payload:** B2 (5 ledger rows).
  **Not executed:** C2.
- **Complete attempts:** A2 (38/38) and C1 (38/38). **Incomplete:** B1 (25/38).
  **Failed, not a measurement:** A1 (0/38).
- **Provider:** Gemini repeatedly returned HTTP 503 / `UNAVAILABLE`. Failed
  requests: A1 4/4, B1 39/49, C1 10/23, A2 2/3, B2 3/5.
- **Request cap:** 84 benchmark requests were recorded; retries count as
  requests. B2 was still running when the guard had already been exceeded, and
  the process was stopped to freeze these artifacts. C2 never ran.
- **Probes:** 26 probe requests (18 successful, 8 failed), excluded from
  benchmark totals.
- **Benchmark cost:** **$0.208361** total; $0.162165 allocated to the four
  attempts, $0.046196 in the unallocated B2 rows.

> Consequence: there is **no two-complete-attempt comparison** for any strategy
> and **no complete Strategy B measurement**. A1's 0/38 is a transport failure,
> not a marking result, and is excluded from every accuracy comparison below.

## 1. Attempts

| Strategy | Attempt | Status | Items | Score /87 | Band 74–78 | Criterion F1 | False awards | False deductions | Ledger requests (success/fail) | Cost USD |
|---|---|---|---|---|---|---|---|---|---|---|
| A | 1 | incomplete_request | 0/38 | — | — | — | — | — | 4 (0/4) | $0.000000 |
| A | 2 | complete | 38/38 | **67** | no | 0.8951 | 3 | 12 | 3 (1/2) | $0.045254 |
| B | 1 | incomplete_output | 25/38 | 41 | no | 0.6491 | 1 | 36 | 49 (10/39) | $0.035772 |
| B | 2 | no raw payload | — | — | — | — | — | — | 5 (2/3) | $0.046196 |
| C | 1 | complete | 38/38 | **78** | **yes** | 0.9542 | 4 | 2 | 23 (13/10) | $0.081140 |

Raw `request_count` (logical requests, before retry expansion): A2 1, B1 18,
C1 13. The ledger count is the API-consumption count and is used here.

## 2. Accuracy — complete attempts only

| Attempt | Score /87 | Error vs 76 | Coverage | Item exact | Criterion P | Criterion R | Criterion F1 | False awards | False deductions |
|---|---|---|---|---|---|---|---|---|---|
| **A2** | 67 | −9 | 38/38 | 27/38 (0.7105) | 0.9552 | 0.8421 | 0.8951 | 3 | 12 |
| **C1** | 78 | +2 | 38/38 | 33/38 (0.8684) | 0.9481 | 0.9605 | 0.9542 | 4 | 2 |
| B1 (not comparable) | 41 | −35 | 25/38 | 21/38 (0.5526) | 0.9737 | 0.4868 | 0.6491 | 1 | 36 |

B1's "item exact" is computed against all 38 scoreable items; it returned only
25. Its low false-award count (1) is an artefact of 13 missing items — missing
items are not false awards. The evaluator's B1 item-exact value is 0.5789 because
a missing zero-mark item (Q37b) is counted as exact by the evaluator; the direct
comparison is 21/38.

C1 is the **only complete attempt inside the 74–78 band**, at its upper edge
(78). That is not the same as criterion-level correctness: its +2 total is the
net of four over-awards and two under-awards.

## 3. Item-level findings

### A2 — 9 marks low

- **Over-awards (3):** Q30, Q31, Q34, each 3/3 vs the reference 2/3. These are
  the three items where the scheme says "Working required" and the user withheld
  A1 for a correct answer with no working. A2 applied "correct answer = full
  marks".
- **Under-awards (12 marks):** Q1a (0 vs 1; read `24` as `84`), Q2 (0 vs 1; read
  `10p` as `6p`), Q13 (1 vs 2), Q24 (0 vs 2), Q26 (1 vs 2; read `20x^3` as
  `20x^2` and `84x` as `84`), Q28 (1 vs 3), Q36 (1 vs 3; the answer is correct),
  Q37a (1 vs 3; the answer is correct).
- **Q24 is a self-contradiction:** the model's own reason says the student's
  `m^2 - 3m - 40` matches the scheme, then awards 0. This is a marking error,
  not a reference-policy disagreement.
- Net: 76 − 12 + 3 = **67**.

### C1 — 2 marks high, inside the band

- **Over-awards (4):** Q21 (2/3 vs 1/3), Q30, Q31, Q34 (3/3 vs 2/3 each). Q30,
  Q31 and Q34 are the same "Working required" policy disagreement seen in A2;
  Q21 is an over-award on a wrong final answer.
- **Under-award (2):** Q32 (1/3 vs 3/3). The model transcribed the student's
  `15x^3 + 10x^2 - 40x` as `15x^3 - 10x^2 - 40x`. The SymPy check then escalated
  Q32 from 2 to 1, increasing the error.
- Net: 76 − 2 + 4 = **78**. The band membership is partly offsetting: four
  over-awards and two under-awards, not four correct criterion decisions.

### B1 — not comparable

- **Blank extraction:** Q7, Q8, Q19 (0/2 each), marked as blank because the
  per-page transcription returned an empty answer.
- **Over-award:** Q21 (2 vs 1).
- **Missing:** Q26–Q37a and Q37b (13 items) because the run returned only 25
  items. These are coverage losses, not false awards.
- Net: 76 − 36 + 1 = **41**.

## 4. Escalation audit

| Run | Item | Before | After | Reference | Error before | Error after | Effect |
|---|---|---|---|---|---|---|---|
| C1 | Q32 | 2 | 1 | 3 | 1 | 2 | **harmful** (+1 error) |
| C1 | Q37b | 1 | 0 | 0 | 1 | 0 | correct (−1 error) |

- Net score: **79 → 78**; net absolute item error: **2 → 2**.
- The two changes offset each other. Without escalation C1 would have scored 79
  (outside the band, +3); with escalation it scores 78 (inside the band, +2).
  The escalation changed the **band outcome**, not aggregate criterion accuracy.
- Q32's escalation was triggered by a transcription sign error, not by a
  disagreement about the marking rule.
- C1 made 11 escalation requests (6 failed, 5 successful); 2 changed a mark.
  All requests are in the ledger with `purpose=escalation`; no silent retries.

## 5. API, cost and latency

| Strategy | Ledger requests | Success | Fail | Input tokens | Output tokens | Total tokens | Cost USD | Mean latency ms | p95 latency ms |
|---|---|---|---|---|---|---|---|---|---|
| A (A1+A2) | 7 | 1 | 6 | 31,818 | 5,704 | 37,522 | $0.045254 | 60,469 | 60,469 |
| B1 | 49 | 10 | 39 | 10,686 | 7,402 | 18,088 | $0.035772 | 10,637 | 23,486 |
| C1 | 23 | 13 | 10 | 43,375 | 17,132 | 60,507 | $0.081140 | 9,757 | 25,233 |
| B2 (unallocated) | 5 | 2 | 3 | 25,230 | 7,273 | 32,503 | $0.046196 | — | — |
| **Benchmark total** | **84** | **26** | **58** | **111,109** | **37,511** | **148,620** | **$0.208361** | — | — |

- Costs use provider-reported tokens × published list prices. Free-tier usage may
  be invoiced at $0; these are estimates, not invoices. Missing token values are
  not treated as zero.
- Latency is computed over successful rows. A has one successful request, so its
  p95 is that request (60.5 s, the A2 whole-paper call). B/C p95 values are
  indicative only (small n).
- **Cost per complete attempt:** A $0.045254; C $0.081140; B none. C is the only
  attempt with a cost per within-band paper ($0.081140).
- Probe requests: 26 (18 successful, 8 failed), 90 tokens, cost not priced;
  excluded from benchmark totals.

## 6. Transcription audit summary

| Attempt | Exact transcriptions | Flagged | Material misreads / losses |
|---|---|---|---|
| A2 | 31/38 | 4 different, 3 unknown | Q1a `24→84`; Q2 `10p→6p`; Q26 `x^3→x^2`, `84x→84`; Q37b `a^5b^2→9a^3b^2` |
| B1 | 18/38 | 3 blank, 4 unknown, 13 missing | Q7, Q8, Q19 blank; Q26–Q37a and Q37b never returned |
| C1 | 34/38 | 1 different, 3 unknown | Q32 `+10x^2→−10x^2` |

- Q13, Q21 and Q23 are messy/truncated in the scan; `unknown` in the audit
  reflects source ambiguity, not necessarily a model error. Their expected
  strings in `STUDENT_ANSWERS.json` include source annotations.
- The full per-item table is in `TRANSCRIPTION_AUDIT.md`.
- A1's 38 `missing_item` rows are a failed request, not transcription errors.

## 7. Answers to the decision questions

1. **Which reproduced the 11-mark deduction most accurately?** C1: 78, absolute
   error 2, the only complete attempt inside 74–78. A2: 67, absolute error 9.
   B has no complete attempt.
2. **Highest criterion F1:** C1 0.9542; A2 0.8951; B1 0.6491 (incomplete).
3. **Fewest false awards:** among complete attempts, A2 3 vs C1 4. B1's 1 is not
   comparable because 13 items were missing.
4. **Fewest false deductions:** C1 2 vs A2 12.
5. **Preserved the most student working:** C1, 34/38 exact transcriptions with
   one material sign error; A2 31/38 with four material misreads; B1 18/38 with
   three blanks and 13 missing items.
6. **Did C's SymPy/escalation improve the result?** Not cleanly. Q37b was
   corrected, Q32 was worsened; net score −1 into the band, net absolute item
   error unchanged (2 → 2). It changed the band outcome, not criterion accuracy.
7. **Did any escalation damage a correct mark?** Yes: Q32's error increased from
   1 to 2. Q37b's correction offset it in the total.
8. **Least API quota:** A used the fewest requests (7; 1 successful) but produced
   one complete attempt. C used 23 (13 successful) and produced one complete
   attempt. B used 49 (10 successful) and produced no complete attempt. Counting
   successful requests alone, A is lowest but least productive.
9. **Cost per paper:** A $0.045254, C $0.081140, B none (no complete attempt).
   Total benchmark cost $0.208361.
10. **Best balance:** C1 on accuracy and coverage among complete attempts,
    provisionally. A2 is cheaper but 9 marks low with 12 false deductions; B is
    not measurable. One paper and one complete attempt per strategy do not
    support a production recommendation.

## 8. Limitations

- **Not the requested design:** only A2 and C1 are complete; B1 is incomplete,
  A1 failed, B2/C2 were not run. The two-complete-attempt comparison does not
  exist for any strategy.
- Provider 503s consumed the request budget; retries are counted and no silent
  infinite retry occurred.
- One paper, one student, one sitting: no statistical significance and no
  general winner.
- The reference is user-ruled with a ±2 human tolerance band; item-level
  uncertainty remains on Q13, Q21, Q23, Q26, Q30, Q31 and Q34.
- C1's 78 is at the upper edge of the band, not an exact 76, and its total is
  the net of four over-awards and two under-awards.
- No production-readiness claim.

## 9. Artifacts

- Reference: `reference/GROUND_TRUTH.json`, `reference/STUDENT_ANSWERS.json`,
  `reference/paper-01.json`, `reference/GROUND_TRUTH_DRAFT.json`.
- Results: `results/STRATEGY_COMPARISON.json`, `results/API_USAGE.jsonl`,
  `results/raw/*.json`, `results/run.log`, `results/cost_estimate.json`,
  `results/key_pool_state.json`, `results/key_coverage_after_probe.json`.
- Audits: `reports/TRANSCRIPTION_AUDIT.md`, `reports/ESCALATION_AUDIT.md`,
  `reports/REFERENCE_RECONCILIATION.md`.
- Inputs and source: `inputs/*.png` (28 clean page images), `source/*.pdf`
  (untouched originals), `manifest.json`, `metadata.json`.
- Runner: `benchmark/code/run_final_test.py`, with
  `benchmark/code/final_metrics.py` and `benchmark/code/evaluate_final_test.py`.

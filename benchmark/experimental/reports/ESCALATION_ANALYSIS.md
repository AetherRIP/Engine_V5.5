# Escalation analysis — Strategy H

Live escalation evidence for paper-01. Every figure here comes from
`results/escalation_responses.json`, `results/h_usage.jsonl`,
`results/signal_analysis.json` and `results/item_transitions.json`.

## 1. Signals and what they fired on

| Code | Signal | Severity | Occurrences across the 3 policies × 2 base runs |
|---|---|---|---|
| S1_structure | criterion count ≠ printed maximum | 3 | 3 |
| S2_evidence_gap | marks with no transcribed answer | 3 | 0 |
| S3_aggregation | awarded ≠ number of criteria awarded | 3 | 3 |
| S4a/S4b/S4c | accuracy without method, full marks with an unawarded criterion, partial with all awarded | 2–3 | 0 |
| S5a_under_award | answer matches the printed answer, full marks not given | 2 | 6 |
| S5b_over_award | answer differs from the printed answer, full marks given | 2 | 4 |
| S6_model_flag | ambiguity / illegibility / scheme mismatch flag | 1 | 0 |
| S7_low_confidence | confidence < 0.80 | 1 | **0** |
| S8_broad_divergence | answer differs from the printed answer, any award | 1 | 10 |

The counts are signal occurrences, not unique items: the same item is counted again in
each policy and base run that selects or suppresses it.

## 2. Selection per base run

| Base | H-low | H-medium | H-high |
|---|---|---|---|
| A2 (77/87) | 26 | 26, 36 | 26, 36, 23, 30, 31 |
| A3 (72/87) | 28 | 28, 21, 32, 36 | 28, 21, 32, 36, 23, 26, 30, 31 |

Union of items that needed a live response: **8** (`21, 23, 26, 28, 30, 31, 32, 36`).
No policy hit its cap; no candidate was suppressed by the cap on this paper.

Selection is deterministic: signal severity first, then the paper's printed item order.
The ground-truth marks are not read when selecting — `signals.py` and `evidence.py` expose
only the printed scheme's prompt, marks and criterion text.

## 3. Confidence calibration (why S7 is not used in low/medium)

| Measure | Value |
|---|---|
| Observations (A2 + A3 items) | 76 |
| Distinct confidence values | 0.9, 0.95, 1.0 |
| Brier score | 0.1292 |
| Threshold used by H-high | 0.80 |
| Times S7 actually fired | 0 |

A's self-reported confidence is saturated: the minimum is 0.9, so an 0.80 threshold can
never fire. The values do not order correct from incorrect items in this sample. This is
why S7 is excluded from H-low and H-medium and appears in H-high only as a documented
negative control. H-high's real policy is S1 + S3 + S5a + S5b + S8.

## 4. Live escalation requests

All requests used one student page and one scheme page; no document was re-uploaded.

| Item | Selected by | Awarded / max | Criteria awarded | Input | Output | Cost USD | Latency |
|---|---|---|---|---|---|---|---|
| 21 | h-medium@a3, h-high@a3 | 2 / 2 | M1, A1 | 2,589 | 302 | 0.00307425 | 4,371 ms |
| 23 | h-high@a2, h-high@a3 | 3 / 3 | M1, M1dep, A1 | 2,592 | 404 | 0.00345900 | 3,526 ms |
| 26 | h-low@a2, h-medium@a2, h-high@a2, h-high@a3 | 2 / 3 | M1_1, M1_2; A1 denied | 2,594 | 436 | 0.00358050 | 3,575 ms |
| 28 | h-low@a3, h-medium@a3, h-high@a3 | 3 / 3 | M1, M1, A1 | 2,592 | 370 | 0.00333150 | 3,901 ms |
| 30 | h-high@a2, h-high@a3 | 2 / 3 | M1_1, M1_2; A1 denied | 2,592 | 435 | 0.00357525 | 3,838 ms |
| 31 | h-high@a2, h-high@a3 | **1 / 3** | M1 only; M1ft and A1 denied | 2,591 | 277 | 0.00298200 | 3,004 ms |
| 32 | h-medium@a3, h-high@a3 | 3 / 3 | M1_1, M1_2, A1 | 2,591 | 380 | 0.00336825 | 3,511 ms |
| 36 | h-medium@a2, h-high@a2, h-medium@a3, h-high@a3 | **1 / 3** | M1 only; M1ft and A1 denied | 2,593 | 428 | 0.00354975 | 3,596 ms |

Totals: 8 unique items, 13 attributed uses, **9 live rows** (one 503 retry),
20,734 input / 3,032 output tokens, **USD 0.0269205 actual spend**, mean latency 3,682.8 ms.
Per-item cost is $0.00298–$0.00358, i.e. about 6–8% of a whole-paper A request.

## 5. Outcomes against the candidate reference

| Item | Ref | A2 | A3 | Escalated | Effect |
|---|---|---|---|---|---|
| 21 | 2 | 2 | 1 | 2 | fixed A3 (+1) |
| 23 | 3 | 0 | 0 | 3 | fixed both (+6 across runs) |
| 26 | 2 | 2 | 1 | 2 | fixed A3 (+1); A2 unchanged |
| 28 | 3 | 3 | 1 | 3 | fixed A3 (+2) |
| 30 | 2 | 1 | 1 | 2 | fixed both (+2) |
| 31 | 2 | 2 | 2 | 1 | **aged badly** (−1 each) |
| 32 | 3 | 3 | 2 | 3 | fixed A3 (+1) |
| 36 | 2 | 3 | 3 | 1 | **over-corrected** (error +1 → −1) |

Across 13 escalated item-instances: 8 improved (+13 marks), 1 unchanged, 4 degraded
(−6 marks), net **+7 marks**. Q23 alone is +6 of the net.

## 6. Failure modes worth keeping

1. **A full-marks item can be damaged.** Q31 was 2/2 in both A runs and 2/2 in both C
   runs; the two-page escalation awarded 1/3. Escalating a full-marks item is the highest
   risk action the policy can take, and S8 triggers it whenever the transcribed answer
   differs from the printed answer — which is always true when the student is wrong but
   the marking is right.
2. **A false award can flip instead of being fixed.** Q36 (A 3/3, reference 2/3) became
   1/3. The absolute error stayed at one mark, so total-mark error does not reveal this
   case; only criterion-level scoring does.
3. **Schema validation cannot catch a wrong mark.** All 8 responses passed the gate. The
   gate is a correctness-of-form check (single id, cap unchanged, coherent criteria,
   reasoned awards, evidence present), not a correctness-of-marking check. Zero live
   rejections is therefore a reliability *warning*, not a reliability result.
4. **C's pipeline does better on these two items.** C5/C6 scored Q31 and Q36 at 2/2. H's
   narrower context, or the different prompt, appears to read the scheme's
   "allow one error" clause more strictly. H is not a drop-in substitute for C item by item.
5. **One capacity failure, handled correctly.** `escalate-31` returned HTTP 503
   `UNAVAILABLE` on attempt 1 (KEY_10) and succeeded on attempt 2 (KEY_11). No 429
   occurred. The run was not retried beyond the configured bound, and no whole-document
   request was issued during the capacity blip.

## 7. Request hygiene

- **No duplicate escalations:** 8 unique items, 13 attributed uses, 9 live rows. The
  registry reuses a valid response across policies and base runs (`h_high@a2` and
  `h_high@a3` share the Q23 response).
- **No prompt anchoring:** A's previous mark is never in the escalation prompt, so a reused
  response is the same measurement, not a revision.
- **No cap change:** every final `max_marks` is injected from the reference; the response's
  own `max_marks` must match or the response is rejected.
- **Original preserved:** every escalated item keeps `a_original` (awarded, criteria,
  reason, confidence, flags, transcribed answer) inside the final item, and the run keeps
  the full `a_original` set and `escalation_audit` entry for the item.
- **No silent overwrite:** the decision, the request row, the validation verdict and the
  before/after marks are all in `results/h_runs.json` per run.

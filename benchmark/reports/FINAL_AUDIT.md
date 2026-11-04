# Final benchmark audit and freeze — paper-01

**Status: FROZEN AUDIT COMPLETE.** No new provider requests were made during this audit.
Raw A/B/C files, C5/C6, failed attempts, the live escalation and the request ledger were
read but not rewritten. The reference remains a candidate, NOT teacher-certified.

## 1. Why C6 reports 82

The apparent **82/80** is a denominator-label ambiguity, not an impossible score and not
an aggregation defect.

- Scoreable maximum: **87 marks** across 38 items.
- Candidate reference total: **80/87**.
- C6 `paper_score_awarded`: **82/87**.
- C6 returned 38 unique scoreable items; no duplicate ids, no unmatched ids, no
  item award above its per-item maximum, and no maximum-mark field mismatch.
- The 82 is the direct sum of the raw item awards. It is two marks above the
  candidate reference because C6 over-awarded **Q26** (3 vs reference 2) and
  **Q30** (3 vs reference 2), each by one mark.
- Criterion awards are not added to the paper total; the total is the sum of item
  `awarded` values. C6 has 87 criterion records for 87 available marks; the
  criterion list is not an extra source of paper marks.
- The benchmark's exact-paper rule compares 82 with the reference **80**, so C6
  is not strictly correct even though 82 is a valid awarded score out of 87.

Independent recalculation:

```text
sum(C6 item awarded) = 82
sum(C6 item max_marks) = 87
reference candidate total = 80
C6 disagreements: Q26 3 vs 2, Q30 3 vs 2
other 36 items: reference marks
=> 80 + 1 + 1 = 82
```

The raw item list, per-item caps and duplicate checks are preserved in
`results/raw/c_run6.json`. The root cause of the confusing presentation was derived
report wording that said "scores 78 / 82 against a reference of 80" without stating
the scoreable maximum. The reports now state **out of 87, candidate reference 80** and
contain a C6 audit section.

## 2. Corrections made to derived reports

Supported corrections only; no historical measurement or scoring rule was changed:

- Added `paper_max_marks` (87) and `paper_reference_marks` (80) to `comparison.json`
  and to each strategy entry.
- Changed report/recommendation wording from "against a reference of 80" to
  "out of 87 against the candidate reference of 80."
- Added a **C6 score audit** section to `BENCHMARK_REPORT.md`.
- Updated the README and methodology table headers to show `/87`.
- No raw C5/C6, A/B, failed attempts or ledger rows were rewritten.

## 3. Final measured comparison

All accuracy figures are provisional against the candidate reference.

| Strategy | Selected runs | Paper scores /87 | Candidate reference | Criterion F1 | Requests | Cost USD |
|---|---|---:|---:|---:|---:|---:|
| A | A2, A3 | 77, 72 | 80 | 0.9479 | 2 | 0.070251 |
| B | B1, B2 | 74, 74 | 80 | 0.9610 | 33 | 0.191967 |
| C | C5, C6 | 78, 82 | 80 | 0.9875 | 23 | 0.151344 |

- **C6:** 82/87, two over-awards (Q26/Q30), not exact.
- **C5:** 78/87, two under-awards (Q26/Q30).
- No strategy returned the exact candidate reference with full coverage in both runs.
- A's A2/A3 selected pair covers all 38 items. B's selected pair covers all 38 but
  Q7/Q8/Q19 have blank extracted answers. C5/C6 cover all 38.
- The live Q30 addendum used one student page and one scheme page, changed C5 Q30
  from 1 to 2, and cost USD 0.0037725. It is separate from the selected C5/C6 pair
  and is **not** evidence of whole-paper reliability.

## 4. Recommendation audit

The reports distinguish:

- **Measured accuracy:** provisional paper/item/criterion agreement against a
  candidate, not teacher-certified, reference.
- **Criterion-level F1:** reported separately from exact paper scores; C's 0.9875
  does not make its selected pair exact.
- **Live escalation capability:** exactly one targeted live Q30 response is
  recorded with a real ledger row and a changed mark. This proves the branch can
  fire on one item; it does not prove full-document escalation reliability.
- **Whole-document reliability:** A2/A3, B1/B2 and C5/C6 are measured complete
  runs; C6's over-awards and B's extraction losses remain failures. The single live
  addendum does not upgrade C5/C6 into a new full run.
- **Provider availability:** full-document C9–C13 attempts were blocked by HTTP 503
  `UNAVAILABLE`/timeouts; 15 healthy keys had available quota. This is a capacity
  limitation, not evidence for or against whole-document marking quality.
- **Throughput:** concurrency was 1; measured scheduler wait is reported separately
  from historical next-use intervals; no rotation speed-up is claimed.
- **Cost:** list-price token estimates are reported per selected strategy and for
  the live addendum; free-tier invoicing may differ.

The recommendation remains conditional, not a production validation.

## 5. Remaining limitations

- One paper, one student, one sitting; no statistical significance.
- The reference is candidate-only and has not been teacher-certified.
- Q12 and Q16(d) remain documented exclusions (4 marks); 38 items / 87 marks are
  scored.
- C's selected runs have no live escalation; only the separate single-item Q30
  addendum is live.
- Full-document C reruns C9–C13 remain provider-blocked; no fresh complete C pair
  was obtained.
- B's Q7/Q8/Q19 blank extraction loss remains; the targeted re-read path was not
  exercised by the selected B pair.
- Throughput, caching and quota conditions are confounded; no causal speed-up or
  quota-expansion claim is made.
- The benchmark is **not ready to serve as the sole basis for a production
  architecture decision**. It supports a provisional architecture hypothesis and
  a decision to run a teacher-certified, multi-paper validation with a complete
  live C run.

## 6. Freeze

`results/frozen_snapshot.json` records SHA-256 hashes for source code, raw A/B/C
runs, C5/C6, the live escalation, failed attempts, the request ledger, reference,
samples, derived results and reports. The 28 anonymised sample hashes are verified
against `dataset_manifest.json`; all 28 existing benchmark tests pass.

No commit, push, pull request or merge was performed.

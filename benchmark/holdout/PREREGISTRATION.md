# Pre-registered holdout experiment

**Status: FROZEN — NOT EXECUTED.** No holdout paper exists and no holdout provider request
has been made. This document fixes the configurations, metrics, acceptance criteria and
analysis before any holdout answer is seen, so that a future run cannot be tuned.

Nothing here changes the frozen `paper-01` experiment. That experiment is complete and its
thresholds are not re-tuned against this plan.

## 1. Frozen configurations

The Strategy H implementation is frozen at the `paper-01` version. Digests are recorded in
`holdout_manifest.json` under `frozen_config.files`; a mismatch voids the run.

| Configuration | Definition | Status |
|---|---|---|
| **A-only** | Strategy A whole-paper request, unchanged (`benchmark.code.strategies.run_a`) | frozen |
| **H-low** | A + S1, S2, S3, cap 3 | frozen, unchanged |
| **H-medium** | A + S1, S2, S3, S4a, S4b, S4c, S5a, S5b, S6, cap 6 | frozen, unchanged |
| **H-high** | H-medium + S7 (confidence < 0.80) + S8, cap 8 | frozen, unchanged |
| **C-only** | Strategy C pipeline, unchanged | frozen; run only if provider availability permits, and reported as "not run" otherwise |

No threshold, cap, model or prompt may change between papers. Model substitutions are
recorded per run and make the affected comparison descriptive only.

## 2. Guarded variants (post-processing, pre-registered)

The single-paper run showed that a well-formed escalation can still damage a correct mark.
The guards below are applied **offline to the same stored escalation responses**, so raw and
guarded results are directly comparable and no extra provider spend is needed. They are not
changes to the marking pipeline.

| Guard | Rule | Effect |
|---|---|---|
| **G1 — no full-mark downgrade** | If A awarded `max_marks` and the escalation would award less, keep A and send the item to human review | Directly prevents the Q31 failure class |
| **G2 — change needs confirmation** | Any change is applied only if a second independent escalation (fresh request, different key, same evidence) agrees exactly; otherwise keep A and review | Halves escalation calls for changed items; turns single-verdict errors into review cases |
| **G3 — magnitude guard** | A change of ≥ 2 marks in one step is applied only with G2 confirmation; otherwise review | Prevents the Q36 class (3 → 1) |

Reported variants: `H-high`, `H-high+G1`, `H-high+G1+G3`, `H-high+G1+G2+G3` (same for
medium if it changes anything). Cost of a guard = extra confirmation requests + review rate.

Pre-registered expectation, stated before the run: G1 must reduce harmful changes to zero
for full-mark items; G2/G3 must reduce incorrect changes at the cost of more review cases.
If a guard does not reduce incorrect changes, it is reported as ineffective and is not
recommended, regardless of its effect on aggregate F1.

## 3. Metrics (all mandatory)

Definitions are fixed here; no metric may be redefined after seeing results.

| Group | Metric |
|---|---|
| Accuracy | criterion precision, recall, F1 (micro over criteria and macro over papers); exact item agreement; exact paper-total agreement; absolute total-mark error; false awards; false deductions (lost marks) |
| Escalation | criteria escalated / total; submissions escalated; escalations that changed a mark; **incorrect escalations** (changed a mark and increased that item's absolute error); **harmful escalations** (changed a previously correct mark to incorrect); escalations that removed a full-marks award; escalations that added an unsupported mark |
| Safety | review rate; unresolved disagreements; audit completeness (changed marks with `a_original`, request row and verdict recorded); schema-valid responses; provider failures |
| Cost | total USD; USD per paper; USD per criterion; USD per 1,000 criteria; incremental escalation USD; requests per paper; full-document uploads per paper |
| Efficiency | wall time; mean/p95 model latency; cache reuse |
| Robustness | results by paper, by topic, by difficulty band; disagreement rate with reference by paper |

## 4. Acceptance criteria (pre-registered)

Primary endpoint: **per-paper paired difference in absolute total-mark error, H-high − A**,
with papers as the resampling unit.

Integration requires **all** of:

1. **Primary:** mean paired Δ ≤ −1.0 mark/paper (H-high better) and the 95% paper-level
   bootstrap CI upper bound < 0.
2. **Criterion agreement:** H-high criterion F1 > A's on ≥ 7 of 10 papers.
3. **Safety gate 1:** zero unreviewed full-mark downgrades.
4. **Safety gate 2:** zero accepted escalations without supporting evidence (validator
   enforced; any occurrence is a defect, not a metric).
5. **Safety gate 3:** audit completeness 100% — every changed mark retains A's original
   result, the request row, and the validation verdict.
6. **Safety gate 4:** incorrect escalations ≤ 10% of changed marks, and harmful escalations
   ≤ 2% of escalated items.
7. **Harm ceiling:** no paper worsens by more than 2 marks net.
8. **Cost:** cost/submission ≤ 80% of C-only on the same papers and ≤ 1.6× A-only.
9. **Reliability:** schema-valid ≥ 95%; provider failure rate ≤ 10%; unresolved escalation
   rate ≤ 5%; every unresolved case is reported, never silently dropped.

Secondary, reported but not gating: C-only non-inferiority (H-high within 0.01 F1 of C-only
at lower cost), H-medium/H-low comparisons, guarded-variant results, per-topic descriptive
results.

If criterion 1 passes but any safety gate fails → **do not integrate**, report the failure.
If criterion 1 fails → **do not integrate**, regardless of F1 or cost.

## 5. Statistical analysis

- **Unit of generalisation: the paper.** Primary CI is a bootstrap over the 10 papers
  (2,000 resamples, seed 20261103). Item-level bootstrap within a paper is descriptive only
  and must be labelled as such.
- Paired comparisons are per paper, not per run; a paper's two runs (if repeated) are
  averaged before the paper-level analysis, and run-to-run variation is reported separately.
- With 10 papers, δ = 1 mark is underpowered. No significance claim is made for a smaller
  effect; the report states the observed effect and its interval.
- Multiplicity: one primary endpoint. Secondary endpoints are reported with intervals and
  no "significant" language.
- Missing data: provider failures are counted and reported; excluded items leave the
  denominator and are listed; nothing is imputed.
- Subgroup analyses (topic, difficulty) are descriptive, pre-declared, and never used to
  select thresholds.

## 6. Correctness and safety investigation (Phase 4 questions)

The report must contain, per paper and in aggregate:

1. Escalations that reduced a previously correct mark, with the A award, the C award and
   the reference.
2. Escalations that awarded marks without supporting evidence (target: zero).
3. Full-mark answers downgraded by C (target: zero unreviewed).
4. Every marker disagreement that touches an item where H changed a mark.
5. Mathematically plausible but incorrect reasoning in C's escalation (manual audit of all
   changed items, not a sample).
6. Invalid or incomplete evidence accepted by the gate (target: zero).
7. Items where schema validation passed and the award is still wrong — counted as
   `incorrect escalation`, and the reason classified (rule misread, transcription error,
   arithmetic, scheme ambiguity).

Safety is judged at the item level, not netted out across the paper.

## 7. Locking and stopping rules

- Before scoring, `python -m benchmark.holdout.manifest --check-code` must pass: the code
  digests, the paper hashes and the certification artifacts must match the manifest.
- Any change to signals, caps, thresholds, prompts, guards or scoring after the first
  holdout request **voids the run**. A new run requires a new manifest and a new
  pre-registration.
- If fewer than 8 papers are certified: run descriptively, no pass/fail decision, state
  the limitation.
- If the provider is unavailable: record failed requests and their actual cost, stop after
  the bounded retry policy, and report the configuration as blocked rather than partially
  scored.
- If certification is incomplete for any paper: that paper is excluded entirely; it is not
  "provisionally" scored.

## 8. Outputs

New files only, under `benchmark/holdout/results/` and `benchmark/holdout/reports/`:

```
results/holdout_manifest_used.json     manifest snapshot used for the run
results/holdout_usage.jsonl            append-only request ledger for the holdout
results/holdout_runs/<paper>.json      raw per-paper results for every configuration
results/holdout_comparison.json        accuracy, cost, safety, per-paper table
results/holdout_guards.json            raw vs G1/G2/G3 comparisons
reports/HOLDOUT_REPORT.md              full report
reports/HOLDOUT_RECOMMENDATION.md      decision against §4
```

The `paper-01` artifacts, `benchmark/results/`, and the frozen reports are never modified.

## 9. Non-goals

Production V5 changes, grade publication, Classroom submission, commits/pushes/merges, and
any claim of generalisation from fewer than 8 certified papers.

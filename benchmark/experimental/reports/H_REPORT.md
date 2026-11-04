# Strategy H (A + selective C) — experimental report

Paper **paper-01** · one student, one sitting, 38 scoreable items / 87 marks
· candidate reference **80/87, not teacher-certified** · generated 2026-11-03.

> **Status.** Accuracy is provisional. The reference was derived from the printed scheme
> and an independent re-solve; no teacher has certified it. One paper cannot support a
> significance claim or a general winner.

## 1. Question

Does running Strategy A by default and escalating only criteria with a *stated,
checkable* reason to a targeted Strategy C re-mark give a better accuracy-to-cost ratio
than A alone or C alone?

## 2. What was actually measured

| Stage | Evidence | Live? |
|---|---|---|
| A-only | preserved runs A2, A3 (whole-paper, `gemini-3.6-flash`) | live, previously recorded |
| C-only | preserved runs C5, C6 (document + scheme + Lite batches) | live, previously recorded |
| H base | A2 and A3 re-read from `results/raw/a_run{2,3}.json` | **replayed** live response, not re-requested |
| H escalation | 8 live requests, one per selected item | **live** |
| H scoring | unchanged `benchmark.code.evaluator`, same reference and exclusions | offline derivation |

H is therefore *live re-marking on a live-preserved A base*. It is not an independent
second A sample, and it is not an offline replay of escalation: all 8 escalation marks
come from real provider responses recorded in `results/h_usage.jsonl`.

No historical file was modified. All 91 artifacts hashed by `results/frozen_snapshot.json`
still match, no probe was spent, and the existing 59 probes remain untouched.

## 3. Headline comparison

All configurations are scored on the same 38 items, the same 87 marks, the same two
exclusions (Q12 source mismatch, Q16(d) not printed) and the same rules.

| Configuration | Runs | Paper /87 | Mean | Item exact | Crit P | Crit R | **Crit F1** | FA | FD | Requests | Cost USD | Cost / submission |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **A-only** | 2 | 77, 72 | 74.5 | 86.85% | 0.9865 | 0.9125 | **0.9479** | 2 | 13 | 2 | 0.070251 | $0.035126 |
| **C-only** | 2 | 78, 82 | 80.0 | 94.74% | 0.9878 | 0.9875 | **0.9875** | 2 | 2 | 23 | 0.151344 | $0.075672 |
| **H-low** | 2 | 77, 74 | 75.5 | 88.16% | 0.9868 | 0.9312 | **0.9582** | 2 | 11 | 4 | 0.077163 | $0.038582 |
| **H-medium** | 2 | 75, 74 | 74.5 | 90.79% | 1.0000 | 0.9313 | **0.9644** | 0 | 11 | 8 | 0.090705 | $0.045353 |
| **H-high** | 2 | 78, 78 | 78.0 | 94.74% | 1.0000 | 0.9750 | **0.9873** | 0 | 4 | 15 | 0.114318 | $0.057159 |

FA = false awards, FD = false deductions against the candidate reference. No configuration
reached 80/87 in both runs; only C reached it at all (C6, by over-awarding Q26 and Q30).

### Change relative to A-only

| Configuration | ΔF1 (abs) | ΔF1 (rel) | Δ mean marks | Δ cost / submission | Δ cost % | Δ requests |
|---|---|---|---|---|---|---|
| H-low | +0.0103 | +1.09% | +1.0 | +$0.003456 | +9.8% | +1 |
| H-medium | +0.0165 | +1.74% | 0.0 | +$0.010227 | +29.1% | +3 |
| H-high | +0.0394 | +4.16% | +3.5 | +$0.022034 | +62.7% | +6.5 |
| C-only | +0.0396 | +4.18% | +5.5 | +$0.040547 | +115.4% | +10.5 |

H-high reaches C's criterion F1 (0.9873 vs 0.9875, Δ0.0002) at **75.5% of C's cost** and
**65% of C's requests**, and it is the only configuration with zero false awards and fewer
than five false deductions. It still trails C on paper totals (mean 78 vs 80), because C's
two extra marks are over-awards that happen to land above the reference.

## 4. Accuracy detail

### Per run

| Config | Run | Score | Item exact | F1 | FA | FD | Unresolved |
|---|---|---|---|---|---|---|---|
| A-only | 2 | 77 | 92.11% | 0.9615 | 1 | 4 | 0 |
| A-only | 3 | 72 | 81.58% | 0.9342 | 1 | 9 | 0 |
| C-only | 5 | 78 | 94.74% | 0.9873 | 0 | 2 | 0 |
| C-only | 6 | 82 | 94.74% | 0.9877 | 2 | 0 | 0 |
| H-low | 2 | 77 | 92.11% | 0.9682 | 1 | 4 | 0 |
| H-low | 3 | 74 | 84.21% | 0.9481 | 1 | 7 | 0 |
| H-medium | 2 | 75 | 92.11% | 0.9677 | 0 | 5 | 0 |
| H-medium | 3 | 74 | 89.47% | 0.9610 | 0 | 6 | 0 |
| H-high | 2 | 78 | 94.74% | 0.9873 | 0 | 2 | 0 |
| H-high | 3 | 78 | 94.74% | 0.9873 | 0 | 2 | 0 |

### Difficult / ambiguous subset (8 items: 14, 21, 23, 26, 28, 30, 32, 36)

| Config | Item exact (runs) | Criterion F1 (runs) |
|---|---|---|
| A-only | 62.5%, 12.5% | 0.8235, 0.6667 |
| C-only | 75.0%, 75.0% | 0.9444, 0.9500 |
| H-low | 62.5%, 25.0% | 0.8571, 0.7500 |
| H-medium | 62.5%, 50.0% | 0.8485, 0.8125 |
| H-high | 87.5%, 87.5% | 0.9730, 0.9730 |

Escalation helps most exactly where A is weakest. That is the intended effect of the
signal design, but it also means the aggregate gain is concentrated in this small subset
(§6).

## 5. Cost

| Config | Total USD | Per submission | Per criterion (87/run) | Escalation share | Escalation USD | Crit escalated | Submissions escalated |
|---|---|---|---|---|---|---|---|
| A-only | 0.070251 | $0.035126 | $0.000404 | 0 | 0 | 0 / 76 | 0% |
| C-only | 0.151344 | $0.075672 | $0.000870 | included | 0 (none fired) | 0 / 76 | 0% |
| H-low | 0.077163 | $0.038582 | $0.000444 | 9.0% | 0.006912 | 2 / 76 (2.6%) | 100% |
| H-medium | 0.090705 | $0.045353 | $0.000521 | 22.5% | 0.020454 | 6 / 76 (7.9%) | 100% |
| H-high | 0.114318 | $0.057159 | $0.000657 | 38.5% | 0.044067 | 13 / 76 (17.1%) | 100% |

- **Actual live spend for the whole experiment: $0.0269205** over 9 requests (8 valid + one
  HTTP 503 that was retried and then succeeded). The per-submission figures above are
  attributions: the same escalation response serves both base runs, so one live row is
  counted once per run that uses it. Both numbers come from the same ledger rows.
- Escalation is cheap per request: mean 2,592 input / 337 output tokens, $0.0034 per item.
- H inherits A's cache confound: A2 cost $0.024495 (93.7% cached) while A3 cost $0.045756
  (no cache reported). H's per-submission cost therefore differs by run for the same
  policy; the comparison against A is paired per base run, so the confound is not removed,
  only held constant.

### Cost per unit of improvement

| Config | Extra cost / submission | Extra marks (mean) | **Cost per extra mark** | Extra F1 | **Cost per +0.01 F1** |
|---|---|---|---|---|---|
| H-low | $0.003456 | +1.0 | **$0.00346** | +0.0103 | **$0.00336** |
| H-medium | $0.010227 | 0.0 | n/a (no gain) | +0.0165 | $0.00620 |
| H-high | $0.022034 | +3.5 | **$0.00630** | +0.0394 | **$0.00559** |
| C-only | $0.040547 | +5.5 | $0.00737 | +0.0396 | $0.01024 |

H-high buys criterion accuracy more cheaply than C and more cheaply than H-medium.
H-low is the cheapest configuration that improves anything at all.

## 6. Statistical analysis

- **Item-level bootstrap**, 2,000 resamples, seed 20261103, resampling the 38 items.
  Criterion F1 95% intervals:

  | Config | Run 2 | Run 3 |
  |---|---|---|
  | A-only | [0.9079, 0.9938] | [0.8742, 0.9787] |
  | H-low | [0.9172, 1.0000] | [0.8906, 0.9867] |
  | H-medium | [0.9161, 1.0000] | [0.9059, 0.9937] |
  | H-high | [0.9669, 1.0000] | [0.9669, 1.0000] |
  | C-only | [0.9673, 1.0000] | [0.9693, 1.0000] |

- **Paired bootstrap of ΔF1 (H − A, same base run)**:

  | Pair | ΔF1 | 95% CI | share of resamples with Δ>0 |
  |---|---|---|---|
  | H-low vs A2 | +0.0066 | [0.0000, 0.0213] | 63.7% |
  | H-low vs A3 | +0.0138 | [0.0000, 0.0444] | 63.4% |
  | H-medium vs A2 | +0.0062 | [−0.0015, 0.0214] | 63.6% |
  | H-medium vs A3 | +0.0268 | [0.0000, 0.0631] | 96.3% |
  | H-high vs A2 | +0.0258 | [−0.0092, 0.0767] | 84.8% |
  | H-high vs A3 | +0.0531 | [0.0063, 0.1168] | 98.3% |

  The A2 comparisons include zero. Even the strongest H-high/A3 interval is an
  **item-level** interval on one paper; it does not estimate performance on another paper.

- **The gain is driven by a handful of items.** H-high changed 13 item-instances:
  8 improved, 4 got worse, 1 unchanged, net +7 marks across two runs. Q23 alone accounts
  for +6 of those marks (A scored 0/3 twice; the escalation scored 3/3 twice). Remove Q23
  and H-high's mean gain falls from +3.5 to +0.5 marks.

- **H is not monotonically better with more escalation.** H-medium (6 escalations/run)
  scored *lower* overall than H-low (1/run) because it escalated Q36 and converted a
  false award into a false deduction without touching Q23. H-high only wins because its
  broad-divergence signal happens to include Q23.

- **Per document.** Run 3 is the harder A digitisation (72/87). Every H policy improves it
  (+2, +2, +6). Run 2 (77/87) improves only under H-high (+1); H-medium makes it worse
  (−2). A configuration that is safe on one run is not automatically safe on the other.

## 7. Reliability

| Measure | Result |
|---|---|
| Live escalation requests | 9 |
| Valid, schema-conforming responses | 8 (88.9%) |
| Schema validation failures | 0 |
| Missing / unmatched criteria | 0 |
| Duplicate escalation requests | 0 (8 unique items for 13 attributed uses) |
| HTTP 429 | 0 |
| HTTP 503 | 1 (`escalate-31`, first attempt; retried once and succeeded) |
| Failed provider requests | 1 |
| Human-review fallbacks | 0 live (validation gate never rejected a live response) |
| Unresolved escalation | 0 |
| Full-document uploads | 0 new (2 replayed A requests) |
| Targeted requests | 9 |
| Cache reuse | 0% (provider reported no cached tokens for two-page requests) |
| Mean latency | 3,682.8 ms (max 4,371 ms) |
| Total escalation wall time | 33.1 s |

**The important reliability result is negative:** the gate accepted every live response,
including the two that disagreed with the reference (Q31, Q36). Schema validation proves
a response is well formed and internally coherent; it cannot prove it is right. Any
production design needs a second, independent check — not just stricter validation.

## 8. What escalation actually fixed and broke

| Item | Ref | A2 | A3 | Escalation | H-low | H-medium | H-high | Verdict |
|---|---|---|---|---|---|---|---|---|
| 21 | 2 | 2 | 1 | 2 | 2 / 1 | 2 / 2 | 2 / 2 | fixed A3 |
| 23 | 3 | 0 | 0 | 3 | 0 / 0 | 0 / 0 | 3 / 3 | fixed both (largest gain) |
| 26 | 2 | 2 | 1 | 2 | 2 / 1 | 2 / 1 | 2 / 2 | fixed A3 under H-high only |
| 28 | 3 | 3 | 1 | 3 | 3 / 3 | 3 / 3 | 3 / 3 | fixed A3 |
| 30 | 2 | 1 | 1 | 2 | 1 / 1 | 1 / 1 | 2 / 2 | fixed both under H-high |
| 31 | 2 | 2 | 2 | **1** | 2 / 2 | 2 / 2 | **1 / 1** | **degraded** by H-high |
| 32 | 3 | 3 | 2 | 3 | 3 / 2 | 3 / 3 | 3 / 3 | fixed A3 under medium/high |
| 36 | 2 | 3 | 3 | **1** | 3 / 3 | **1 / 1** | **1 / 1** | **over-corrected** (error sign flipped) |

- The escalation reproduces C's *error mode* on Q31/Q36 rather than C's best behaviour:
  C5/C6 both scored those two items 2/2, while the two-page single-item re-mark read the
  "allow one error" style clause more harshly and awarded 1/3.
- Against a candidate reference, Q31/Q36 may themselves be arguable. The honest statement
  is "the escalation disagreed with the candidate reference", not "the escalation is
  definitely wrong". That ambiguity is exactly why a teacher-certified reference is
  required before a cost/accuracy decision.
- Full item-by-item evidence: `results/item_transitions.json`.

## 9. Threats to validity

1. **One paper, one student, 38 items.** No document-level generalisation, no significance.
2. **Candidate reference.** Every "improvement" and "degradation" is relative to marks no
   teacher has certified. Q31/Q36 and Q23 are the kinds of lines a teacher might dispute.
3. **H's base is replayed, not re-requested.** H is not an independent A sample; it also
   cannot establish that a fresh A run would produce the same signals.
4. **Cache confound.** A2 was 93.7% cached, A3 was not; H's cost inherits that split.
5. **Escalation model** is `gemini-3.6-flash`, the same model as A, because the configured
   strong model was quota-limited. The measured effect is "narrower context", not "stronger
   model". A true stronger model could behave differently in either direction.
6. **C-only comparison is a different pipeline**: C5/C6 had zero escalations, so the cost
   figures do not include any specialist spend. H's escalation cost is included.
7. **Signal selection is deterministic but not independent of A's own output quality.** A3
   had a structure failure (Q28) that made H-low fire; A2 had none on that item. Policy
   behaviour therefore varies with A's formatting as well as its marking.
8. **Tooling available at run time.** No Graphify graph and no installed skill was present
   in this workspace, so code relationships were read directly from the benchmark source.
   There is no git repository here, so the no-commit rule is satisfied by construction.

## 10. Answers

Detailed in `H_RECOMMENDATION.md`. In short: selective escalation **does** improve A's
criterion F1 on this paper at every tier, H-high matches C's F1 at 75.5% of its cost, the
cheapest improvement is H-low at +$0.0035 per submission, but the gain is concentrated in
a few items, one policy is worse than the cheapest one, two escalations disagreed with the
reference, and the evidence is nowhere near sufficient for V5 production.

## 11. Artifacts

```
benchmark/experimental/
  PLAN.md                            pre-registered design and frozen thresholds
  H_CONFIGURATION.md                 as-run configuration
  strategy_h/                        implementation (config, evidence, signals, runner, evaluate)
  run_experiment.py                  signals / live escalation / scoring driver
  results/signal_analysis.json       per-run signals and confidence calibration
  results/escalation_responses.json  raw live escalation responses + validation verdicts
  results/h_usage.jsonl              append-only experimental request ledger
  results/escalation_run.json        bounded-run status, retries, skips
  results/h_runs.json                per-run H payloads with the full audit trail
  results/h_comparison.json          accuracy, cost, subsets, bootstrap
  results/item_transitions.json      per-item truth / A / C / escalation / H
  results/paired_bootstrap.json      paired ΔF1 intervals
  reports/H_REPORT.md                this report
  reports/ESCALATION_ANALYSIS.md     signal and escalation audit
  reports/H_RECOMMENDATION.md        decision
  tests/test_strategy_h.py           15 offline tests
```

Reproduce scoring without any provider call: `--signals` then `--evaluate`
(`H_CONFIGURATION.md`). Scoring is deterministic; only `--escalate` spends quota.

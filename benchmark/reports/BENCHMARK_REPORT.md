# Correction strategy benchmark — measured report

Paper: **paper-01** · generated 2026-11-03T20:50:14+00:00

> **Ground-truth status: candidate, NOT teacher-certified.** The reference marks were
> derived from the printed scheme and an independent re-solve. Accuracy below is
> provisional and must not be presented as a certified marking accuracy.

## 1. Dataset

- 7 anonymised student pages, 21 mark-scheme pages.
- 40 items in the reference; 38 scoreable (87 marks); 2 excluded for source inconsistency.
- Candidate total: 80 / 87 (91.95%).
- Excluded: 12 (excluded_source_mismatch); 16d (excluded_not_printed).

## 2. Models and configuration

| Role | Model |
|---|---|
| primary | `gemini-3.6-flash` |
| lite | `gemini-3.5-flash-lite` |
| strong | `gemini-3.6-flash` |
- primary: gemini-3.6-flash verified on KEY_10
- lite: gemini-3.1-flash-lite not verified on the first 3 healthy key(s)
- lite: gemini-3.5-flash-lite verified on KEY_10
- strong: gemini-3.1-pro-preview not verified on the first 3 healthy key(s)
- strong: gemini-3.6-flash verified on KEY_10

Generation settings: temperature 0, top-p 0.95, thinking budget 0 (per-model
override where the model rejects zero), identical response schema; two selected
runs per strategy. The original six were interleaved A1→B1→C1→A2→B2→C2; A3 was
appended as a recorded complete reattempt.

## 3. Accuracy (provisional)

| Strategy | Coverage | Item exact | Paper score /87 (exact / within 1) | MAE | Criterion P | Criterion R | Criterion F1 | False awards | False deductions | Unresolved |
|---|---|---|---|---|---|---|---|---|---|---|
| A — whole document | 100.00% | 86.84% | 0/2 exact · 0/2 within 1 | 0.20 | 0.99 | 0.91 | 0.95 | 1 | 6.50 | 0 |
| B — extract then batch | 100.00% | 92.11% | 0/2 exact · 0/2 within 1 | 0.16 | 1.00 | 0.93 | 0.96 | 0 | 6 | 0 |
| C — whole document + specialists | 100.00% | 94.74% | 0/2 exact · 0/2 within 1 | 0.05 | 0.99 | 0.99 | 0.99 | 1 | 1 | 0 |

### C6 score audit

- C6's `paper_score_awarded` is **82**. The scoreable maximum is **87**, and the candidate reference is **80**. Thus 82 is an awarded total out of 87, not 82 out of 80.
- The raw C6 payload has 38 unique scoreable items, no duplicate or unmatched ids, and no item award above its 3-mark (or smaller) cap. Its item awards sum directly to 82; the only disagreements are Q26 awarded 3 vs reference 2, Q30 awarded 3 vs reference 2.
- The extra two marks are Q26 and Q30 over-awards (+1 each), not duplicate criteria or a maximum-mark accounting defect. The 82/80 appearance is therefore a derived report-label ambiguity: 80 is the candidate reference, not the denominator. The benchmark's strict correctness rule remains reference equality.

## 4. API consumption

| Strategy | Requests | Failed | Input tokens | Output tokens | Cached input | Total tokens | Est. cost USD | Cost / paper | Cost / near-correct paper | Cost / correct paper |
|---|---|---|---|---|---|---|---|---|---|---|
| A — whole document | 2 | 0 | 63,636 | 11,371 | 29,803 | 75,007 | 0.070251 | 0.035126 | unavailable | unavailable |
| B — extract then batch | 33 | 5 | 83,653 | 38,399 | 21,880 | 122,052 | 0.191967 | 0.095983 | unavailable | unavailable |
| C — whole document + specialists | 23 | 7 | 82,023 | 38,998 | 43,768 | 121,021 | 0.151344 | 0.075672 | unavailable | unavailable |

> Costs are provider-reported tokens × published list prices. Free-tier usage may be
> invoiced at USD 0; these are estimates for comparison, not invoices. A missing value
> is `unavailable`, never zero. Probe requests are excluded here and reported in §6.
> 'Near-correct' means the total is within one mark with full coverage; it is not used
> to relax the strict definition of a correctly assessed paper.

## 5. Processing time

| Strategy | Mean request latency (ms) | p50 | Max | Requests / paper | Observed successes / min | Observed 429 rate | Observed concurrency | Observed cooldown wait (s) |
|---|---|---|---|---|---|---|---|---|
| A — whole document | 25888.50 | 25888.50 | 29,947 | 1.00 | 0.00 | 0.00% | 1 | 0 (none) |
| B — extract then batch | 11014.50 | 6897.00 | 69,315 | 16.50 | 3.70 | 12.12% | 1 | unavailable |
| C — whole document + specialists | 35584.40 | 23002.50 | 168,832 | 11.50 | 1.34 | 0.00% | 1 | 0 (none) |

Observed concurrency is the peak overlap of request intervals reconstructed from
`started_at`/`finished_at` where present, otherwise completion time minus latency.
Cooldown wait is the instrumented scheduler wait for new rows. Historical 429 rows
without that field are labelled by their next observed use interval; assigned
`cooldown_s` values are never substituted for measured wait.

## 6. Key pool and observed quota

- Keys discovered: **20**; eligible (valid, reachable, generation-capable at discovery): **15**.
- Eligible keys with at least one successful benchmark request: **15 / 15**.
- Full eligible-key coverage: **True**.
- Coverage threshold: **15** successful benchmark requests; observed **95**.
  The threshold is a necessary floor, not a guarantee that every eligible key was used.
- The workload produced **144** benchmark requests (95 successful); coverage is **15 / 15**.
  All eligible keys have at least one successful benchmark request; excluded keys are listed below.
- Probe requests (excluded from benchmark totals): **59**; benchmark requests: **144**.

| Key | Validity | Quota | Network | Probe | Pool | Benchmark successes | Requests | 429s |
|---|---|---|---|---|---|---|---|---|
| KEY_01 | VALID | AVAILABLE | REACHABLE | healthy | POOL_SHARED_1 | 6 | 10 | 1 |
| KEY_02 | VALID | AVAILABLE | REACHABLE | healthy | POOL_SHARED_1 | 3 | 8 | 1 |
| KEY_03 | VALID | UNKNOWN | REACHABLE | http_error | POOL_UNKNOWN_KEY_03 | 0 | 1 | 0 |
| KEY_04 | VALID | UNKNOWN | REACHABLE | http_error | POOL_UNKNOWN_KEY_04 | 0 | 1 | 0 |
| KEY_05 | VALID | AVAILABLE | REACHABLE | healthy | POOL_SHARED_1 | 3 | 8 | 1 |
| KEY_06 | VALID | AVAILABLE | REACHABLE | healthy | POOL_SHARED_1 | 4 | 7 | 1 |
| KEY_07 | INVALID | UNKNOWN | REACHABLE | invalid_key | POOL_EXCLUDED_KEY_07 | 0 | 0 | 0 |
| KEY_08 | INVALID | UNKNOWN | REACHABLE | invalid_key | POOL_EXCLUDED_KEY_08 | 0 | 0 | 0 |
| KEY_09 | VALID | AVAILABLE | REACHABLE | healthy | POOL_SHARED_1 | 4 | 6 | 1 |
| KEY_10 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_2 | 5 | 7 | 1 |
| KEY_11 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 10 | 13 | 1 |
| KEY_12 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 8 | 11 | 1 |
| KEY_13 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 10 | 14 | 0 |
| KEY_14 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 8 | 11 | 1 |
| KEY_15 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 9 | 12 | 1 |
| KEY_16 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 3 | 6 | 1 |
| KEY_17 | VALID | AVAILABLE | REACHABLE | healthy | POOL_SHARED_1 | 2 | 5 | 1 |
| KEY_18 | VALID | UNKNOWN | REACHABLE | http_error | POOL_UNKNOWN_KEY_18 | 0 | 1 | 0 |
| KEY_19 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 9 | 12 | 0 |
| KEY_20 | VALID | AVAILABLE | REACHABLE | healthy | POOL_OBSERVED_3 | 11 | 13 | 0 |

| Observed pool | Keys | Benchmark successes | Requests | 429s |
|---|---|---|---|---|
| POOL_SHARED_1 | KEY_01, KEY_02, KEY_05, KEY_06, KEY_09, KEY_17 | 22 | 44 | 6 |
| POOL_UNKNOWN_KEY_03 | KEY_03 | 0 | 1 | 0 |
| POOL_UNKNOWN_KEY_04 | KEY_04 | 0 | 1 | 0 |
| POOL_EXCLUDED_KEY_07 | KEY_07 | 0 | 0 | 0 |
| POOL_EXCLUDED_KEY_08 | KEY_08 | 0 | 0 | 0 |
| POOL_OBSERVED_2 | KEY_10 | 5 | 7 | 1 |
| POOL_OBSERVED_3 | KEY_11, KEY_12, KEY_13, KEY_14, KEY_15, KEY_16, KEY_19, KEY_20 | 68 | 92 | 5 |
| POOL_UNKNOWN_KEY_18 | KEY_18 | 0 | 1 | 0 |

Keys excluded from eligibility:
- KEY_03: probe state http_error
- KEY_04: probe state http_error
- KEY_07: invalid key (UNAUTHENTICATED)
- KEY_08: invalid key (UNAUTHENTICATED)
- KEY_18: probe state http_error

### Did distribution improve throughput?

Per-key and per-pool states, successes, 429s and measured cooldown records are in
`api_usage.jsonl` and `results/throughput.json`. A 429 also suspends keys already inferred
into the same pool; that is cooldown protection, not additional quota. No controlled
single-key versus pool experiment was run in this pilot, so no causal throughput gain
is claimed. Distribution is load balancing within the observed quota, not extra quota.

## 7. Failure analysis

- B — extract then batch run 1: `complete`; 0 invalid response(s), 0 unresolved, 2 failed request(s); no unresolved parse/transport error remains in the final payload
- B — extract then batch run 2: `complete`; 0 invalid response(s), 0 unresolved, 3 failed request(s); no unresolved parse/transport error remains in the final payload
- C — whole document + specialists run 5: `complete`; 0 invalid response(s), 0 unresolved, 3 failed request(s); no unresolved parse/transport error remains in the final payload
- C — whole document + specialists run 6: `complete`; 0 invalid response(s), 0 unresolved, 4 failed request(s); no unresolved parse/transport error remains in the final payload

### Per-item disagreements (all runs)

| Strategy | Run | Item | Awarded | Reference | Model reason |
|---|---|---|---|---|---|
| A | 2 | 23 | 0 | 3 | Incorrect expansion from the first step (2x^3 instead of 2x^2) leading to incorrect answer -2x^3 - 7x^2 - 43x - 42 |
| A | 2 | 30 | 1 | 2 | First M1 awarded for correct expansion of two factors (12x^2 + 4x). The subsequent step contains arithmetic/copying erro |
| A | 2 | 36 | 3 | 2 | Student wrote 3x^3 + 36x^2 + 108x - 2x^2 - 22x - 72 (slight error on -22x) but correctly simplified their working line t |
| A | 3 | 21 | 1 | 2 | Student wrote 4n^3 + 8n^2 - 60n which is correct! Re-evaluating A1 mark: awarded. |
| A | 3 | 23 | 0 | 3 | Incorrect expansion throughout resulting in wrong final expression. |
| A | 3 | 26 | 1 | 2 | First method mark awarded for correct expansion of two brackets. Arithmetic/sign error in second expansion step. |
| A | 3 | 28 | 1 | 3 | All steps correct, full marks awarded. |
| A | 3 | 30 | 1 | 2 | First M1 awarded for expanding two factors. Arithmetic error 12x^2 * 2x = 22x^3 loses second M1 and A1. |
| A | 3 | 32 | 2 | 3 | Fully correct expansion and simplification matching mark scheme. |
| A | 3 | 36 | 3 | 2 | Fully correct final answer with valid method shown. |
| B | 1 | 7 | 0 | 2 | Blank answer. |
| B | 1 | 8 | 0 | 2 | Blank answer. |
| B | 1 | 19 | 0 | 2 | Blank question. |
| B | 2 | 7 | 0 | 2 | Blank response. |
| B | 2 | 8 | 0 | 2 | Blank response. |
| B | 2 | 19 | 0 | 2 | Question was blank. |
| C | 5 | 26 | 1 | 2 | First M1 awarded for correct expansion of two brackets, subsequent expansion has errors leading to incorrect final answe |
| C | 5 | 30 | 1 | 2 | First expansion is correct, but subsequent expansion contains a multiplication error (4 * 3 = 12, but student wrote 22x^ |
| C | 6 | 26 | 3 | 2 | All steps are fully correct. |
| C | 6 | 30 | 3 | 2 | Fully correct. |

### Observations

- Strategy A made 2 benchmark request(s) across its current run(s) 2, 3; scores 77 / 72 out of 87 against the candidate reference of 80, coverage 100.00%.
  Every current A run returned all scoreable items; the current pair is complete.
  The single whole-paper response covered all items; no split was required.
- Strategy B made 33 benchmark request(s) across its current run(s) 1, 2; scores 74 / 74 out of 87 against the candidate reference of 80, criterion F1 0.96, coverage 100.00%.
  Empty extracted answers remain for 19, 7, 8; these are extraction losses, not marking-rule losses. Root cause: the per-page transcription returned a blank student_answer for these ids, so the marking stage correctly saw blank work. The targeted re-read path is implemented but was not exercised by the selected B pair.
- Strategy C's current attempt `c-rerun-20261103T140743Z` returned all 38 items in both runs;
  scores 78 / 82 out of 87 against the candidate reference of 80, criterion F1 0.99. It recorded 0 raw `different`
  check(s) and 0 escalation(s); raw `escalation_gap` is False.
  Raw verification has 0 `different`; fixed re-evaluation recovers 6 genuine differences. The replay below is offline, not a live escalation run.
  Its raw item disagreements are listed below; the re-evaluated differences and replay are derived artifacts.
  The latest appended C attempt `c-rerun-20261103T194303Z` (run 9) was not promoted: not promoted; no valid differing pair.
  Offline replay (not a live run): 10 checks = 4 historical C1/C2 raw + 6 recovered C5/C6; pre-fix 0 escalation(s) with gap True; repaired guard 10 escalation(s) with gap False.
  A separate append-only live escalation re-marked only Q30 from one student page and one scheme page; it changed 1 to 2 and is not a rewrite of C5/C6.

### Live targeted escalation — C5 / Q30

This is a separate live provider response, not a rewrite of the selected C5/C6 runs. It used one anonymised student page and the matching one-page printed scheme; no whole-document upload was made.

| Base run | Item | Model | Before | After | Reference | Changed |
|---|---|---|---|---|---|---|
| C5 | Q30 | `gemini-3.6-flash` | 1 | 2 | 2 | True |

- Ledger batch `live-escalation-30`; status `200`; input/output tokens 2,595 / 487; estimated cost USD 0.003772.
- Page hashes: student `e2f41a758de48835…`, scheme `acd333ba7c346ed7…`; coverage 100.00% (1 / 1 item).
- This addendum does not alter C5/C6's measured scores or claim a complete fresh C pairing.

## 8. Caching

| Strategy | Run | Input tokens | Cached input | Cache hit rate | Reported cost USD |
|---|---|---|---|---|---|
| A — whole document | 2 | 31,818 | 29,803 | 93.7% | 0.024495 |
| A — whole document | 3 | 31,818 | not reported | n/a | 0.045756 |
| B — extract then batch | 1 | 41,809 | not reported | n/a | 0.104066 |
| B — extract then batch | 2 | 41,844 | 21,880 | 52.3% | 0.087901 |
| C — whole document + specialists | 5 | 41,034 | 21,884 | 53.3% | 0.079460 |
| C — whole document + specialists | 6 | 40,989 | 21,884 | 53.4% | 0.071885 |

Gemini implicit caching is provider-controlled and cannot be forced on or off per
request. The table is the measured split, not a controlled experiment.

**Important confound:** A2 was 93.7% cached; A3 reported no cached tokens. B's first
included run did not report cached tokens, while C's current first run was 53.3% cached.
C's cache state is not equal to B's or A's. A's reported cost is therefore partly a warm-cache
artefact; the strategies were not measured under equal cache conditions. No strategy was
deliberately given a cache advantage, and no cold-versus-warm causal claim is made.

## 9. Limitations

- One paper, one student, one sitting: no statistical significance and no general winner.
- The reference is candidate-only; a teacher must certify it before production adoption.
- Two items are excluded because the student page and scheme disagree (Q12, Q16d).
- Provider quota conditions differed between requests and pools; per-pool results are
  reported to expose the confounding rather than hiding it.
- A's selected pair required no output split; the split fallback remains available but was not exercised in these runs.
- The historical A1 run (26/38) remains preserved in the raw files and ledger; it is excluded from the current A pair.
- A's current selected runs contain no failed benchmark requests; retries are not counted as coverage.
- Lite model substitution: `gemini-3.1-flash-lite` was not verified on the first healthy
  keys, so `gemini-3.5-flash-lite` was used with its default thinking budget. This is a
  capability difference between strategies and is flagged as a confound.
- The selected C5/C6 runs made no escalation request; the separate targeted live escalation used `gemini-3.6-flash` on one student page plus one scheme page (2595 input, 487 output tokens; USD 0.003772).
- C's current attempt `c-rerun-20261103T140743Z` has 0 raw `different` check(s) and 0 escalation(s); raw `escalation_gap` is False. Earlier C runs (C1–C4) are preserved as historical attempts and are not used in this verdict. Raw C5/C6 verification has 0 `different`; fixed re-evaluation recovers 6 genuine differences (C5 4, C6 2). Offline replay of those plus 4 historical C1/C2 differences has pre-fix 0 escalation(s) with gap True, and fixed 10 escalation(s) with gap False; the full-document branch remains unexercised. Separately, a targeted live escalation of C5 item 30 changed 1 to 2.
- Raw C5/C6 verification has 0 `different`; fixed re-evaluation recovers 6 (C5 4, C6 2). The raw C files were not rewritten; the re-evaluation lives in the derived replay artifact.
- The latest appended C attempt `c-rerun-20261103T194303Z` (run 9) was not promoted: not promoted; no valid differing pair.
- This replay demonstrates the guard on preserved raw and re-evaluated inputs; it is not a new live C measurement. No live API calls were made for the replay. The separate targeted live escalation below is the live evidence. Offline replay (not a live run): 10 checks = 4 historical C1/C2 raw + 6 recovered C5/C6; pre-fix 0 escalation(s) with gap True; repaired guard 10 escalation(s) with gap False.
- Full-document C reruns C9–C13 remained provider-blocked by HTTP 503/timeouts. The live escalation evidence is a separate targeted addendum for C5 Q30, not a complete fresh C pairing.
- All provider calls were sequential (concurrency 1); no concurrency speed-up is claimed.
- Historical 429 rows that predate instrumentation have no `cooldown_wait_s`; their
  next observed use interval is labelled in `throughput.json` rather than treated as a
  configured cooldown. New rows record the measured scheduler wait; no wait-time causal
  claim is made.

## 10. Recommended architecture

See `RECOMMENDATION.md`. No strategy met the strict bar of an exact paper score with
full coverage, so the recommendation is a conditional architecture choice, not a
production adoption.

## 11. Further experiments before production

- Teacher-certify this paper and a holdout of at least 10 papers across topics.
- Repeat A's completeness check on additional papers; the current pair is complete
  and any output split is recorded in the raw run and ledger.
- B's Q7/Q8/Q19 loss is recorded as a blank per-page transcription; validate the targeted re-read path on a live B run and add a transcription verification step.
- C's escalation branch has been demonstrated offline; its full-document live reruns were provider-blocked (HTTP 503/timeouts), while a targeted live single-item escalation succeeded. A full live C pairing and an image-grounded transcription fidelity check remain necessary to measure whether either removes its corrected-answer over-awards.
- Repeat with cold and warm caches explicitly controlled where the provider allows.
- Run a single-key versus pool throughput experiment before relying on distribution.

## Appendix — source integrity

- Dataset manifest: `dataset_manifest.json`; anonymised copies only.
- Reference: `ground_truth/paper-01.json`; review sheet: `ground_truth/REVIEW_SHEET.md`.
- Q12 and Q16(d) are documented exclusions, not zero-mark questions.
- Batch-scope validator messages that named items already present in the final payload
  were removed from this report; raw run files retain them.

# Methodology

## 1. Question

Which packaging gives the highest count of **correctly assessed papers per unit
of API quota consumed**, with accuracy treated as a constraint rather than a
trade-off?

## 2. Dataset selection

The new project was empty. V5 was inspected read-only. The only real student
work present was in V5's temporary ingestion directories:

- `.tmp_paper/p01..p07.png` — seven scanned pages of a handwritten algebra
  workbook (pages 340–346), 37 numbered Edexcel-style questions.
- `.tmp_scheme_pages/page-01..21.png` — the matching printed scheme with
  criterion-level M1/A1/B1 clauses and expected answers.

No original PDF is present in the V5 tree, so the retained renders are the
highest-fidelity copy available. No stored correction for this paper exists.
V5's own reference set is synthetic and 0/16 teacher-verified, so it was not
used as ground truth.

Only anonymised copies entered this project: the teacher name printed in the
footer and the scanner vendor watermark were painted out; question content,
marks and page numbers were not altered. `dataset_manifest.json` records source
paths, SHA-256 hashes and the redaction rectangles. Originals were never copied.

## 3. Ground truth

`ground_truth/paper-01.json` was built from the printed scheme:

- every scheme criterion was transcribed (code, text, expected answer);
- each question was solved independently;
- each criterion was awarded only where the student's visible working evidenced
  it;
- uncertainty is recorded per item (`confidence`, `evidence`);
- totals are validated against the scheme's marks.

Two source inconsistencies are documented rather than papered over:

| Item | Problem | Handling |
|---|---|---|
| Q12 | Student page repeats the Q11 expression; scheme Q12 is a different question | excluded from scoring |
| Q16(d) | Marked in the scheme but not printed on the student page | excluded from scoring |

The reference status is **candidate_not_teacher_certified**. `REVIEW_SHEET.md`
is the sign-off form. Every report labels accuracy provisional.

## 4. Strategies

All three receive the same paper, scheme, marking instructions, output schema,
temperature, top-p and thinking budget.

- **A (whole document)** — one request containing all 7 student pages and all
  21 scheme pages. If a successful response omits scoreable items, `run_a`
  triggers the documented output split: up to two completion requests for the
  missing ids (six per request), with the same document, scheme, system prompt
  and schema. The recorded A1 predates the fallback and remains preserved as a
  historical incomplete attempt (26/38); it is excluded from the current pair.
  A3 is a real appended reattempt: its whole-paper response returned all 38
  items, so no split request was needed. The current A2/A3 pair is complete; the
  fallback remains available and is logged if a future response omits items.
- **B (extract then batch)** — one scheme-extraction request, one transcription
  request per student page, then six text-only marking batches. Extraction
  requests carry `purpose=extraction` and are totalled separately. Marking sees
  only the extracted text, so transcription loss is part of B's measured cost.
- **C (whole document + specialists)** — one multimodal understanding pass over
  the student pages, one scheme canonicalisation pass, six Lite marking
  batches, a SymPy equivalence check per item, and escalation of items that are
  low-confidence, flagged, or mathematically inconsistent with the scheme's
  expected answer. Escalation is capped at six per run and recorded with purpose
  `escalation`.

## 5. Controls

- Same paper, scheme, criteria, schema, item list and system prompt.
- Exact model IDs recorded per run; substitutions are logged.
- temperature 0, top-p 0.95, thinking budget 0; one media resolution (the
  source renders, unresized).
- Two selected runs per strategy for comparison. The original six were
  interleaved A1→B1→C1→A2→B2→C2 so a quota change did not systematically favour
  one strategy; A3 was appended as a recorded complete reattempt.
- Implicit provider caching cannot be forced; cached tokens are recorded. Actual
  cache states differed between strategies and are reported as a confound, not as a
  controlled variable.
- Failed requests and retries are counted in consumption.
- The same key pool serves every strategy, round-robin, and the key label and
  observed pool are logged on every request.

## 6. Key pool

Keys are read into memory from V5's authorised file; only labels
(`KEY_01…KEY_20`) ever appear in logs or reports. Per key, three independent
states are kept: `key_validity`, `quota_state`, `network_state`.

- A 429 suspends the key for the provider's `Retry-After` (or a conservative
  per-minute/daily default); it is never retried in a tight loop and never
  treated as an invalid key. A daily quota is parked for a 24-hour reset window;
  keys already inferred into the same quota pool are suspended too.
- Invalid/revoked keys are excluded with a reason.
- Pools are inferred from quota IDs and observed co-limitation; a success
  immediately after another key was limited is recorded as *observed
  independence*, not as proof of separate projects.
- Distribution across keys is load balancing. It is not treated as additional
  quota, and no throughput gain is attributed to it without a controlled test.
- Coverage rule: an eligible key counts as used only after a successful
  Strategy A/B/C request. Probe requests never count.

## 7. Instrumentation

Every request writes one row to `results/api_usage.jsonl` (also aggregated in
the result files): strategy, run, batch, item IDs, provider, model, purpose, key
label, pool, three key states, input/output/cached/thinking/total tokens, image
tokens where itemised, reported-vs-estimated flags, latency, HTTP status, error
class/code, retry-after, cooldown, attempt, escalation flag and success.

Cost = provider-reported tokens × `pricing.json` list prices. Missing prices or
tokens produce `null`, not zero. The provider's free tier may bill USD 0; the
report distinguishes list-price estimate from invoice.

## 8. Metrics

Accuracy: criterion precision/recall/F1 (criteria matched by code and order),
item exact match, exact paper score, mean absolute score error, false awards,
false deductions, coverage, unresolved items, invalid JSON/schema responses,
hallucination suspects (e.g. marks awarded for the blank Q37b) and a manual
audit of reported student answers.

Efficiency: requests per paper, input/output/total tokens per paper, cost per
paper, cost per correctly assessed paper, quota efficiency (correct papers per
1,000 requests), latency, escalation cost, failure cost, cache saving estimate,
and observed throughput per key/pool.

A paper is **correctly assessed** only when its total equals the candidate
reference, every scoreable item was returned, no item is unresolved and no
response was invalid. A strategy that skips difficult questions therefore
cannot look efficient.

## 9. Fairness and validity

- One strategy never consumes another's result; the only shared artifact is the
  source paper and scheme.
- No strategy sees information another does not (C's extra passes are part of C
  and are costed).
- Failures, retries and cooldowns are never excluded from consumption.
- Per-pool results expose confounding when quota conditions differ.
- One paper is an engineering pilot. No statistical significance is claimed and
  no general winner is declared.

## 10. Deviations and limitations

- The reference is not teacher-certified.
- Two items are excluded for source inconsistency, reducing the scoreable paper
  from 91 scheme marks to 87.
- Provider quota conditions may vary between runs; per-pool figures are shown.
- Image-token accounting is only what the provider itemises.
- Implicit caching is uncontrolled; measured cache states are reported, but no causal cold/warm effect is claimed.

## 11. Executed protocol and measured result

The final experiment used `gemini-3.6-flash` for A and for C's document/scheme
passes, and `gemini-3.5-flash-lite` for B/C marking. The requested
`gemini-3.1-flash-lite` was transiently unavailable during model selection and the
requested strong escalation model `gemini-3.1-pro-preview` was quota-limited, so
the strong role fell back to `gemini-3.6-flash`. Lite therefore ran with its default
thinking budget rather than the requested zero; this is a capability confound. The implemented escalation rule was capped at six per run and required confidence < 0.6, an ambiguous/illegible flag, or a SymPy disagreement with a non-empty expected answer.

| Measure | A | B | C |
|---|---|---|---|
| Runs | 2 | 2 | 2 |
| Items returned | 38, 38 | 38, 38 | 38, 38 |
| Paper score /87 (candidate reference 80) | 77, 72 | 74, 74 | 78, 82 |
| Criterion F1 | 0.9479 | 0.9610 | 0.9875 |
| False awards / deductions | 1 / 6.5 | 0 / 6 | 1 / 1 |
| Requests (including failures) | 2 | 33 | 23 |
| Input / output tokens | 63,636 / 11,371 | 83,653 / 38,399 | 82,023 / 38,998 |
| Cost at list price (USD) | 0.070251 | 0.191967 | 0.151344 |
| Strictly correct papers | 0/2 | 0/2 | 0/2 |

The planned benchmark workload was 46–58 requests (A 1, B 14, C 8 plus up to
six C escalations per run). The original six interleaved runs (A1→B1→C1→A2→B2→C2)
contributed 53 requests. A3 added one appended A request; append-only C attempts
added 90 failed or completed request rows across C3–C13. The current ledger is
144 benchmark requests (95 successful) plus 59 discovery/model probes logged
separately. C7/C8 were not promoted because scheme extraction failed. C9–C13
were attempted after C5/C6; every full-document request returned HTTP 503 (model
high demand) or timed out, including explicit 3.6, 3.5, 3.8 and 3.1-Lite
fallbacks. No C9–C13 run enters the C accuracy verdict. A separate targeted live
escalation of C5/Q30 from one student page and one scheme page changed 1 to 2 and
is recorded in `results/live_escalation.json`; that addendum is the live escalation
evidence and is not part of the selected C5/C6 accuracy pair. All runs used the same reference, schema and instructions. The reference
is still candidate-only, so these are provisional measurements from one paper.

Key coverage is 20 discovered, 15 eligible, and all 15 with at least one successful
benchmark request. No eligible key was unused; five keys were ineligible: two
invalid and three with HTTP/probe errors. Full coverage is true and probes never
count as coverage.

All provider calls were issued sequentially (concurrency 1); no concurrency
speed-up is claimed. Historical ledger rows record the assigned cooldown window,
not the actual wall-clock time spent waiting; new rows record the measured
scheduler acquire wait. Assigned `cooldown_s` values are never used as measured
wait, and historical 429 rows without instrumentation are labelled by their next
observed use interval. A's cost is warm-cache affected: its first included run already reported 29,803
cached input tokens (93.7% of input) from earlier aborted attempts; A3 reported no
cached tokens, while B's first run did not report cached tokens. A's reported cost
is therefore cache-affected and no cold-cache cost advantage is established. C's
current first run was 53.3% cached. Cache states were not equal and no causal claim
is made.

## 12. What actually failed

- **A, historical run 1:** returned 26 of 38 items in a single HTTP 200 response,
  omitting Q27–Q37b. It is preserved as incomplete but is excluded from the current
  A pair. A2 and A3 both returned all items; A3 did not require the split.
- **A, current A2/A3:** Q23 is a false deduction in both runs; the correct answer is
  `2x^3 - 7x^2 - 43x - 42`. A3 also has item-level disagreements at Q21, Q26, Q28,
  Q30, Q32 and Q36; these remain measured errors, not corrected results.
- **B, Q7/Q8/Q19:** the per-page extraction returned an empty `student_answer`,
  so marking correctly awarded zero to blank input. These are extraction losses,
  not marking-rule errors. B had no false awards and full coverage.
- **C, current C5/C6:** the attempt returned all 38 items and recorded 0 raw
  `different` checks and 0 escalations. The fixed classifier re-evaluates the
  preserved C5/C6 inputs and recovers 6 genuine differences (C5 4, C6 2); C5
  under-awarded Q26/Q30 and C6 over-awarded the same items. The current scores are
  a valid whole-document/Lite measurement. A separate targeted live escalation
  on C5/Q30 changed 1 to 2 using one student page and one scheme page. C1–C4 are
  historical attempts; C7/C8 are preserved but invalid because scheme extraction
  failed. C9–C13 were provider-blocked/incomplete full-document attempts, so none
  is used in the current verdict; the targeted live addendum is the live evidence.
- **C escalation:** the repaired guard is present. C5/C6 raw verification had no
  `different` checks, but offline replay drives the 6 recovered C5/C6 differences
  plus 4 historical C1/C2 raw differences through the guard: 10 checks, with
  pre-fix 0 escalations / gap True and fixed 10 escalations / gap False. This is
  replay evidence, not a live C measurement; no corrected-answer claim is made
  for the selected C5/C6 attempt. The targeted live Q30 addendum is separately
  recorded and is not a full-document run.

## 13. Reproduction and derived artifacts

- `results/raw/` holds the authoritative model responses for the original six runs, the complete A3 reattempt and the C rerun attempts that produced a raw payload (C3–C9); C7/C8 are preserved invalid attempts and are not promoted. C10–C13 failed before a raw run file was written; their failed requests remain in the ledger.
- `results/api_usage.jsonl` is the current request ledger; older ledgers are
  preserved as `api_usage.previous-*.jsonl` and are not included in totals.
- `python -m benchmark.code.regenerate` rebuilds every derived JSON and report
  from the raw runs and ledger without contacting the provider. This is how the
  reports were corrected after the experiment; only C was rerun, append-only.
- `pytest benchmark/tests -q` runs the offline measurement and strategy tests.

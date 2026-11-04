# Correction strategy benchmark

An engineering pilot that compares three ways of marking one real handwritten
mathematics workbook with the same paper, mark scheme, ground-truth reference,
output schema and marking instructions:

| Strategy | Packaging |
|---|---|
| **A** | Whole document: every student page and every scheme page in one multimodal request |
| **B** | Extract first (scheme clauses, per-page transcription), then text-only marking batches |
| **C** | Whole-document understanding once, reusable scheme representation, Lite batch marking, SymPy checks, per-item escalation |

The deliverable is evidence about accuracy, API consumption and cost — not a
production correction engine.

## Status labels

- **Reference: candidate, NOT teacher-certified.** Marks come from the printed
  criterion-level scheme plus an independent re-solve. `ground_truth/REVIEW_SHEET.md`
  is the form a teacher signs; until then accuracy is provisional.
- **One paper.** No statistical significance and no general winner.
- **Source exclusions.** Q12 is excluded because the student page and the mark
  scheme disagree; Q16(d) is excluded because it is marked in the scheme but not
  printed on the student page. They remain in the dataset; the exclusions and
  their reasons are in `ground_truth/paper-01.json` and the report.

## Measured outcome (this pilot)

The original six interleaved runs, a recorded A3 reattempt, and four separately identified C rerun groups (C3/C4, C5/C6 current, C7/C8 invalid, and C9–C13 provider-blocked or incomplete) were recorded against the candidate reference of 80/87 marks. The current A evidence is A2/A3; both cover all 38 scoreable items. The current ledger contains 144 benchmark requests (95 successful) and 59 probe requests; the targeted live escalation is the extra request. **No strategy was strictly correct on the paper in either reported run.**

| Strategy | Coverage | Paper scores /87 (candidate ref 80) | Criterion F1 | Requests | Cost USD | Main failure |
|---|---|---|---|---|---|---|
| A | 100% | 77, 72 | 0.9479 | 2 | 0.0703 | Q23 false deduction in both current runs; A1 historical 26/38 excluded |
| B | 100% | 74, 74 | 0.9610 | 33 | 0.1920 | Q7/Q8/Q19 extracted blank in both runs (6 false deductions); root cause is blank per-page transcription |
| C | 100% | 78, 82 | 0.9875 | 23 | 0.1513 | Q26/Q30 disagreements: C5 under-awarded, C6 over-awarded; 0 raw `different` checks, 6 recovered offline; targeted live Q30 escalation changed 1→2; full-document C9–C13 remained blocked |

A1 is preserved as a historical incomplete run (26/38) and is excluded from the current pair. The current A2/A3 pair is complete: A3's whole-paper request returned all 38 scoreable items, so no split request was needed; the ledger contains only the real A3 request. A's cost is cache-affected (A2 was 93.7% cached; A3 reported no cached tokens), so no cold-cache cost advantage is claimed. C's current attempt (C5/C6) is protocol-compliant on the escalation gate. Its raw verification had 0 `different` checks; the fixed classifier recovers 6 genuine C5/C6 differences, and an offline replay of those plus 4 historical C1/C2 differences exercises the repaired guard (10 checks, gap True before the fix and False after). This replay is offline evidence. A separate targeted live escalation on C5/Q30 used one student page and one scheme page, changed 1 to 2, and is recorded in `results/live_escalation.json`; it is not a fresh complete C run. Full-document C9–C13 attempts remained blocked by provider HTTP 503/timeouts; they remain in the ledger and are not used in the C verdict. The live addendum adds one request and USD 0.003773 to the ledger, but not to C's selected 23-request total. C1–C4 are preserved as historical attempts; C7/C8 are preserved but invalid because scheme extraction failed. Key coverage is 15 of 15 eligible keys; the five excluded keys are listed in `key_coverage.json`. See `reports/BENCHMARK_REPORT.md` and `reports/RECOMMENDATION.md`.

## Layout

```
benchmark/
  README.md                  this file
  methodology.md             design, controls, metrics, limitations
  dataset_manifest.json      source paths, SHA-256s, redactions, page map
  pricing.json               provider list prices + retrieval date
  anonymized_samples/        redacted student and scheme pages (the only copies)
  ground_truth/
    paper-01.json            criterion-level candidate reference
    REVIEW_SHEET.md          printable teacher review form
  code/                      reusable loader, provider, key pool, runners, metrics
  tests/                     offline tests (fake provider, no network)
  results/                   measured JSON/JSONL from the live runs
  reports/                   BENCHMARK_REPORT.md, RECOMMENDATION.md
  holdout/                   certified-paper intake, registration and promotion
```

## Running

The benchmark needs an authorised Gemini API key pool. It reads V5's key file
**read-only** and never writes a key into this project. Never put a key in a
source file, a log, or this repository.

```
# key discovery and model probes only (no benchmark requests)
python -m benchmark.code.run_benchmark --probe-only

# the experiment: two interleaved runs per strategy
python -m benchmark.code.run_benchmark --runs 2

# offline tests (no network)
python -m pytest benchmark/tests -q

# regenerate derived results/reports from preserved raw runs (no API calls)
python -m benchmark.code.regenerate
```

The project-local interpreter used during development is `.tools/python`
(git-ignored). Any Python 3.13 with `pillow`/`sympy`/`pytest` can run the code; the API
adapter uses only the standard library.

## Holdout intake

The teacher-certified multi-paper holdout is **not populated**: the live manifest is at
`blocked_no_certified_papers` with zero papers. `paper-01` is the design paper and cannot
serve as holdout evidence.

The intake, certification, registration and promotion workflow is documented in
[holdout/INTAKE_GUIDE.md](holdout/INTAKE_GUIDE.md). Human marking rules are in
[holdout/CERTIFICATION_PROTOCOL.md](holdout/CERTIFICATION_PROTOCOL.md), dataset requirements
in [holdout/HOLDOUT_REQUIREMENTS.md](holdout/HOLDOUT_REQUIREMENTS.md), and the frozen plan in
[holdout/PREREGISTRATION.md](holdout/PREREGISTRATION.md).

A generated certification draft, a registered candidate revision and a promoted manifest
entry are distinct states. None of them is created automatically, and a detached hash proves
integrity, not signer identity. No holdout score may be reported until the pre-registered
number of certified papers exists: 10 for the decision rule per
[holdout/HOLDOUT_REQUIREMENTS.md](holdout/HOLDOUT_REQUIREMENTS.md), with 8 the
implementation's `certified_holdout` threshold.

## Measurement rules

- One JSONL row per request, including retries and failures.
- Provider-reported tokens and locally estimated values are separate fields.
- Probe requests are marked `purpose=probe` and excluded from benchmark totals.
- A missing price is `null`, never zero.
- `key_validity`, `quota_state` and `network_state` are independent; a 429 never
  makes a key invalid.
- No claim that a key was used unless it has a successful Strategy A/B/C request.

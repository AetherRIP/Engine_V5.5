# Holdout dataset requirements

## 1. What is available today (verified, not assumed)

| Check | Result |
|---|---|
| Papers in `benchmark/anonymized_samples` | **1** (`paper-01`: 7 student pages, 21 scheme pages) |
| Papers with a certified reference | **0** |
| Papers with a candidate reference | 1 (`paper-01`, 80/87, `candidate_not_teacher_certified`) |
| Certification signature in `REVIEW_SHEET.md` | none (blank reviewer record) |
| Independent papers in the V5 source directories | **0** — `.tmp_paper` holds `p01..p07.png` plus `j01..j07.jpg` re-encodings of the same seven pages; `.tmp_scheme_pages` holds the same 21 scheme pages |
| Second examination paper anywhere in the workspace | none found |

**Conclusion: the holdout dataset does not exist yet.** `paper-01` cannot serve as holdout
for two independent reasons: it is the paper the hybrid was designed and evaluated on, and
it is one topic. This report therefore stops at requirements and a frozen plan, as the
mission requires.

`paper-01` is also structurally narrow: all 38 items are "expand and simplify", all use
`M1`/`A1`/`B1` codes, 87 marks, 1- and 2- and 3-mark items only, and 37 of 38 items are
reference-confidence `high`. It cannot stand in for a topic mix.

## 2. Minimum viable holdout: 10 certified papers

A paper is one student's complete attempt at one examination paper, with its printed mark
scheme. Ten is the minimum that supports a **paper-level** paired comparison; fewer cannot
distinguish a strategy effect from one unusual paper.

### Composition matrix

| Dimension | Minimum |
|---|---|
| Papers | 10 certified, independent (different paper, ideally different series) |
| Topic domains | ≥ 4, at least 1 non-algebra: algebraic manipulation; quadratics/factorising; fractions, indices and surds; geometry/trigonometry; statistics/probability |
| Difficulty bands | ≥ 3 (foundation, higher, multi-step/problem-solving) |
| Paper length | 45–100 marks each; ≥ 25 scoreable items per paper |
| Mark allocations | mix of 1-, 2-, 3- and ≥ 4-mark items |
| Scheme conventions | both `M1/A1/B1` and scheme styles with follow-through (`ft`) and dependent method marks (see the scoring restriction below) |
| Handwriting quality | ≥ 2 papers with illegible or ambiguous working on ≥ 10% of items |
| Source inconsistency | at least 1 paper with a documented `source_mismatch` or `not_printed` exclusion, to test exclusion handling |
| Reference | 100% teacher-certified per `CERTIFICATION_PROTOCOL.md`; κ reported per paper |

Total expected size: ≈ 10 papers × 30–38 items ≈ 300–380 items, ≈ 700–900 criteria.

## 3. Why 10, and when 10 is not enough

The primary endpoint is the per-paper paired difference in absolute total-mark error
(H-high − A-only). Papers are the unit of generalisation, so the sample size is the number
of papers, not items. For a two-sided paired test at 80% power:

`n ≈ 7.85 · σ² / δ²`, where `σ` is the between-paper SD of the paired difference and `δ`
the improvement in marks per paper.

| Between-paper SD σ | δ = 1 mark | δ = 2 marks | δ = 3 marks |
|---|---|---|---|
| 1.5 | 18 | 5 | 2 |
| 2.0 | 32 | 8 | 4 |
| 3.0 | 71 | 18 | 8 |

`σ` is unknown: the single-paper experiment provides no between-paper variance at all.
Ten papers covers the realistic case (δ ≈ 2, σ ≈ 2) with a small margin, and is enough to
*evaluate the safety gates*, which are counts rather than tests.

Ten is **not** sufficient for:

- topic-specific claims (≈ 2 papers per topic);
- rare failure modes below ~1 in 100 escalations;
- claims about unrepresented conventions (e.g. 4-mark "show that" items are sparsely
  represented even at 10 papers);
- estimating between-paper variance well enough for precise planning of a later study.

If only 6–9 papers can be certified, run the plan descriptively: report per-paper results,
do not apply the pass/fail decision rule, and state the limitation.

## 4. What is required per paper before it enters the manifest

1. Complete anonymised student pages and complete printed scheme pages.
2. Page-level `sha256` hashes recorded in `holdout_manifest.json`.
3. A teacher-certified reference with two independent marker sheets, an adjudication record
   for every disagreement, exclusions with reasons, and a signed certification artifact.
4. A `paper_id` that is not `paper-01` and no page hash that collides with `paper-01`
   (the manifest validator enforces both).
5. Reference totals that reconcile: Σ criterion marks = Σ item `max_marks`; no item award
   exceeds its cap; no duplicate item ids.
6. No student identity anywhere in the artifacts.

**Scoring restriction.** The frozen evaluator pairs only `M1`, `M2`, `A1`, `A2`, `B1` and
`B2`, plus an approved `DEP` alias such as `M1dep`. Papers using other conventions (for
example `ft` or `C1`-style codes) are accepted by intake but **blocked from registration and
scoring** until a separately approved scoring extension exists. Do not modify
`_normalize_code` as a workaround: it is frozen and changing it voids the pre-registered run.

## 5. Intake sequence

The intake workspace is created and filled by the CLI; the live manifest is not edited by
hand. The full guide is [INTAKE_GUIDE.md](INTAKE_GUIDE.md).

```
holdout/papers/<paper_id>/
  items.json               custodian's printed item registry (≥25 items)
  pages/student/*.png      anonymised student pages
  pages/scheme/*.png       printed scheme pages
  markers/original/…      preserved raw marker submissions
  markers/marker_a.json    normalised sheet A
  markers/marker_b.json    normalised sheet B
  adjudication.json        disagreements, resolutions, exclusions
  audit.json               audit re-mark evidence
  reference.json           derived, adjudicated criterion-level marks
  certification.json       two markers + adjudicator + κ + audit + evidence hashes
  attestations/…           detached marker, adjudicator and custodian evidence
```

Commands (all refuse to run out of order):

```
python -m benchmark.holdout.intake init <paper_id> --items items.json \
  --topic <topic> --difficulty <band> --marks <n>
python -m benchmark.holdout.intake pages <paper_id> --role student --files …
python -m benchmark.holdout.intake pages <paper_id> --role scheme --files …
python -m benchmark.holdout.intake markers <paper_id> --role marker_a \
  --marker-id MARKER_A_01 --file marker_a_raw.json
python -m benchmark.holdout.intake markers <paper_id> --role marker_b \
  --marker-id MARKER_B_01 --file marker_b_raw.json
python -m benchmark.holdout.intake adjudicate <paper_id> --file adjudication.json
python -m benchmark.holdout.intake build <paper_id> --audit audit.json
python -m benchmark.holdout.intake attest <paper_id> --role <role> --file evidence.json
python -m benchmark.holdout.intake validate <paper_id>
python -m benchmark.holdout.intake register <paper_id> [--dry-run]
python -m benchmark.holdout.intake promote --revision <revision.json> \
  --approval approval.json [--dry-run]
```

Registration creates an immutable **candidate** revision under
`holdout/registrations/<paper_id>/` and leaves the live manifest unchanged. Promotion is a
separate, explicitly approved operation that writes a new manifest revision under
`holdout/manifests/`; it does not move a live pointer. A paper that fails validation is not
eligible; it is not "provisionally" eligible.

## 6. Request

The benchmark needs **10 independently sourced, teacher-certified papers** matching
§2 before any holdout request is issued. Until they exist, the honest status is *blocked on
data*, not *hybrid validated*.

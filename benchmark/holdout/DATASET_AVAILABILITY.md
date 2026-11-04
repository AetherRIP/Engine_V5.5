# Dataset availability audit

Audited 2026-11-03 against the workspace as it stands. Nothing here is estimated: every
count and hash was read from disk.

## 1. Papers available

| Location | What is actually there | Independent papers |
|---|---|---|
| `benchmark/anonymized_samples` | 7 student pages + 21 scheme pages, one workbook (`paper-01`) | **1** |
| `benchmark/ground_truth` | `paper-01.json` (candidate 80/87) and an unsigned review sheet | 1, uncertified |
| `C:\Projects\MATH_CHECKER_V5\.tmp_paper` | `p01..p07.png` — the same seven pages at 1240×1755 | 0 new |
| `C:\Projects\MATH_CHECKER_V5\.tmp_paper` | `j01..j07.jpg` — the same seven pages re-encoded at 910×1287 | 0 new |
| `C:\Projects\MATH_CHECKER_V5\.tmp_scheme_pages` | 21 scheme pages, the same scheme as `paper-01` | 0 new |
| Anywhere else in the workspace | no examination paper found | 0 new |

The `j0*.jpg` files were checked rather than assumed to be duplicates: decoded to a common
resolution, the mean absolute grey-level difference against the corresponding `p0*.png` is
1.3–2.8 (max 242 at ink edges), i.e. JPEG re-encoding of the same scans, not a second paper.

**Independent papers: 1. Teacher-certified papers: 0.**

## 2. Why `paper-01` cannot be the holdout

1. It is the paper Strategy H was designed, tuned against and evaluated on. Using it again
   would measure the fit, not generalisation.
2. Its reference is `candidate_not_teacher_certified`. The review sheet's reviewer record
   is blank, so no mark has been signed off.
3. It is one topic. All 38 scoreable items contain "expand and simplify"; there are no
   factorising, fractions, geometry or statistics items. Scheme codes are only
   `M1` (48), `A1` (33), `B1` (5) and one `M1dep`; mark sizes are only 1, 2 and 3.
4. Its difficulty is narrow: 37 of 38 items carry reference confidence `high`, and the two
   exclusions are both source defects rather than hard marking judgements.
5. It is one student, one sitting. There is no second script for the same paper.

A 10-paper holdout cannot be built by re-splitting this paper. Duplicating pages or
splitting items would fabricate independence.

## 3. Certification state

| Requirement | State |
|---|---|
| Two independent human markers | none |
| Adjudicator | none |
| Criterion-level κ | not computed |
| Disagreement records | none |
| Exclusions with reasons | present in the candidate reference (Q12, Q16d) but not teacher-confirmed |
| Signed certification artifact | none |

No AI-generated reference is counted as certified, and the existing candidate reference is
not promoted by this audit.

## 4. Consequence

The mission's stop condition applies: **teacher-certified papers are unavailable**, so this
work stops at dataset requirements and a frozen experiment plan. Specifically:

- no holdout evaluation was run;
- no provider request was made for this phase (USD 0.00 spent);
- no accuracy, cost or generalisation claim is made;
- the `paper-01` artifacts, its raw runs, the ledger, the probe log and the frozen reports
  are unchanged.

Status recorded in `holdout_manifest.json`: `blocked_no_certified_papers`,
0 papers, 0 certified.

## 5. What unblocks it

Ten certified papers matching `HOLDOUT_REQUIREMENTS.md` §2, each with the artifacts in §5
and a passing `python -m benchmark.holdout.manifest` run. The validator refuses a paper
with fewer than two human signatures, an unresolved disagreement, a κ below 0.60, a
colliding page hash, or a reference whose totals do not reconcile — so a paper cannot be
counted as certified by editing a status field.

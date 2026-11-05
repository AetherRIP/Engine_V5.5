# Reference reconciliation — ch2-l3-final-01

Status: **RESOLVED — reference band 74–78 (centre 76).** No API request had been made when the reference was fixed.

## 1. Source verification

| Check | Result |
|---|---|
| Student PDF | `Ch2 L3.pdf`, 7 pages, CamScanner scan, SHA-256 `1a0598e17875b601258f88955ff08bc57e346269ba740e2222ab5782f5475678` |
| Mark-scheme PDF | `Ch2L3MS- Simplifying Expressions.pdf`, 21 pages, SHA-256 `bb89f80b9027a73e7815c9839f094af3c270210250783ca8277eff15f7030b13` |
| Text layer | None in either PDF (image-only scans) |
| PDF annotations | None in either PDF |
| Red teacher ink | **None.** Red-pixel share is 0.000% on all 7 student pages; only blue/black student ink is present |
| Teacher awarded marks / ticks | **None visible anywhere in the student PDF** |
| Complete student work | Yes — Q1a through Q37a, plus a Q37b answer in this scan |
| Complete printed scheme | Yes — 21 pages, Q1–Q37 including Q12 and Q16(d) |
| Q12 | Confirmed defective: student page repeats the Q11 expression; scheme Q12 is a different question (`4p + 20 + 7p - 14`) |
| Q16(d) | Confirmed not printed on the student page; scheme still marks it |
| Q32 mark conflict | Worksheet prints **(2)** beside Q32; the scheme prints **3** marks for Jan 22/1H/Q13a. Not previously documented. |

The supplied scan is the same workbook as historical `paper-01` (pages 340–346, same 7 student pages, same 21 scheme pages). It is **not** byte-identical to the historical dataset: this scan contains a Q37b answer, `a^5 b^2`, where the historical scan (and `paper-01.json`) recorded a blank answer.

## 2. What the 11 marks can mean

The reference must satisfy: `eligible maximum − awarded = 11`.

- Eligible maximum after the two mandatory exclusions: **87** (91 printed − Q12 2 − Q16d 2).
- 87 − 11 = **76**. So the user's figure implies an awarded score of 76/87.

An independent criterion-level re-mark of the supplied scan does **not** reach 76 under any defensible reading of the printed scheme. The scheme contains three items whose A1 row says *"Working required"* where the student wrote only the correct answer: **Q30, Q31, Q34**. The reading chosen for those three items moves the total by up to 9 marks:

| Reading of "Working required" | Q30 | Q31 | Q34 | Eligible total | Eligible marks lost |
|---|---|---|---|---|---|
| Correct answer scores full marks | 3/3 | 3/3 | 3/3 | **80/87** | **7** |
| Method marks credited, A1 withheld | 2/3 | 2/3 | 2/3 | **77/87** | **10** |
| No working = no marks | 0/3 | 0/3 | 0/3 | **71/87** | **16** |

Resolved deductions common to every reading:

| Item | Award | Reason |
|---|---|---|
| Q13 | 2/3 | Both expansion method marks earned; final line is not `2x^2 + 19x + 24` (reads `x^2 + 12x + 9 − 2x^2 + 7x + 15`, margin `3x^2 …`). Confidence medium. |
| Q21 | 1/2 | Correct partial expansion `4n(n^2 + 2n − 15)`; final written with wrong powers (`… 8n^3 … 60n^2`). Confidence medium. |
| Q23 | 2/3 | Both bracket stages correct to `(x + 2)(2x^2 − 11x − 21)`; final in box reads `2x^3 − 4x^2 …` (truncated), not `2x^3 − 7x^2 − 43x − 42`. Confidence medium. |
| Q26 | 2/3 | Final `20x^3 − 31x^2 − 84x − 18`; x-term should be `81x`. Confidence high. |
| Q37b | 0/3 | Answer `a^5 b^2`; correct is `a^3 b^2`. Confidence high. |

Q36 is **3/3** in this scan: the answer is `3x^3 + 34x^2 + 84x − 72`, and the scheme states a correct answer scores full marks. The historical reference awarded 2/3 on a misread `86x`.

## 3. The likely reconciliation

`91 printed marks − 80 awarded = 11 marks lost.`

That is exactly the user's figure, and it **includes the 4 marks attached to the two excluded items** (Q12 2 + Q16d 2). Under this reading the eligible loss is **7 marks (80/87)**, not 11.

This is a direct conflict with the instruction *"Total eligible marks − manually awarded marks = 11"* after the mandatory exclusions. The brief requires this discrepancy to be raised rather than silently forced.

## 4. Consequence for the experiment

Criterion-level precision, recall, F1, false awards, false deductions and item agreement all depend on the per-item award vector, not only on the total. Three items (Q30, Q31, Q34) are genuinely undecidable from the scheme plus the scan because the scheme's "Working required" condition is applied differently by different examiners. The scanned paper contains no teacher annotation to settle it.

Until the basis is confirmed:

- no strategy is executed;
- no reference is declared final;
- the draft reference (`reference/GROUND_TRUTH_DRAFT.json`) keeps Q30, Q31 and Q34 as `pending_policy`;
- all other items are recorded with evidence and confidence, including the medium-confidence Q13/Q21/Q23 readings.

## 5. Files preserved

- `source/Ch2 L3.pdf`, `source/Ch2L3MS- Simplifying Expressions.pdf` — untouched originals.
- `inputs/student_p01…p07.png` (1240×1755), `inputs/scheme_p01…p21.png` (1540×1190) — clean model inputs; footer teacher name and scanner watermark redacted exactly as in the historical convention; no student working altered.
- `metadata.json` — page hashes, source hashes, redaction boxes.
- `reference/GROUND_TRUTH_DRAFT.json` — criterion-level draft with the three pending items flagged.

## 6. Reference band (user instruction, 2026-11-05)

The user directed that 76 be treated as a range, because a human marker can also err.

- Primary band: **74–78** (centre 76, ±2 marks on 87).
- Exact 76 is still recorded per attempt, but "paper-total agreement" in the final test means inside 74–78.
- Flagged items with a plausible alternative award: Q13 2/3, Q21 1/2, Q23 1/2, Q26 2/3, Q30 2/3, Q31 2/3, Q34 2/3. Their combinatorial envelope is 70–83; it is recorded for transparency and is not the headline verdict.
- Criterion F1 is measured against the central vector; the band applies to the paper total. A disagreement on a flagged item is reported separately rather than treated as an absolute error.

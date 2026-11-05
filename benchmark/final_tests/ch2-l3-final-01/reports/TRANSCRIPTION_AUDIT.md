# Transcription audit

Paper: **ch2-l3-final-01**. Compares each attempt's reported student answer with
the visible answer in the scan.

- `exact`: normalized string or SymPy-equivalent to the student's visible answer.
- `different`: neither blank nor equivalent — a material misread or a genuine
  difference in the student's written answer.
- `unknown`: the expression could not be parsed; Q13, Q21 and Q23 are messy or
  truncated in the scan, and their expected strings in `STUDENT_ANSWERS.json`
  include source annotations.
- `blank`: the strategy reported no answer where the scan has one.
- `missing_item`: the attempt did not return that item at all.

## Summary

| Attempt | Exact | Different | Unknown | Blank | Missing | Main findings |
|---|---|---|---|---|---|---|
| A1 | 0 | 0 | 0 | 0 | 38 | failed request; not a transcription measurement |
| A2 | 31/38 | 4 | 3 | 0 | 0 | Q1a `24→84`; Q2 `10p→6p`; Q26 `x^3→x^2`, `84x→84`; Q37b `a^5b^2→9a^3b^2` |
| B1 | 18/38 | 0 | 4 | 3 | 13 | Q7, Q8, Q19 blank; Q26–Q37a and Q37b never returned |
| C1 | 34/38 | 1 | 3 | 0 | 0 | Q32 `+10x^2→−10x^2` |

The material transcription errors explain several marking losses:

- **A2:** Q1a and Q2 were marked 0 because the model read the wrong coefficient
  (`24→84`, `10p→6p`); Q26 lost a mark after `20x^3` was read as `20x^2` and
  `84x` as `84`; Q37b's `a^5b^2` became `9a^3b^2`.
- **B1:** Q7, Q8 and Q19 were marked blank because the per-page transcription
  returned an empty answer. Q26–Q37a and Q37b were never returned because the
  run stopped at 25 items. These are extraction/coverage losses, not marking-rule
  losses.
- **C1:** Q32's sign error (`+10x^2` read as `−10x^2`) triggered the SymPy
  escalation that reduced the mark from 2 to 1. This is the clearest case of a
  transcription error causing a harmful escalation.

Q13, Q21 and Q23 are flagged `unknown` in several attempts because the scan is
messy or truncated; treat those rows as source ambiguity, not as confirmed model
errors. A1's 38 `missing_item` rows are the failed whole-paper request.

## Full table

| Strategy | Run | Item | Status | Expected (student) | Reported |
|---|---|---|---|---|---|
| A | 1 | 1a | missing_item | 24 - 18y |  |
| A | 1 | 1d | missing_item | y^2 + 8y - 20 |  |
| A | 1 | 2 | missing_item | 10p - 15 |  |
| A | 1 | 3 | missing_item | x^2 + 4x - 5 |  |
| A | 1 | 4 | missing_item | t^2 + t - 20 |  |
| A | 1 | 5 | missing_item | x^2 + 2x |  |
| A | 1 | 6 | missing_item | 24x |  |
| A | 1 | 7 | missing_item | x^2 - 7x - 18 |  |
| A | 1 | 8 | missing_item | 8y^2 + 10y - 3 |  |
| A | 1 | 9 | missing_item | 10x + 22 |  |
| A | 1 | 10 | missing_item | 8y - 2 |  |
| A | 1 | 11 | missing_item | 24x - 9 |  |
| A | 1 | 13 | missing_item | x^2 + 12x + 9 - 2x^2 + 7x + 15 (margin; not 2x^2 + 19x + 24) |  |
| A | 1 | 14 | missing_item | k^2 + 4k - 45 |  |
| A | 1 | 15 | missing_item | 12p + 15 |  |
| A | 1 | 16b | missing_item | 2p^2 - 3p |  |
| A | 1 | 17 | missing_item | x^2 - 3x - 18 |  |
| A | 1 | 18 | missing_item | 2x^3 - 5x^2 - 28x + 15 |  |
| A | 1 | 19 | missing_item | 3x^2 + 5xy - 12y^2 |  |
| A | 1 | 20 | missing_item | e^2 - 2e - 15 |  |
| A | 1 | 21 | missing_item | 4n^3 + 8n^3 - 60n^2 (as written; wrong powers) |  |
| A | 1 | 22 | missing_item | x^2 + 7x - 18 |  |
| A | 1 | 23 | missing_item | 2x^3 - 4x^2 ... (truncated/wrong) |  |
| A | 1 | 24 | missing_item | m^2 - 3m - 40 |  |
| A | 1 | 25 | missing_item | x^2 - 3x - 10 |  |
| A | 1 | 26 | missing_item | 20x^3 - 31x^2 - 84x - 18 |  |
| A | 1 | 27 | missing_item | 2x^3 - 16x^2 + 30x |  |
| A | 1 | 28 | missing_item | x^3 + 3x^2 - 6x - 8 |  |
| A | 1 | 29 | missing_item | 2x^2 + 29x |  |
| A | 1 | 30 | missing_item | 24x^3 - 28x^2 - 12x |  |
| A | 1 | 31 | missing_item | 8x^3 - 28x^2 - 60x |  |
| A | 1 | 32 | missing_item | 15x^3 + 10x^2 - 40x |  |
| A | 1 | 33 | missing_item | 3n^3 - 7n^2 - 20n |  |
| A | 1 | 34 | missing_item | 12x^3 - 60x^2 + 75x |  |
| A | 1 | 35 | missing_item | 30x^3 + 25x^2 - 20x |  |
| A | 1 | 36 | missing_item | 3x^3 + 34x^2 + 84x - 72 |  |
| A | 1 | 37a | missing_item | -3x^3 - 7x^2 + 22x + 8 |  |
| A | 1 | 37b | missing_item | a^5 b^2 |  |
| A | 2 | 1a | different | 24 - 18y | 84 - 18y |
| A | 2 | 2 | different | 10p - 15 | 6p - 15 |
| A | 2 | 13 | unknown | x^2 + 12x + 9 - 2x^2 + 7x + 15 (margin; not 2x^2 + 19x + 24) | -x^2 + 5x + 24 |
| A | 2 | 21 | unknown | 4n^3 + 8n^3 - 60n^2 (as written; wrong powers) | 4n^3 + 8n^2 - 60n^2 |
| A | 2 | 23 | unknown | 2x^3 - 4x^2 ... (truncated/wrong) | 2x^3 - 14x^2... |
| A | 2 | 26 | different | 20x^3 - 31x^2 - 84x - 18 | 20x^2 - 31x^2 - 84 - 18 |
| A | 2 | 37b | different | a^5 b^2 | 9 a^3 b^2 |
| B | 1 | 6 | unknown | 24x | = 24x |
| B | 1 | 7 | blank | x^2 - 7x - 18 |  |
| B | 1 | 8 | blank | 8y^2 + 10y - 3 |  |
| B | 1 | 13 | unknown | x^2 + 12x + 9 - 2x^2 + 7x + 15 (margin; not 2x^2 + 19x + 24) | -x^2 + 5x + 24 |
| B | 1 | 19 | blank | 3x^2 + 5xy - 12y^2 |  |
| B | 1 | 21 | unknown | 4n^3 + 8n^3 - 60n^2 (as written; wrong powers) | 4n^3 + 8n^2 - 60n |
| B | 1 | 23 | unknown | 2x^3 - 4x^2 ... (truncated/wrong) | 2x^3 - 14x^2 |
| B | 1 | 26 | missing_item | 20x^3 - 31x^2 - 84x - 18 |  |
| B | 1 | 27 | missing_item | 2x^3 - 16x^2 + 30x |  |
| B | 1 | 28 | missing_item | x^3 + 3x^2 - 6x - 8 |  |
| B | 1 | 29 | missing_item | 2x^2 + 29x |  |
| B | 1 | 30 | missing_item | 24x^3 - 28x^2 - 12x |  |
| B | 1 | 31 | missing_item | 8x^3 - 28x^2 - 60x |  |
| B | 1 | 32 | missing_item | 15x^3 + 10x^2 - 40x |  |
| B | 1 | 33 | missing_item | 3n^3 - 7n^2 - 20n |  |
| B | 1 | 34 | missing_item | 12x^3 - 60x^2 + 75x |  |
| B | 1 | 35 | missing_item | 30x^3 + 25x^2 - 20x |  |
| B | 1 | 36 | missing_item | 3x^3 + 34x^2 + 84x - 72 |  |
| B | 1 | 37a | missing_item | -3x^3 - 7x^2 + 22x + 8 |  |
| B | 1 | 37b | missing_item | a^5 b^2 |  |
| C | 1 | 13 | unknown | x^2 + 12x + 9 - 2x^2 + 7x + 15 (margin; not 2x^2 + 19x + 24) | -x^2 + 5x + 24 |
| C | 1 | 21 | unknown | 4n^3 + 8n^3 - 60n^2 (as written; wrong powers) | 4n^3 + 8n^2 - 60n |
| C | 1 | 23 | unknown | 2x^3 - 4x^2 ... (truncated/wrong) | 2x^3 - 14x^2... |
| C | 1 | 32 | different | 15x^3 + 10x^2 - 40x | 15x^3 - 10x^2 - 40x |

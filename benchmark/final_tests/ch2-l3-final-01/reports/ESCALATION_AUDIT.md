# Escalation audit — C1

Paper: **ch2-l3-final-01** · Strategy C, run 1 (complete, 38/38 items).

Every recorded escalation that changed a mark is compared with the user-ruled
reference. `Error` is `|awarded − expected|` at the item level. `Harmful` means
the change **increased** that item's absolute error, not merely that the item was
already wrong before the change.

| Item | Before | After | Reference | Error before | Error after | Effect | Reason |
|---|---|---|---|---|---|---|---|
| Q32 | 2 | 1 | 3 | 1 | 2 | **harmful** (+1 error) | SymPy says the transcribed answer differs from the scheme's expected answer |
| Q37b | 1 | 0 | 0 | 1 | 0 | correct (−1 error) | SymPy says the transcribed answer differs from the scheme's expected answer |

## Net effect

- Score before escalation: **79** (Q32 2 + Q37b 1).
- Score after escalation: **78** (Q32 1 + Q37b 0).
- Net score change: **−1**; net absolute item error: **2 → 2**.
- Band consequence: 79 is outside the 74–78 band (+3); 78 is inside the band at
  its upper edge (+2). The escalation therefore changed the **band outcome** but
  did not improve aggregate criterion accuracy.
- The Q32 change was caused by a transcription sign error (`+10x^2` read as
  `−10x^2`), not by a disagreement about the marking rule. The model then applied
  the SymPy escalation and reduced the mark from 2 to 1, moving further from the
  reference 3.
- The Q37b change corrected an over-award: the student wrote `a^5b^2`, not the
  correct `a^3b^2`, so the reference is 0.

## Completeness

- C1 made **11 escalation requests**: 6 failed, 5 successful.
- **2** escalations changed a mark; the rest made no change or failed.
- All requests are recorded in `results/API_USAGE.jsonl` with
  `purpose=escalation`, `strategy=c`, `run=1`; no silent retries and no
  unlogged escalation.
- C1's final 38-item payload contains no unresolved item and no invalid response.

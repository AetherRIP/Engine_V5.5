# Recommendation

> Provisional. The reference is not teacher-certified and the sample is one paper.

## Decision rule

Accuracy is a constraint, not a trade-off. A strategy is eligible only if it returned
every scoreable item, reached the reference paper total exactly in at least one run,
and its criterion F1 was at least as high as the best strategy. Among eligible
strategies, the lowest cost per correctly assessed paper wins; request count alone
never decides.

## Measured result

- Strategy A: criterion F1 0.95, coverage 100.00%, paper scores 77, 72 (max 87; candidate reference 80), 0 strictly correct run(s), 2 requests, cost USD 0.070251.
- Strategy B: criterion F1 0.96, coverage 100.00%, paper scores 74, 74 (max 87; candidate reference 80), 0 strictly correct run(s), 33 requests, cost USD 0.191967.
- Strategy C: criterion F1 0.99, coverage 100.00%, paper scores 78, 82 (max 87; candidate reference 80), 0 strictly correct run(s), 23 requests, cost USD 0.151344.

## Recommendation

**No strategy met the strict bar.** None returned an exact paper score with full coverage in either run, so no packaging can be called production-ready on this evidence.

The closest aggregate result is **strategy C** (attempt `c-rerun-20261103T140743Z`): criterion F1 0.99, coverage 100.00%, scores 78 / 82 against a maximum of 87 and a candidate reference of 80, false awards 1. C's current attempt is a valid whole-document/Lite measurement with 0 raw `different` checks. Re-evaluating the preserved C5/C6 inputs with the fixed classifier recovers 6 genuine differences (C5 4, C6 2); offline replay of those plus 4 historical C1/C2 differences has pre-fix 0 escalation(s) and gap True, versus fixed 10 escalation(s) and gap False. This replay is offline, not a live run. Full-document post-C5/C6 live attempts C9–C13 were provider-blocked by HTTP 503/timeouts before any escalation request could complete.

**Architecture recommendation:** do not adopt C as a validated specialist pipeline on this sample: its measured scores are close but not exact, and the escalation branch is exercised in a targeted live single-item case, but not across a fresh complete C run. Any future C must add an independent image-grounded transcription check and a full live C pairing and a transcription-fidelity check. The replay is derived from preserved raw inputs; no raw C file was rewritten, and no live API call was made for it. A separate targeted live escalation on C5 Q30 changed 1 to 2 using `gemini-3.6-flash`; it is real live evidence, but not a fresh full-paper C run. B is the lower-risk baseline only after its blank-extraction defect is fixed and a non-empty check is added; it had no false awards. A now has 2 complete recorded run(s) (runs 2, 3), covering all scoreable items; no split was required.

## What would change it

- A teacher-certified reference that moves the criterion F1 or false-award ordering.
- A larger sample where A's completeness or B's extraction loss changes materially.
- Live evidence that C's escalation stage fires, and that transcription fidelity checks catch
  its corrected-answer hallucinations.
- A provider price or quota change larger than the measured cost gap.

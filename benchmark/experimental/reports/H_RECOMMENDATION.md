# Strategy H — recommendation

> Candidate reference, one paper, 38 items. Every accuracy figure is provisional.

## Decision rule (fixed before the result)

Accuracy is a constraint. A configuration is eligible only if it covers every scoreable
item, has no unresolved item and no invalid response, and improves criterion F1 over A
without approaching C-only cost. Among eligible configurations the lowest cost per unit of
improvement wins, and any item it damages is reported even if the aggregate improves.

## Measured outcome

| Configuration | Paper /87 | Criterion F1 | Requests | Cost / submission |
|---|---|---|---|---|
| A-only | 77, 72 | 0.9479 | 2 | $0.035126 |
| C-only | 78, 82 | 0.9875 | 23 | $0.075672 |
| H-low | 77, 74 | 0.9582 | 4 | $0.038582 |
| H-medium | 75, 74 | 0.9644 | 8 | $0.045353 |
| H-high | 78, 78 | 0.9873 | 15 | $0.057159 |

## The seven questions

**1. Does selective escalation improve A's accuracy?**
On this paper, yes at every tier on criterion F1: +0.0103 (low), +0.0165 (medium),
+0.0394 (high). At the paper-total level it improves for low (+1.0 mark mean) and high
(+3.5), but **not** for medium (0.0, because medium degraded A2 from 77 to 75 while
fixing two A3 items).

**2. How much additional accuracy?**
H-high: criterion F1 0.9479 → 0.9873 (+4.16% relative), item exact 86.85% → 94.74%
(+7.9 pp), false deductions 13 → 4, false awards 2 → 0. That is not an exact paper:
78/87 in both runs against a reference of 80. Total-mark error is still 2 per run.
H-low, the cheapest: F1 +1.09% relative, +1 mark mean.

**3. What is the additional cost per submission?**
+$0.00346 (H-low), +$0.01023 (H-medium), +$0.02203 (H-high) against A's $0.03513.
C-only costs +$0.04055. H-high therefore sits at **75.5% of C's cost** and **65% of C's
requests** (15 vs 23) while matching C's criterion F1 to 0.0002.

**4. What percentage of criteria require escalation?**
2.6% (2/76) for H-low, 7.9% (6/76) for H-medium, 17.1% (13/76) for H-high. Every
submission had at least one escalated item, so "100% of submissions escalated" is true but
uninformative: the policy is selective at criterion level, not submission level.

**5. Which escalation policy offers the best trade-off?**
**H-high**, on cost per unit of accuracy: $0.00559 per +0.01 F1 versus $0.00620 for
H-medium and $0.01024 for C-only; $0.00630 per extra mark versus $0.00737 for C.
**H-low** is the cheapest configuration that improves anything ($0.00336 per +0.01 F1,
+9.8% cost) and it damaged nothing on this paper, but its gain is one item.

**6. Is the hybrid genuinely better than A-only and C-only?**
- Better than **A-only**: yes on criterion accuracy, with overlapping item-level bootstrap
  intervals on A2 (H-high ΔF1 CI [−0.0092, 0.0767]) and non-overlapping zero only on A3.
  The gain is real in direction but not established at this sample size, and it is
  concentrated in Q23 (+6 of the +7 net marks) plus four other items.
- Better than **C-only**: no, not on accuracy. C's mean total is 80, H-high's is 78. H-high
  is a **better cost/accuracy point** (same F1, ~25% cheaper, fewer requests), not a more
  accurate marker. C also over-awards Q26/Q30; H-high under-awards Q31/Q36. They fail
  differently.
- So: H-high is a genuinely better *trade-off*, not a genuinely better *marker*.

**7. Is there sufficient evidence to recommend it for V5 production?**
**No.** Four independent reasons:

1. One paper, one student, 38 items. The paired bootstrap intervals include zero on one
   of the two base runs for every policy.
2. The reference is candidate-only. Two of the eight escalations (Q31, Q36) disagree with
   it, and a teacher could plausibly side with either the escalation or the reference.
3. The policy is not monotonic. More signals made things worse (H-medium < H-low on totals).
   A production threshold cannot be justified from one paper without a calibration set,
   and there is no second document to calibrate on.
4. The gain is one item deep. H-high's headline is mostly Q23; if a future paper has no
   Q23-shaped error, the same policy spends 17% of criteria to gain little.

## Recommendation

**Do not integrate Strategy H into MathChecker V5 production.** Keep A as the production
baseline and keep the experiment as a preserved artifact.

If the hybrid line is continued, the evidence supports this order of work:

1. **Teacher-certify the reference and add ≥10 papers with a real calibration/holdout
   split.** Freeze thresholds on the calibration split only; report on the holdout. Without
   this, no threshold choice is defensible.
2. **Fix the two demonstrated failure modes before any accuracy claim:**
   - never let an escalation lower a full-marks award without a second independent
     confirmation (Q31);
   - treat a changed award whose absolute error is unchanged as a review case, not an
     improvement (Q36).
3. **Restrict broad divergence (S8) to items where a marks-level contradiction exists.**
   Escalating every answer that differs from the printed answer is what pulled in Q31 and
   produced most of H-high's 17% escalation rate.
4. **Keep the validation gate, but do not mistake it for a correctness check.** It caught
   nothing live because nothing was malformed; it cannot catch a wrong mark. Pair it with
   one independent signal (a second re-mark, or a deterministic check of the final answer)
   before a mark is replaced.
5. **Keep the request hygiene that worked:** one item per request, two page images, no
   document re-upload, one stored response reused across policies, bounded retries, stop
   after two consecutive provider failures. That part is production-shaped and cheap
   (~$0.0034 per escalation, 3.7 s mean latency, one 503 retried successfully).

## What would change this recommendation

- A teacher-certified reference that confirms Q23/Q21/Q28/Q30/Q32 and disputes Q31/Q36 —
  that would raise H's measured gain and strengthen the case.
- A multi-paper holdout where H-high keeps its F1 advantage over A and stays near C at
  lower cost, with no full-marks degradation.
- A cheaper or more reliable escalation check (text-only on a cached scheme representation)
  that removes the 2.6k-token image cost per item without losing the narrow-context gain.
- Evidence that C's own over-awards (Q26/Q30) can be removed, which would make C the
  accuracy leader again and change the trade-off calculus.

## What must not be concluded from this experiment

- That H is production-ready.
- That escalation is safe because validation passed.
- That the measured +4.16% F1 is statistically significant.
- That thresholds tuned on this paper would transfer to another paper.

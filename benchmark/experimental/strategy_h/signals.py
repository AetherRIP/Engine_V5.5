"""Deterministic escalation signals for Strategy H.

Every signal is computed locally from Strategy A's own criterion-level output plus the
printed scheme.  No signal reads a reference mark, and no signal calls a provider.

Design rules:

* a signal needs a stated, checkable reason; "the model feels unsure" is not one;
* an unparseable answer produces ``unknown`` from SymPy and therefore no signal, so
  formatting is never mistaken for a marking contradiction;
* model-reported confidence is only reachable through the high policy, and only after
  the calibration check in ``ESCALATION_ANALYSIS.md`` showed it carries no information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ...code import verifier
from . import evidence as scheme
from .config import SIGNAL_LABEL, SIGNAL_SEVERITY, PolicyConfig

_CODE_PATTERN = re.compile(r"(M1|M2|A1|A2|B1|B2)")
_FLAG_TOKENS = ("ambig", "illegib", "mismatch")


def normalise_code(code: object) -> str:
    """Mirror ``evaluator._normalize_code`` so signal and score agree on a label."""
    text = str(code or "").strip().upper().replace("DEP", "")
    match = _CODE_PATTERN.search(text)
    return match.group(1) if match else text


@dataclass(frozen=True)
class Signal:
    code: str
    detail: str

    @property
    def severity(self) -> int:
        return SIGNAL_SEVERITY.get(self.code, 1)

    @property
    def label(self) -> str:
        return SIGNAL_LABEL.get(self.code, self.code)

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "label": self.label, "detail": self.detail}


@lru_cache(maxsize=256)
def _equivalent(answer: str, expected: str) -> dict:
    return verifier.equivalent(answer, expected)


def answer_check(item: dict) -> dict:
    """SymPy comparison of A's transcribed answer with the printed answer."""
    answer = str(item.get("student_answer") or "").strip()
    expected = scheme.expected_answer(str(item.get("id")))
    if not answer or not expected:
        return {"status": "unknown", "detail": "empty side"}
    return _equivalent(answer, expected)


def detect(item: dict, *, include_confidence: bool = False,
           confidence_threshold: float = 0.80,
           check: dict | None = None) -> list[Signal]:
    """Return every signal the item fires, regardless of policy."""
    signals: list[Signal] = []
    max_marks = int(item.get("max_marks") or 0)
    awarded = int(item.get("awarded") or 0)
    criteria = [c for c in (item.get("criteria") or []) if isinstance(c, dict)]
    codes = [normalise_code(c.get("code")) for c in criteria]
    answer = str(item.get("student_answer") or "").strip()
    complete_criteria = len(criteria) == max_marks and max_marks > 0

    # S1 — structure.  Repeated codes are legitimate (a question can print two M1
    # marks), so a duplicate label is never treated as a structural failure; the
    # printed order is what pairs criteria with the reference.
    if len(criteria) != max_marks:
        signals.append(Signal("S1_structure",
                              f"{len(criteria)} criteria returned for {max_marks} marks"))
    elif any(not code for code in codes):
        signals.append(Signal("S1_structure", "a criterion has an empty code"))
    if awarded < 0 or awarded > max_marks:
        signals.append(Signal("S1_structure", f"awarded {awarded} outside 0..{max_marks}"))

    # S2 — evidence gap.  A positive mark must rest on something transcribed.
    if awarded > 0 and not answer:
        signals.append(Signal("S2_evidence_gap",
                              f"{awarded} mark(s) with no transcribed student answer"))

    # S3 — aggregation coherence.
    if complete_criteria:
        true_count = sum(1 for criterion in criteria if criterion.get("awarded"))
        if true_count != awarded:
            signals.append(Signal("S3_aggregation",
                                  f"awarded {awarded} but {true_count} criteria awarded"))

    # S4 — marking-logic contradictions.
    accuracy = [c for c in criteria
                if normalise_code(c.get("code")).startswith(("A", "B"))]
    method = [c for c in criteria if normalise_code(c.get("code")).startswith("M")]
    if max_marks > 1 and accuracy and method:
        if any(c.get("awarded") for c in accuracy) and not any(
                c.get("awarded") for c in method):
            signals.append(Signal("S4a_accuracy_without_method",
                                  "accuracy mark awarded with no method mark"))
    if complete_criteria:
        if awarded == max_marks and any(not c.get("awarded") for c in criteria):
            signals.append(Signal("S4b_full_marks_with_unawarded",
                                  "full marks with an unawarded criterion"))
        if awarded < max_marks and all(c.get("awarded") for c in criteria):
            signals.append(Signal("S4c_partial_with_all_awarded",
                                  f"{awarded}/{max_marks} with every criterion awarded"))

    # S5 / S8 — deterministic answer contradiction.
    check = check if check is not None else answer_check(item)
    status = str(check.get("status"))
    if status == "equivalent" and awarded < max_marks:
        signals.append(Signal(
            "S5a_under_award_contradiction",
            f"answer matches the printed answer but {awarded}/{max_marks} awarded"))
    if status == "different" and awarded == max_marks:
        signals.append(Signal(
            "S5b_over_award_contradiction",
            f"answer {answer!r} differs from the printed answer but full marks awarded"))
    if status == "different":
        signals.append(Signal("S8_broad_answer_divergence",
                              f"answer {answer!r} differs from the printed answer"))

    # S6 — model-reported flags, tied to a named reason.
    flags = " ".join(str(flag) for flag in (item.get("flags") or [])).lower()
    for token in _FLAG_TOKENS:
        if token in flags:
            signals.append(Signal("S6_model_flag", f"flag contains {token!r}"))
            break

    # S7 — model-reported confidence, only for the policy that opts in.
    if include_confidence:
        confidence = item.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < confidence_threshold:
            signals.append(Signal(
                "S7_low_confidence",
                f"confidence {confidence} below {confidence_threshold}"))

    return signals


def evaluate(items: dict[str, dict], policy_config: PolicyConfig) -> dict[str, list[Signal]]:
    """Return the policy-eligible signals per item (empty list = no escalation)."""
    out: dict[str, list[Signal]] = {}
    for item_id, item in items.items():
        check = answer_check(item)
        all_signals = detect(
            item,
            include_confidence="S7_low_confidence" in policy_config.signals,
            confidence_threshold=policy_config.confidence_threshold,
            check=check,
        )
        out[item_id] = [signal for signal in all_signals
                        if signal.code in policy_config.signals]
    return out


def select(items: dict[str, dict], policy_config: PolicyConfig,
           item_order: list[str]) -> dict:
    """Choose the items to escalate: dedupe, severity order, then the frozen cap.

    Returns ``{"selected": [...], "signals": {...}, "suppressed": [...]}`` where each
    selected entry carries the item id, the primary reason and every eligible signal.
    """
    per_item = evaluate(items, policy_config)
    order = {item_id: index for index, item_id in enumerate(item_order)}
    candidates = []
    for item_id, signals in per_item.items():
        if not signals:
            continue
        top = max(signal.severity for signal in signals)
        candidates.append((-top, order.get(item_id, 10_000), item_id, signals))
    candidates.sort(key=lambda entry: (entry[0], entry[1]))

    selected = []
    suppressed = []
    for _severity, _order, item_id, signals in candidates:
        entry = {
            "item": item_id,
            "reason": sorted(signals, key=lambda s: -s.severity)[0].code,
            "signals": [signal.as_dict() for signal in signals],
        }
        if len(selected) < policy_config.max_escalations:
            selected.append(entry)
        else:
            suppressed.append(entry)

    return {
        "selected": selected,
        "suppressed": suppressed,
        "signals": {item_id: [signal.as_dict() for signal in signals]
                    for item_id, signals in per_item.items() if signals},
        "candidate_count": len(candidates),
        "cap": policy_config.max_escalations,
    }

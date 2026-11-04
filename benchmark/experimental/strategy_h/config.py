"""Frozen escalation policies for Strategy H.

The thresholds and signal sets were written before Strategy H produced any accuracy
number (see ``benchmark/experimental/PLAN.md``).  Changing them now would invalidate the
experiment, so they are plain data and not derived from the evaluation labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Severity used only for deterministic ordering when the cap bites.
#: 3 = integrity failure, 2 = deterministic contradiction, 1 = soft/model-reported.
SIGNAL_SEVERITY = {
    "S1_structure": 3,
    "S2_evidence_gap": 3,
    "S3_aggregation": 3,
    "S4a_accuracy_without_method": 2,
    "S4b_full_marks_with_unawarded": 3,
    "S4c_partial_with_all_awarded": 2,
    "S5a_under_award_contradiction": 2,
    "S5b_over_award_contradiction": 2,
    "S6_model_flag": 1,
    "S7_low_confidence": 1,
    "S8_broad_answer_divergence": 1,
}

#: Human-readable reason per signal, used in the audit trail and the report.
SIGNAL_LABEL = {
    "S1_structure": "criterion structure does not match the printed maximum",
    "S2_evidence_gap": "marks awarded with no transcribed student answer",
    "S3_aggregation": "awarded total disagrees with the criteria awarded",
    "S4a_accuracy_without_method": "accuracy mark awarded while no method mark is",
    "S4b_full_marks_with_unawarded": "full marks awarded while a criterion is unawarded",
    "S4c_partial_with_all_awarded": "partial total while every criterion is awarded",
    "S5a_under_award_contradiction": "answer matches the printed answer but full marks were not awarded",
    "S5b_over_award_contradiction": "answer differs from the printed answer but full marks were awarded",
    "S6_model_flag": "model flagged ambiguity, illegibility or a scheme mismatch",
    "S7_low_confidence": "model-reported confidence below the frozen threshold",
    "S8_broad_answer_divergence": "transcribed answer diverges from the printed answer",
}


@dataclass(frozen=True)
class PolicyConfig:
    name: str
    description: str
    signals: frozenset[str]
    max_escalations: int
    confidence_threshold: float = 0.80
    max_attempts: int = 2
    max_consecutive_provider_failures: int = 2
    uses_model_confidence: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


_INTEGRITY = frozenset({"S1_structure", "S2_evidence_gap", "S3_aggregation"})
_CONTRADICTION = frozenset({
    "S4a_accuracy_without_method",
    "S4b_full_marks_with_unawarded",
    "S4c_partial_with_all_awarded",
    "S5a_under_award_contradiction",
    "S5b_over_award_contradiction",
    "S6_model_flag",
})

POLICIES: dict[str, PolicyConfig] = {
    "h-low": PolicyConfig(
        name="h-low",
        description="Conservative: escalate only structural and evidence integrity failures.",
        signals=_INTEGRITY,
        max_escalations=3,
        notes=("No marking-judgement signal is used.",),
    ),
    "h-medium": PolicyConfig(
        name="h-medium",
        description=(
            "Moderate and rule-based: residual integrity failures plus deterministic "
            "marking contradictions. No model-reported confidence."
        ),
        signals=_INTEGRITY | _CONTRADICTION,
        max_escalations=6,
        notes=("This is the confidence-free rule-based configuration.",),
    ),
    "h-high": PolicyConfig(
        name="h-high",
        description=(
            "Aggressive: every deterministic contradiction plus model flags and any "
            "algebraic divergence from the printed answer."
        ),
        signals=_INTEGRITY | _CONTRADICTION | {"S7_low_confidence",
                                              "S8_broad_answer_divergence"},
        max_escalations=8,
        uses_model_confidence=True,
        notes=(
            "Uses uncalibrated model confidence; treated as a negative control.",
            "Broad divergence escalates correct partial marking as well as errors.",
        ),
    ),
}

POLICY_ORDER = ("h-low", "h-medium", "h-high")


def policy(name: str) -> PolicyConfig:
    try:
        return POLICIES[name]
    except KeyError as error:  # pragma: no cover - caller error, not a measurement
        raise KeyError(f"unknown Strategy H policy {name!r}") from error

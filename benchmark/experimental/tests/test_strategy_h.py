"""Offline tests for Strategy H (no network, no key, no quota).

The base run is a synthetic Strategy A result built from the printed-scheme evidence, so
a test can create exactly the signal it needs.  Escalation responses come from a fake
executor; nothing here calls a provider.
"""

from __future__ import annotations

import copy
import json

import pytest

from benchmark.code import evaluator, ground_truth, loader
from benchmark.code.execution import ModelSelection
from benchmark.code.provider import ProviderResult
from benchmark.experimental.strategy_h import config as hconfig
from benchmark.experimental.strategy_h import evaluate as heval
from benchmark.experimental.strategy_h import evidence as scheme
from benchmark.experimental.strategy_h import runner as hrunner
from benchmark.experimental.strategy_h import signals as signal_mod

MODELS = ModelSelection(primary="fake-primary", lite="fake-lite", strong="fake-strong")


def _truth() -> dict[str, dict]:
    return {str(item["id"]): item for item in ground_truth.load()["items"]
            if item["status"] == "scored"}


def _a_item(item_id: str) -> dict:
    truth = _truth()[item_id]
    answer = scheme.expected_answer(item_id)
    return {
        "id": item_id,
        "student_answer": answer if truth["expected_mark"] == truth["max_marks"] else "0",
        "awarded": truth["expected_mark"],
        "max_marks": truth["max_marks"],
        "criteria": [{"code": c["code"], "awarded": c["awarded"], "reason": "printed"}
                     for c in truth["criteria"]],
        "confidence": 1.0,
        "flags": [],
        "reason": "consistent with the printed scheme",
        "source": "primary",
    }


def _base_items() -> list[dict]:
    return [_a_item(item_id) for item_id in loader.item_ids()]


def _base_run(items: list[dict] | None = None, run: int = 2) -> dict:
    return {
        "strategy": "a", "run": run,
        "models": MODELS.as_dict(),
        "items": items if items is not None else _base_items(),
        "request_count": 1, "invalid_responses": 0, "errors": [],
        "verification": {}, "escalations": [], "completion_status": "complete",
    }


def _payload(item_id: str, awarded: int | None = None, *, answer: str = "worked answer",
             correct: bool = False) -> dict:
    truth = _truth()[item_id]
    awarded = truth["expected_mark"] if awarded is None else awarded
    if correct:
        criteria = [{"code": c["code"], "awarded": c["awarded"], "reason": "re-marked"}
                    for c in truth["criteria"]]
    else:
        criteria = [{"code": f"c{index}", "awarded": index < awarded, "reason": "re-marked"}
                    for index in range(truth["max_marks"])]
    return {"items": [{
        "id": item_id, "awarded": awarded, "max_marks": truth["max_marks"],
        "student_answer": answer, "criteria": criteria, "confidence": 1.0, "flags": [],
    }]}


class FakeExecutor:
    def __init__(self, responses: dict | None = None, *, fail: bool = False):
        self.responses = responses or {}
        self.fail = fail
        self.calls: list[dict] = []
        self.ledger = None

    def call(self, *, strategy, run, batch, purpose, model, parts, system, schema,
             item_ids, escalated=False, max_attempts=3):
        self.calls.append({"batch": batch, "item": item_ids[0], "purpose": purpose,
                           "model": model})
        if self.fail:
            return ProviderResult(status="http_error", http_status=503,
                                  error_code="UNAVAILABLE"), []
        payload = self.responses[item_ids[0]]
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return ProviderResult(status="ok", http_status=200, text=text, model=model,
                              usage={"input_tokens": 100, "output_tokens": 50,
                                     "reported": True}), []


def _perturb(items: list[dict], item_id: str, awarded: int) -> list[dict]:
    """Change only the total so the criterion list becomes inconsistent."""
    patched = copy.deepcopy(items)
    for item in patched:
        if item["id"] == item_id:
            item["awarded"] = awarded
    return patched


# ---------------------------------------------------------------- policy basics
def test_no_signal_means_no_escalation_and_no_request():
    executor = FakeExecutor()
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(), 1, hconfig.policy("h-low"))
    assert executor.calls == []
    assert result["request_count"] == 0
    assert result["escalations"] == []
    assert result["signal_summary"]["candidates"] == 0
    assert len(result["items"]) == 38


def test_one_criterion_escalates_once_and_is_applied():
    items = _perturb(_base_items(), "6", 1)  # 1 awarded but 2 criteria awarded
    executor = FakeExecutor({"6": _payload("6", correct=True)})
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(items), 1, hconfig.policy("h-low"))

    assert [call["item"] for call in executor.calls] == ["6"]
    assert result["escalations"] == ["6"]
    assert result["request_count"] == 1
    assert any(item["id"] == "6" and item["awarded"] == 3 for item in result["items"])


def test_multiple_criteria_escalate_independently():
    items = _perturb(_perturb(_base_items(), "6", 1), "26", 3)
    executor = FakeExecutor({"6": _payload("6", correct=True),
                             "26": _payload("26", correct=True)})
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(items), 1, hconfig.policy("h-medium"))

    assert sorted(call["item"] for call in executor.calls) == ["26", "6"]
    assert sorted(result["escalations"]) == ["26", "6"]
    assert all(call["purpose"] == "escalation" for call in executor.calls)


def test_invalid_json_keeps_strategy_a_result():
    items = _perturb(_base_items(), "6", 1)
    executor = FakeExecutor({"6": "{not json"})
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(items), 1, hconfig.policy("h-low"))

    assert result["escalations"] == []
    assert result["invalid_responses"] == 1
    escalated = next(item for item in result["items"] if item["id"] == "6")
    assert escalated["awarded"] == 1
    assert escalated["source"] == "primary"
    assert result["unresolved_for_review"][0]["item"] == "6"


def test_out_of_range_award_is_rejected():
    items = _perturb(_base_items(), "6", 1)
    executor = FakeExecutor({"6": _payload("6", 9)})
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(items), 1, hconfig.policy("h-low"))

    assert result["escalations"] == []
    escalated = next(item for item in result["items"] if item["id"] == "6")
    assert escalated["awarded"] == 1
    assert any("outside" in reason or "schema validation" in reason
               for reason in result["unresolved_for_review"][0]["detail"].split("; "))


def test_missing_evidence_is_rejected():
    items = _perturb(_base_items(), "6", 1)
    for item in items:
        if item["id"] == "6":
            item["student_answer"] = ""
    executor = FakeExecutor({"6": _payload("6", 2, answer="")})
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(items), 1, hconfig.policy("h-medium"))

    assert result["escalations"] == []
    assert any("no visible transcribed evidence" in reason
               for reason in result["unresolved_for_review"][0]["detail"].split("; "))


def test_duplicate_escalation_is_prevented_by_the_cache():
    items = _perturb(_base_items(), "6", 1)
    cache: dict = {}
    executor = FakeExecutor({"6": _payload("6", correct=True)})
    runner = hrunner.StrategyHRunner(executor, MODELS)

    first = runner.run(_base_run(items), 1, hconfig.policy("h-low"),
                       cache=cache, persist=lambda item_id, entry: None)
    second = runner.run(_base_run(items), 2, hconfig.policy("h-medium"), cache=cache)

    assert len(executor.calls) == 1
    assert first["request_count"] == 1
    assert second["request_count"] == 0
    assert second["reused_responses"] == 1
    assert second["escalations"] == ["6"]


def test_duplicate_item_in_a_response_is_rejected():
    items = _perturb(_base_items(), "6", 1)
    duplicate_id = {"items": [_payload("6", correct=True)["items"][0]] * 2}
    result = hrunner.StrategyHRunner(FakeExecutor({"6": duplicate_id}), MODELS).run(
        _base_run(items), 1, hconfig.policy("h-low"))
    assert result["escalations"] == []
    assert "schema validation" in result["unresolved_for_review"][0]["detail"]

    two_items = {"items": [_payload("6", correct=True)["items"][0],
                            _payload("26", correct=True)["items"][0]]}
    other = hrunner.StrategyHRunner(FakeExecutor({"6": two_items}), MODELS).run(
        _base_run(items), 2, hconfig.policy("h-low"))
    assert other["escalations"] == []
    assert "schema validation" in other["unresolved_for_review"][0]["detail"]


def test_provider_failure_stops_after_the_configured_budget():
    items = _perturb(_perturb(_perturb(_base_items(), "6", 1), "26", 3), "21", 1)
    executor = FakeExecutor(fail=True)
    result = hrunner.StrategyHRunner(executor, MODELS).run(
        _base_run(items), 1, hconfig.policy("h-medium"))

    assert result["request_count"] == 2
    assert len(executor.calls) == 2
    assert any(entry["status"] == "not_attempted"
               for entry in result["unresolved_for_review"])
    assert any("consecutive provider failures" in error for error in result["errors"])


def test_original_strategy_a_result_is_preserved():
    items = _perturb(_base_items(), "26", 3)
    original = copy.deepcopy(next(item for item in items if item["id"] == "26"))
    result = hrunner.StrategyHRunner(FakeExecutor({"26": _payload("26", correct=True)}),
                                     MODELS).run(
        _base_run(items), 1, hconfig.policy("h-medium"))

    kept = next(item for item in result["a_original"] if item["id"] == "26")
    final = next(item for item in result["items"] if item["id"] == "26")
    assert kept == original
    assert final["awarded"] == 2
    assert final["a_original"]["awarded"] == 3
    assert final["max_marks"] == original["max_marks"]
    assert result["escalation_changes"] == [
        {"item": "26", "before": 3, "after": 2, "reason": "S3_aggregation"}]


def test_low_confidence_alone_never_escalates_but_high_does():
    items = copy.deepcopy(_base_items())
    for item in items:
        if item["id"] == "5":
            item["confidence"] = 0.1

    low = hrunner.StrategyHRunner(FakeExecutor(), MODELS).run(
        _base_run(items), 1, hconfig.policy("h-low"))
    medium = hrunner.StrategyHRunner(FakeExecutor(), MODELS).run(
        _base_run(items), 2, hconfig.policy("h-medium"))
    responses = {item_id: _payload(item_id, correct=True) for item_id in loader.item_ids()}
    high = hrunner.StrategyHRunner(FakeExecutor(responses), MODELS).run(
        _base_run(items), 3, hconfig.policy("h-high"))

    assert low["signal_summary"]["candidates"] == 0
    assert medium["signal_summary"]["candidates"] == 0
    assert "5" in high["escalations"]


def test_signal_detector_reports_structure_and_contradictions():
    item = _a_item("6")
    item["criteria"] = item["criteria"][:2]
    codes = {signal.code for signal in signal_mod.detect(item)}
    assert "S1_structure" in codes

    item = _a_item("26")  # awarded 2/3, printed answer differs -> broad divergence
    codes = {signal.code for signal in signal_mod.detect(item)}
    assert "S8_broad_answer_divergence" in codes
    assert "S5a_under_award_contradiction" not in codes

    item = _a_item("23")
    item["awarded"] = 3
    item["criteria"][2]["awarded"] = False
    codes = {signal.code for signal in signal_mod.detect(item)}
    assert {"S3_aggregation", "S4b_full_marks_with_unawarded"} <= codes


def test_criterion_aggregation_matches_the_shared_evaluator():
    items = _perturb(_perturb(_base_items(), "6", 1), "26", 3)
    result = hrunner.StrategyHRunner(
        FakeExecutor({"6": _payload("6", correct=True),
                      "26": _payload("26", correct=True)}), MODELS).run(
        _base_run(items), 1, hconfig.policy("h-medium"))
    accuracy = evaluator.evaluate_run(result, ground_truth.load())

    assert accuracy["criterion_f1"] == 1.0
    assert accuracy["strict_correct"] is True
    assert accuracy["paper_score_awarded"] == 80
    assert accuracy["escalation_count"] == 2


def test_excluded_items_and_reference_exclusions_are_untouched():
    ids = loader.item_ids()
    assert "12" not in ids and "16d" not in ids
    assert len(ids) == 38
    reference = ground_truth.load()
    excluded = {item["id"]: item["status"] for item in reference["items"]
                if item["status"] != "scored"}
    assert excluded == {"12": "excluded_source_mismatch",
                        "16d": "excluded_not_printed"}
    result = hrunner.StrategyHRunner(FakeExecutor(), MODELS).run(
        _base_run(), 1, hconfig.policy("h-low"))
    assert "12" not in {item["id"] for item in result["items"]}
    assert ground_truth.validate(reference) == []


def test_cost_attribution_adds_only_escalation_cost():
    registry = {"6": {"cost_usd": 0.004}, "26": {"cost_usd": 0.0035}}
    cost = heval.cost_attribution(0.03, registry, ["6", "26"])
    assert cost["total_cost_usd"] == pytest.approx(0.0375)
    assert cost["escalation_cost_usd"] == pytest.approx(0.0075)

    unknown = heval.cost_attribution(0.03, registry, ["6", "99"])
    assert unknown["total_cost_usd"] is None
    assert unknown["criterion_costs_missing"] == 1

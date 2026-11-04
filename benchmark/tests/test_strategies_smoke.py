"""End-to-end smoke test of the three strategy runners with a fake executor.

No network, no key, no quota.  It proves the plumbing — batching, extraction,
escalation, parsing, evaluation — not the quality of any model.
"""

from __future__ import annotations

import json

from benchmark.code import ground_truth, loader, schema
from benchmark.code.execution import ModelSelection
from benchmark.code.provider import ProviderResult
from benchmark.code.strategies import StrategyRunner


class FakeExecutor:
    def __init__(self, reference):
        self.reference = reference
        self.items = {item["id"]: item for item in reference["items"] if item["status"] == "scored"}
        self.calls = []

    def call(self, *, strategy, run, batch, purpose, model, parts, system, schema,
             item_ids, escalated=False, max_attempts=3):
        self.calls.append({"strategy": strategy, "run": run, "batch": batch,
                           "purpose": purpose, "model": model, "ids": item_ids})
        if purpose == "extraction" and batch == "extract-scheme":
            payload = {"questions": [
                {"id": item_id, "question_text": item["prompt"], "max_marks": item["max_marks"],
                 "criteria": [{"code": c["code"], "text": c["text"]} for c in item["criteria"]],
                 "expected_answer": "expected"}
                for item_id, item in self.items.items()]}
            text = json.dumps(payload)
        elif purpose == "extraction" and batch.startswith("extract-page"):
            payload = {"questions": [
                {"id": item_id, "question_text": self.items[item_id]["prompt"],
                 "student_working": "working", "student_answer": "answer"}
                for item_id in item_ids]}
            text = json.dumps(payload)
        elif purpose == "extraction":  # C document understanding
            payload = {"questions": [
                {"id": item_id, "student_working": "working", "student_answer": "",
                 "confidence": 0.3 if item_id == "37b" else 0.99,
                 "ambiguous": item_id == "37b"}
                for item_id in item_ids]}
            text = json.dumps(payload)
        else:
            payload = {"items": [
                {"id": item_id, "awarded": self.items[item_id]["expected_mark"],
                 "max_marks": self.items[item_id]["max_marks"],
                 "student_answer": "a^3 b^2" if item_id == "37b" else "",
                 "criteria": [{"code": c["code"], "awarded": c["awarded"]}
                              for c in self.items[item_id]["criteria"]],
                 "confidence": 0.3 if item_id == "37b" else 0.99,
                 "flags": ["ambiguous"] if item_id == "37b" else []}
                for item_id in item_ids]}
            text = json.dumps(payload)
        return ProviderResult(status="ok", http_status=200, text=text, model=model,
                              usage={"input_tokens": 10, "output_tokens": 5, "reported": True}), []


def test_all_strategies_plumb_through_to_a_full_score():
    reference = ground_truth.load()
    models = ModelSelection(primary="fake-primary", lite="fake-lite", strong="fake-strong")
    executor = FakeExecutor(reference)
    runner = StrategyRunner(executor, models)

    for outcome in (runner.run_a(1), runner.run_b(1), runner.run_c(1)):
        assert len(outcome.final_items) == 38, outcome.errors
        assert outcome.invalid_responses == 0, outcome.errors
        assert sum(item["awarded"] for item in outcome.final_items.values()) == 80

    purposes = {call["purpose"] for call in executor.calls}
    assert {"marking", "extraction", "escalation"} <= purposes
    # Every escalation is a single-item request, never a whole-paper repeat.
    for call in executor.calls:
        if call["purpose"] == "escalation":
            assert len(call["ids"]) == 1


class PartialAExecutor(FakeExecutor):
    """Returns a partial whole-paper payload once, then completes split chunks."""

    def __init__(self, reference):
        super().__init__(reference)
        self.whole_paper_calls = 0

    def call(self, *, strategy, run, batch, purpose, model, parts, system, schema,
             item_ids, escalated=False, max_attempts=3):
        if batch == "whole-paper":
            self.whole_paper_calls += 1
            payload = {"items": [
                {"id": item_id, "awarded": self.items[item_id]["expected_mark"],
                 "max_marks": self.items[item_id]["max_marks"],
                 "student_answer": "",
                 "criteria": [{"code": c["code"], "awarded": c["awarded"]}
                              for c in self.items[item_id]["criteria"]],
                 "confidence": 0.99, "flags": []}
                for item_id in item_ids[:26]
            ]}
            return ProviderResult(status="ok", http_status=200, text=json.dumps(payload),
                                  model=model, finish_reason="MAX_TOKENS",
                                  usage={"input_tokens": 10, "output_tokens": 5,
                                         "reported": True}), []
        return super().call(strategy=strategy, run=run, batch=batch, purpose=purpose,
                            model=model, parts=parts, system=system, schema=schema,
                            item_ids=item_ids, escalated=escalated,
                            max_attempts=max_attempts)


class BRetryExecutor(FakeExecutor):
    """Leaves Q7/Q8 blank once, then succeeds on B's targeted page re-read."""

    def __init__(self, reference):
        super().__init__(reference)
        self.emptied_page_two = False

    def call(self, *, strategy, run, batch, purpose, model, parts, system, schema,
             item_ids, escalated=False, max_attempts=3):
        result, attempts = super().call(
            strategy=strategy, run=run, batch=batch, purpose=purpose, model=model,
            parts=parts, system=system, schema=schema, item_ids=item_ids,
            escalated=escalated, max_attempts=max_attempts,
        )
        if batch == "extract-page-1" and not self.emptied_page_two:
            payload = json.loads(result.text)
            for question in payload["questions"]:
                if question["id"] in {"7", "8"}:
                    question["student_working"] = ""
                    question["student_answer"] = ""
            result.text = json.dumps(payload)
            self.emptied_page_two = True
        return result, attempts


def test_b_retries_empty_page_transcription():
    reference = ground_truth.load()
    models = ModelSelection(primary="fake-primary", lite="fake-lite", strong="fake-strong")
    executor = BRetryExecutor(reference)
    outcome = StrategyRunner(executor, models).run_b(1)

    assert outcome.completion_status == "complete"
    assert outcome.extractions["retry_requests"] == 1
    assert {"7", "8"} <= set(outcome.extractions["retried_ids"])
    assert outcome.extractions["empty_after_retry"] == []
    assert outcome.final_items["7"]["awarded"] == 2
    assert outcome.final_items["8"]["awarded"] == 2


def test_a_uses_documented_split_after_partial_output():
    reference = ground_truth.load()
    models = ModelSelection(primary="fake-primary", lite="fake-lite", strong="fake-strong")
    executor = PartialAExecutor(reference)
    outcome = StrategyRunner(executor, models).run_a(1)

    assert executor.whole_paper_calls == 1
    assert outcome.request_count == 3
    assert len(outcome.splits) == 2
    assert outcome.completion_status == "complete_after_split"
    assert len(outcome.final_items) == 38
    assert sum(item["awarded"] for item in outcome.final_items.values()) == 80
    assert all(split["finish_reason"] == "" for split in outcome.splits)
    assert {call["batch"] for call in executor.calls} >= {"whole-paper-split-1",
                                                          "whole-paper-split-2"}


def test_c_escalation_reason_fires_on_sympy_disagreement():
    from benchmark.code.strategies import _escalation_reason

    reason = _escalation_reason(
        {"confidence": 0.99, "flags": []},
        {"status": "different", "detail": "difference 6"},
    )
    assert reason == "SymPy says transcribed answer differs from the scheme's expected answer"

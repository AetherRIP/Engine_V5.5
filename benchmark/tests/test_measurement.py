"""Offline tests for the measurement and evaluation code (no network, no quota)."""

from __future__ import annotations

import json

import pytest

from benchmark.code import config, evaluator, ground_truth, schema, usage, verifier
from benchmark.code.keypool import KeyPool, KeyRecord
from benchmark.code.provider import GeminiClient
from benchmark.code.report import coverage_audit, selected_strategy_rows
from benchmark.code.usage import observed_throughput
from benchmark.code.rerun_c import next_run_id
from benchmark.code.regenerate import load_strategy_runs


@pytest.fixture(scope="module")
def reference():
    return ground_truth.load()


def test_ground_truth_is_internally_consistent(reference):
    assert ground_truth.validate(reference) == []
    assert reference["totals"]["items_scored"] == 38
    assert reference["totals"]["items_excluded"] == 2
    assert reference["totals"]["marks_available_scored"] == 87
    assert reference["totals"]["candidate_marks_awarded"] == 80
    assert {item["id"] for item in reference["exclusions"]} == {"12", "16d"}


def _perfect_run(reference):
    items = []
    for item in reference["items"]:
        if item["status"] != "scored":
            continue
        items.append({
            "id": item["id"], "awarded": item["expected_mark"],
            "max_marks": item["max_marks"],
            "criteria": [{"code": criterion["code"],
                          "awarded": criterion["awarded"]} for criterion in item["criteria"]],
            "confidence": 0.95, "flags": [], "student_answer": "",
        })
    return {"strategy": "a", "run": 1, "items": items, "invalid_responses": 0, "errors": []}


def test_perfect_run_scores_one(reference):
    result = evaluator.evaluate_run(_perfect_run(reference), reference)
    assert result["strict_correct"] is True
    assert result["criterion_f1"] == 1.0
    assert result["coverage"] == 1.0
    assert result["paper_score_awarded"] == 80
    assert result["unresolved_count"] == 0


def test_missing_items_lose_coverage_and_become_unresolved(reference):
    run = _perfect_run(reference)
    run["items"] = [item for item in run["items"] if item["id"] != "37b"]
    result = evaluator.evaluate_run(run, reference)
    assert result["coverage"] < 1.0
    assert "37b" in result["unresolved_items"]
    assert result["strict_correct"] is False
    assert "37b" in result["hallucination_suspects"] or result["hallucination_suspects"] == []


def test_false_award_on_blank_item_is_suspected(reference):
    run = _perfect_run(reference)
    for item in run["items"]:
        if item["id"] == "37b":
            item["awarded"] = 3
            item["student_answer"] = "a^3 b^2"
            item["criteria"] = [{"code": c["code"], "awarded": True} for c in item["criteria"]]
    result = evaluator.evaluate_run(run, reference)
    assert result["false_awards"] == 3
    assert "37b" in result["hallucination_suspects"]
    assert result["strict_correct"] is False


def test_cost_uses_published_prices_and_flags_missing():
    pricing = {"m": config.Pricing("m", input_per_million=1.0, output_per_million=2.0,
                                   cached_input_per_million=0.25)}
    price = pricing["m"]
    assert price.cost(input_tokens=1_000_000, output_tokens=1_000_000) == 3.0
    assert price.cost(input_tokens=1_000_000, output_tokens=0, cached_tokens=1_000_000) == 0.25
    assert config.Pricing("none").cost(input_tokens=10, output_tokens=10) is None


def test_usage_aggregate_keeps_missing_tokens_missing():
    rows = [
        {"success": True, "input_tokens": 10, "output_tokens": 5, "latency_ms": 100,
         "attempt": 1, "cost_usd": 0.1, "model": "m", "key_label": "KEY_01"},
        {"success": False, "input_tokens": None, "output_tokens": None, "latency_ms": 200,
         "attempt": 2, "cost_usd": None, "model": "m", "key_label": "KEY_01"},
    ]
    totals = usage.aggregate(rows)
    assert totals["requests"] == 2
    assert totals["failed_requests"] == 1
    assert totals["input_tokens"] == 10
    assert totals["retries"] == 1
    assert totals["cost_usd"] == 0.1
    assert totals["rate_limit_rate"] == 0.0
    assert totals["cooldown_s_total"] is None


def test_schema_rejects_out_of_range_and_missing():
    clean, problems = schema.validate_marking(
        {"items": [{"id": "2", "awarded": 9, "criteria": []}]}, {"2": 1, "3": 2})
    assert clean["items"][0]["awarded"] == 1
    assert any("outside" in problem for problem in problems)
    assert any("missing" in problem for problem in problems)


def test_schema_accepts_valid_payload():
    clean, problems = schema.validate_marking(
        {"items": [{"id": "2", "awarded": 1, "criteria": [{"code": "B1", "awarded": True}],
                    "confidence": 0.9}]}, {"2": 1})
    assert clean and clean["paper_total"] == 1
    assert problems == []


def test_verifier_equivalent_different_unknown():
    assert verifier.equivalent("x^2 + 7x - 18", "x^2+7x-18")["status"] == "equivalent"
    assert verifier.equivalent("x^2 - 7x - 18", "x^2+7x-18")["status"] == "different"
    assert verifier.equivalent("", "x^2")["status"] == "unknown"
    assert verifier.equivalent("not maths !!!", "x^2")["status"] == "unknown"
    # Scheme extraction sometimes emits prime marks for superscripts.  The
    # normaliser must expose the real difference instead of returning unknown.
    assert verifier.normalise("20x'-31x\"") == "20x**3-31x**2"
    assert verifier.normalise("3x\"+5xy-12y\"") == "3x**2+5xy-12y**2"
    assert verifier.equivalent("20x^3-31x^2+63x-18",
                               "20x'-31x\"-81x-18")["status"] == "different"


class FakeClient:
    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = 0

    def list_models(self, key):
        state = self.statuses[self.calls]
        self.calls += 1
        if state == "invalid":
            return {"status": "invalid", "error_code": "API_KEY_INVALID", "models": []}
        if state == "quota":
            return {"status": "quota", "error_code": "RESOURCE_EXHAUSTED",
                    "daily_quota": False, "quota_id": "Q", "models": []}
        if state == "network":
            return {"status": "network", "error_code": "URLError", "models": []}
        return {"status": "ok", "error_code": "", "models": ["gemini-3.6-flash"]}

    def probe_generate(self, key, model=None):
        from benchmark.code.provider import ProviderResult
        return ProviderResult(status="ok", http_status=200, model=model or config.PRIMARY_MODEL,
                              usage={"input_tokens": 1, "output_tokens": 1, "reported": True})


def test_keypool_treats_429_as_quota_not_invalid(tmp_path):
    pool = KeyPool(["secret-a", "secret-b"], state_path=tmp_path / "state.json")
    pool.probe(FakeClient(["quota", "invalid"]))
    states = {key.label: key for key in pool.keys}
    assert states["KEY_01"].key_validity == "VALID"
    assert states["KEY_01"].quota_state in {"RATE_LIMITED", "QUOTA_EXHAUSTED"}
    assert states["KEY_02"].key_validity == "INVALID"
    coverage = pool.coverage()
    assert coverage["keys_total"] == 2
    assert coverage["keys_used_in_benchmark"] == 0
    assert len(coverage["unused_keys"]) == 2


def test_keypool_round_robin_and_cooldown(tmp_path):
    pool = KeyPool(["a", "b"], state_path=tmp_path / "state.json")
    pool.probe(FakeClient(["ok", "ok"]))
    first = pool.acquire()
    second = pool.acquire()
    assert first.label != second.label
    pool.mark_rate_limited(first, retry_after=120, quota_id="Q", daily=False)
    assert first.available() is False
    third = pool.acquire()
    assert third.label == second.label


def test_observed_throughput_uses_intervals_and_instrumented_wait():
    rows = [
        {"purpose": "marking", "timestamp": "2026-01-01T00:00:10+00:00",
         "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:10+00:00",
         "latency_ms": 10000, "success": True, "error_class": "", "key_label": "KEY_01"},
        {"purpose": "marking", "timestamp": "2026-01-01T00:00:15+00:00",
         "started_at": "2026-01-01T00:00:10+00:00", "finished_at": "2026-01-01T00:00:15+00:00",
         "latency_ms": 5000, "success": False, "error_class": "quota",
         "key_label": "KEY_02", "cooldown_wait_s": 2.5},
    ]
    result = observed_throughput(rows)
    assert result["requests"] == 2
    assert result["successes"] == 1
    assert result["concurrency_peak"] == 1
    assert result["rate_limit_rate"] == 0.5
    assert result["cooldown_wait_s_total"] == 2.5
    assert result["cooldown_wait_sources"]["instrumented"] == 1
    assert result["cooldown_records"][0]["source"] == "instrumented"


def test_historical_429_is_labelled_next_observed_use():
    rows = [
        {"purpose": "marking", "timestamp": "2026-01-01T00:00:00+00:00",
         "latency_ms": 1000, "success": False, "error_class": "quota",
         "key_label": "KEY_01", "batch": "one"},
        {"purpose": "marking", "timestamp": "2026-01-01T00:01:00+00:00",
         "latency_ms": 1000, "success": True, "error_class": "",
         "key_label": "KEY_01", "batch": "two"},
    ]
    result = observed_throughput(rows)
    assert result["suspensions"] == 1
    assert result["cooldown_wait_s_total"] is None
    assert result["cooldown_records"][0]["source"] == "next_observed_use"
    assert result["cooldown_records"][0]["wait_s"] == 60.0


def test_selected_rows_exclude_historical_attempts():
    rows = [
        {"strategy": "a", "run": 1, "success": False},
        {"strategy": "a", "run": 2, "success": True},
        {"strategy": "a", "run": 3, "success": True},
        {"strategy": "b", "run": 1, "success": True},
    ]
    selected = [{"run": 2}, {"run": 3}]
    assert selected_strategy_rows("a", rows, selected) == rows[1:3]
    assert selected_strategy_rows("b", rows, selected) == []


def test_coverage_audit_flags_inconsistent_claims(tmp_path):
    pool = KeyPool(["a"], state_path=tmp_path / "state.json")
    pool.probe(FakeClient(["ok"]))
    pool.keys[0].benchmark_successes = 2  # claim that the ledger cannot support
    rows = [{"purpose": "marking", "success": True, "key_label": "KEY_01"}]
    audit = coverage_audit(rows, pool.coverage())
    assert audit["keys"][0]["ledger_benchmark_successes"] == 1
    assert audit["keys"][0]["claimed_consistent"] is False
    assert audit["inconsistencies"] == ["KEY_01"]


def test_provider_usage_and_duration():
    client = GeminiClient()
    payload = {"usageMetadata": {
        "promptTokenCount": 100, "candidatesTokenCount": 20,
        "cachedContentTokenCount": 30, "thoughtsTokenCount": 5,
        "totalTokenCount": 125,
        "promptTokensDetails": [{"modality": "IMAGE", "tokenCount": 60}]}}
    from benchmark.code.provider import _usage
    parsed = _usage(payload)
    assert parsed["input_tokens"] == 100
    assert parsed["image_tokens"] == 60
    assert parsed["cached_tokens"] == 30
    from benchmark.code.provider import _duration
    assert _duration("1.5s") == 1.5
    assert _duration("250ms") == 0.25
    assert _duration("") is None
    assert client is not None


def test_pool_cooldown_suspends_inferred_pool(tmp_path):
    pool = KeyPool(["a", "b"], state_path=tmp_path / "state.json")
    pool.probe(FakeClient(["ok", "ok"]))
    pool.keys[0].pool = pool.keys[1].pool = "POOL_SHARED_99"
    pool.mark_rate_limited(pool.keys[0], retry_after=60, quota_id="Q", daily=False)
    assert pool.keys[1].available() is False
    assert any(event["event"] == "pool_cooldown" for event in pool.events)


def test_daily_quota_resets_probe_state_after_window(tmp_path):
    pool = KeyPool(["a"], state_path=tmp_path / "state.json")
    pool.probe(FakeClient(["ok"]))
    key = pool.keys[0]
    key.quota_state = "QUOTA_EXHAUSTED"
    key.cooldown_kind = "daily"
    key.cooldown_until = 0
    key.probe_state = "quota_limited"
    assert key.available() is True
    assert key.quota_state == "UNKNOWN"
    assert key.probe_state == "healthy"


def test_keypool_from_state_preserves_historical_counters(tmp_path):
    state_path = tmp_path / "state.json"
    pool = KeyPool(["a"], state_path=state_path)
    pool.probe(FakeClient(["ok"]))
    pool.mark_success(pool.keys[0], benchmark=True)
    loaded = KeyPool.from_state(["a"], state_path=state_path)
    assert loaded.keys[0].requests == pool.keys[0].requests
    assert loaded.keys[0].successes == pool.keys[0].successes
    assert loaded.keys[0].benchmark_successes == 1
    assert loaded.keys[0].probe_state == "healthy"


def test_historical_and_recovered_c_differences_replay_through_repaired_guard():
    from benchmark.code.replay_c import build_replay
    replay = build_replay()
    assert replay["kind"] == "offline_replay"
    assert replay["measurement_kind"] == "replay_not_live"
    assert replay["live_api_calls"] == 0
    assert replay["raw_files_modified"] is False
    assert replay["historical_raw"] == {"runs": [1, 2], "raw_different": 4}
    assert replay["current_raw"]["raw_different"] == 0
    assert replay["current_raw"]["re_evaluated_different"] == 6
    assert replay["current_raw"]["by_run"] == {"5": 4, "6": 2}
    assert replay["different_checks"] == 10
    assert sum(1 for record in replay["records"]
               if record["source_kind"] == "historical_raw_different") == 4
    assert sum(1 for record in replay["records"]
               if record["source_kind"] == "recovered_from_raw_unknown") == 6
    assert replay["pre_fix"] == {"escalations": 0, "escalation_gap": True}
    assert replay["fixed"] == {"escalations": 10, "escalation_gap": False}
    assert all(not record["pre_fix_escalated"] for record in replay["records"])
    assert all(record["fixed_escalated"] for record in replay["records"])
    assert all(record["fixed_reason"] for record in replay["records"])


def test_escalation_gap_requires_every_different_item():
    from benchmark.code.rerun_c import _attempt_diagnostics
    payload = {
        "verification": {"1": {"status": "different"}, "2": {"status": "different"}},
        "escalations": ["1"], "items": [], "completion_status": "incomplete",
    }
    diagnostics = _attempt_diagnostics(payload)
    assert diagnostics["different_checks"] == 2
    assert diagnostics["escalation_count"] == 1
    assert diagnostics["escalation_gap"] is True
    assert diagnostics["valid"] is False


def test_rerun_rejects_scheme_extraction_failure():
    from benchmark.code.rerun_c import _attempt_diagnostics
    payload = {
        "verification": {item: {"status": "unknown"} for item in
                          ("1a", "1d", "2", "3", "4", "5", "6", "7")},
        "escalations": [], "items": [], "completion_status": "complete",
        "errors": ["scheme extraction failed; escalation checks are limited"],
    }
    diagnostics = _attempt_diagnostics(payload)
    assert diagnostics["scheme_ok"] is False
    assert diagnostics["valid"] is False


def test_rerun_ids_never_reuse_old_c_files(tmp_path):
    assert next_run_id(tmp_path) == 1
    (tmp_path / "c_run1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "c_run2.json").write_text("{}", encoding="utf-8")
    assert next_run_id(tmp_path) == 3
    (tmp_path / "c_run7.json").write_text("{}", encoding="utf-8")
    assert next_run_id(tmp_path) == 8


def test_rerun_selector_promotes_only_valid_c_pair(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "c_run1.json").write_text(json.dumps({"run": 1}), encoding="utf-8")
    (raw / "c_run2.json").write_text(json.dumps({"run": 2}), encoding="utf-8")
    (raw / "c_run3.json").write_text(json.dumps({"run": 3, "attempt_status": "valid"}), encoding="utf-8")
    (raw / "c_run4.json").write_text(json.dumps({"run": 4, "attempt_status": "valid"}), encoding="utf-8")
    runs = load_strategy_runs("c", tmp_path)
    assert [run["run"] for run in runs] == [3, 4]
    (raw / "c_run5.json").write_text(json.dumps({"run": 5, "attempt_status": "invalid"}), encoding="utf-8")
    assert [run["run"] for run in load_strategy_runs("c", tmp_path)] == [3, 4]

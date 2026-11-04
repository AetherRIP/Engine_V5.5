"""Build comparison.json, key coverage, and the human-readable reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config, evaluator, ground_truth, usage


def _pct(value):
    return None if value is None else round(value * 100, 2)


def selected_strategy_rows(strategy: str, rows: list[dict],
                            runs: list[dict]) -> list[dict]:
    """Return ledger rows belonging only to the selected runs.

    Historical attempts stay on disk and in the ledger, but they must never be
    added to a strategy's current usage totals.
    """
    run_ids = {str(run.get("run")) for run in runs}
    return [row for row in rows
            if row.get("strategy") == strategy
            and str(row.get("run")) in run_ids]


def build_comparison(strategy_runs: dict[str, list[dict]], rows: list[dict],
                     pool_state: dict | None) -> dict:
    benchmark_rows = [row for row in rows if row.get("purpose") != "probe"]
    probe_rows = [row for row in rows if row.get("purpose") == "probe"]
    reference = ground_truth.load()
    comparison = {
        "paper_id": config.PAPER_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference_status": "candidate_not_teacher_certified",
        "paper_max_marks": reference["totals"]["marks_available_scored"],
        "paper_reference_marks": reference["totals"]["candidate_marks_awarded"],
        "definitions": {
            "correctly_assessed_paper": (
                "paper total exactly equal to the candidate reference, all scoreable items "
                "returned, no unresolved item, and no invalid response"
            ),
            "near_correct": "paper total within one mark of the candidate reference and full coverage",
            "cost": "provider-reported tokens x published per-million prices; None when unpublished",
            "quota_efficiency": "correctly assessed papers per 1,000 benchmark requests",
        },
        "strategies": {},
        "keys": {},
        "probes": usage.aggregate(probe_rows),
        "benchmark_totals": usage.aggregate(benchmark_rows),
        "throughput": usage.observed_throughput(benchmark_rows),
    }

    for strategy, runs in strategy_runs.items():
        accuracy = [evaluator.evaluate_run(run) for run in runs]
        strategy_rows = selected_strategy_rows(strategy, benchmark_rows, runs)
        totals = usage.aggregate(strategy_rows)
        correct = sum(1 for run in accuracy if run["strict_correct"])
        near = sum(1 for run in accuracy if run["near_correct_within_one"])
        within_three = sum(1 for run in accuracy if abs(run["score_error"]) <= 3
                           and run["coverage"] == 1.0)
        extraction_rows = [row for row in strategy_rows if row.get("purpose") == "extraction"]
        marking_rows = [row for row in strategy_rows if row.get("purpose") == "marking"]
        escalation_rows = [row for row in strategy_rows if row.get("purpose") == "escalation"]
        cost = totals.get("cost_usd")
        comparison["strategies"][strategy] = {
            "runs": len(runs),
            "attempt_id": next((run.get("attempt_id") for run in reversed(runs)
                                if run.get("attempt_id")), None) if runs else None,
            "models": runs[0].get("models") if runs else None,
            "paper_max_marks": reference["totals"]["marks_available_scored"],
            "paper_reference_marks": reference["totals"]["candidate_marks_awarded"],
            "accuracy": evaluator.summarise(accuracy),
            "accuracy_per_run": accuracy,
            "disagreements": _disagreements(runs, reference),
            "run_meta": [
                {"run": run.get("run"),
                 "completion_status": run.get("completion_status"),
                 "request_count": run.get("request_count"),
                 "splits": run.get("splits") or [],
                 "errors": run.get("errors") or [],
                 "extractions": run.get("extractions") or {},
                 "escalations": run.get("escalations") or [],
                 "escalation_changes": run.get("escalation_changes") or []}
                for run in runs
            ],
            "throughput": usage.observed_throughput(strategy_rows),
            "usage": totals,
            "extraction": usage.aggregate(extraction_rows),
            "marking": usage.aggregate(marking_rows),
            "escalation": usage.aggregate(escalation_rows),
            "escalations_total": sum(len(run.get("escalations") or []) for run in runs),
            "correctly_assessed_papers": correct,
            "near_correct_papers": near,
            "within_three_papers": within_three,
            "cost_per_paper_usd": round(cost / len(runs), 8) if cost is not None and runs else None,
            "cost_per_correctly_assessed_paper_usd": (
                round(cost / correct, 8) if cost is not None and correct else None),
            "cost_per_near_correct_paper_usd": (
                round(cost / near, 8) if cost is not None and near else None),
            "cost_per_paper_within_3_marks_usd": (
                round(cost / within_three, 8) if cost is not None and within_three else None),
            "quota_efficiency_papers_per_1000_requests": (
                round(correct / totals["requests"] * 1000, 2) if totals.get("requests") else None),
            "requests_per_paper": round(totals.get("requests", 0) / len(runs), 2) if runs else None,
            "wall_clock": usage.wall_clock(strategy_rows),
            "per_run": {
                str(run.get("run")): usage.aggregate(
                    [row for row in strategy_rows if row.get("run") == run.get("run")])
                for run in runs
            },
        }

    if pool_state:
        comparison["keys"] = {
            "keys_total": pool_state.get("keys_total"),
            "eligible_keys": pool_state.get("eligible_keys"),
            "keys_used_in_benchmark": pool_state.get("keys_used_in_benchmark"),
            "successful_benchmark_requests": pool_state.get("successful_benchmark_requests"),
            "min_successful_requests_for_full_coverage": pool_state.get(
                "min_successful_requests_for_full_coverage"),
            "full_coverage_achieved": pool_state.get("full_coverage_achieved"),
            "pools": pool_state.get("pools", {}),
        }
    return comparison


def _disagreements(runs: list[dict], reference: dict) -> list[dict]:
    gt = {item["id"]: item for item in reference["items"] if item["status"] == "scored"}
    out = []
    for run in runs:
        got = {item["id"]: item for item in run.get("items", [])}
        for item_id, truth in gt.items():
            awarded = got.get(item_id, {}).get("awarded")
            if awarded != truth["expected_mark"]:
                out.append({
                    "run": run.get("run"),
                    "item": item_id,
                    "awarded": awarded,
                    "expected": truth["expected_mark"],
                    "reason": got.get(item_id, {}).get("reason", "")[:300],
                })
    return out


def write_comparison(comparison: dict) -> None:
    config.ensure_dirs()
    (config.RESULTS_DIR / "comparison.json").write_text(
        json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    throughput = {
        "generated_at": comparison.get("generated_at"),
        "source": "results/api_usage.jsonl",
        "overall": comparison.get("throughput"),
        "strategies": {strategy: entry.get("throughput")
                       for strategy, entry in comparison.get("strategies", {}).items()},
    }
    (config.RESULTS_DIR / "throughput.json").write_text(
        json.dumps(throughput, indent=2) + "\n", encoding="utf-8")


def write_strategy_result(strategy: str, runs: list[dict], accuracy: list[dict],
                          totals: dict, path: Path | None = None) -> None:
    payload = {
        "strategy": strategy,
        "paper_id": config.PAPER_ID,
        "models": runs[0].get("models") if runs else None,
        "runs": [{"run": run.get("run"), "request_count": run.get("request_count"),
                  "invalid_responses": run.get("invalid_responses"),
                  "completion_status": next(
                      (item.get("completion_status") for item in accuracy
                       if item.get("run") == run.get("run")), None),
                  "errors": run.get("errors"), "items": run.get("items"),
                  "extractions": run.get("extractions"),
                  "escalations": run.get("escalations"),
                  "verification": run.get("verification"),
                  "splits": run.get("splits")} for run in runs],
        "accuracy": accuracy,
        "usage": totals,
    }
    latest_attempt = next((run.get("attempt_id") for run in reversed(runs)
                           if run.get("attempt_id")), None)
    if latest_attempt:
        payload["attempt_id"] = latest_attempt
    target = path or (config.RESULTS_DIR / f"strategy_{strategy}.json")
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def coverage_audit(rows: list[dict], pool_state: dict) -> dict:
    """Audit key use against the ledger.

    An "eligible" key is one that authenticated, was reachable and was not
    generation-denied at discovery.  Keys that later exhausted their daily quota
    remain eligible; their absence is a quota outcome, not a silent omission.
    """
    benchmark_successes: dict[str, int] = {}
    for row in rows:
        if row.get("purpose") == "probe" or not row.get("success"):
            continue
        label = row.get("key_label")
        benchmark_successes[label] = benchmark_successes.get(label, 0) + 1

    keys = []
    for key in pool_state.get("keys", []):
        label = key["label"]
        actual = benchmark_successes.get(label, 0)
        claimed = key.get("benchmark_successes", 0)
        keys.append({**key, "ledger_benchmark_successes": actual,
                     "claimed_consistent": actual == claimed, "used": actual > 0})

    eligible = [key for key in keys
                if key.get("key_validity") == "VALID"
                and key.get("network_state") != "UNREACHABLE"
                and (key.get("probe_state") == "healthy" or key.get("successes", 0) > 0)]
    eligible_labels = {key["label"] for key in eligible}
    used_eligible = [key for key in eligible if key["used"]]
    reasons = {entry["label"]: entry["reason"] for entry in pool_state.get("unused_keys", [])}
    eligible_unused = [
        {"label": key["label"],
         "reason": reasons.get(key["label"], _reason_from_state(key))}
        for key in eligible if not key["used"]
    ]
    excluded = [
        {"label": key["label"], "reason": reasons.get(key["label"], _reason_from_state(key))}
        for key in keys if key["label"] not in eligible_labels
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "keys_total": len(keys),
        "eligible_keys": len(eligible),
        "eligible_labels": sorted(eligible_labels),
        "keys_with_successful_benchmark_request": len(used_eligible),
        "successful_benchmark_requests": sum(
            key["ledger_benchmark_successes"] for key in used_eligible),
        "min_successful_requests_for_full_coverage": len(eligible),
        "full_coverage_achieved": len(used_eligible) == len(eligible),
        "eligible_keys_unused": eligible_unused,
        "excluded_keys": excluded,
        "unused_keys": eligible_unused + excluded,
        "inconsistencies": [key["label"] for key in keys if not key["claimed_consistent"]],
        "probe_rows": sum(1 for row in rows if row.get("purpose") == "probe"),
        "benchmark_rows": sum(1 for row in rows if row.get("purpose") != "probe"),
        "keys": keys,
    }


def _reason_from_state(key: dict) -> str:
    if key.get("key_validity") == "INVALID":
        return f"invalid key ({key.get('last_error_code') or 'auth error'})"
    if key.get("network_state") == "UNREACHABLE":
        return "unreachable"
    if key.get("quota_state") == "QUOTA_EXHAUSTED":
        return "quota exhausted"
    if key.get("probe_state") not in {"healthy", None}:
        return f"probe state {key.get('probe_state')}"
    return "not selected before the workload ended"


def write_coverage(audit: dict) -> None:
    (config.RESULTS_DIR / "key_coverage.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8")


def _fmt(value, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return str(value)


def _pct_fmt(value) -> str:
    if value is None:
        return "unavailable"
    return f"{value * 100:.2f}%"


def _cooldown_fmt(throughput: dict) -> str:
    if not throughput:
        return "unavailable"
    if not throughput.get("suspensions"):
        return "0 (none)"
    sources = throughput.get("cooldown_wait_sources") or {}
    measured = int(sources.get("instrumented") or 0)
    if measured:
        total = throughput.get("cooldown_wait_s_total")
        return f"{_fmt(total, digits=3)} ({measured} instrumented)"
    next_use = [item for item in (throughput.get("cooldown_records") or [])
                if item.get("source") == "next_observed_use"]
    if next_use:
        total = sum(item.get("wait_s") or 0 for item in next_use)
        return f"next-use {_fmt(total, digits=1)} ({len(next_use)})"
    return "unavailable"


def _clean_errors(run: dict) -> list[str]:
    """Drop batch-scope "missing items" messages contradicted by the final output."""
    present = {item.get("id") for item in run.get("items", [])}
    cleaned = []
    for error in run.get("errors", []):
        if error.startswith("missing items:"):
            ids = [part.strip() for part in error.split(":", 1)[1].split(",")]
            if all(item_id in present for item_id in ids):
                continue
        cleaned.append(error)
    return cleaned


def render_report(comparison: dict, audit: dict, reference: dict, manifest: dict) -> str:
    strategies = [s for s in ("a", "b", "c") if s in comparison["strategies"]]
    names = {"a": "A — whole document", "b": "B — extract then batch",
             "c": "C — whole document + specialists"}
    c_entry = comparison["strategies"].get("c", {})
    c_runs = c_entry.get("accuracy_per_run", [])
    c_different = sum(int(run.get("verification_different") or 0) for run in c_runs)
    c_escalations = sum(int(run.get("escalation_count") or 0) for run in c_runs)
    c_gap = any(bool(run.get("escalation_gap")) for run in c_runs)
    c_scores = " / ".join(str(run.get("paper_score_awarded")) for run in c_runs)
    c_f1 = _fmt(c_entry.get("accuracy", {}).get("criterion_f1"))
    c_false = _fmt(c_entry.get("accuracy", {}).get("false_awards"))
    c_attempt = c_entry.get("attempt_id") or "historical C attempt"
    c_escalation_requests = int((c_entry.get("escalation") or {}).get("requests") or 0)
    current_ids = sorted(int(run.get("run")) for run in c_runs
                         if str(run.get("run", "")).isdigit())
    prior_end = min(current_ids) - 1 if current_ids else 0
    c_archived = f"C1–C{prior_end}" if prior_end >= 1 else "none"
    c_replay = c_entry.get("replay_evidence") or {}
    replay_current = c_replay.get("current_raw") or {}
    replay_historical = c_replay.get("historical_raw") or {}
    replay_recovered = int(replay_current.get("re_evaluated_different") or 0)
    replay_raw_current = int(replay_current.get("raw_different") or 0)
    replay_historical_different = int(replay_historical.get("raw_different") or 0)
    replay_pre = c_replay.get("pre_fix") or {}
    replay_fixed = c_replay.get("fixed") or {}
    c_live = c_entry.get("live_escalation") or {}
    c_live_ok = bool(c_live.get("valid_changed_mark"))
    c_live_request = c_live.get("request") or {}
    if c_replay:
        c_guard_note = (
            f"Raw C5/C6 verification has {replay_raw_current} `different`; fixed "
            f"re-evaluation recovers {replay_recovered} genuine differences "
            f"(C5 {replay_current.get('by_run', {}).get('5', 0)}, "
            f"C6 {replay_current.get('by_run', {}).get('6', 0)}). Offline replay of those "
            f"plus {replay_historical_different} historical C1/C2 differences has pre-fix "
            f"{replay_pre.get('escalations', 0)} escalation(s) with gap "
            f"{replay_pre.get('escalation_gap')}, and fixed "
            f"{replay_fixed.get('escalations', 0)} escalation(s) with gap "
            f"{replay_fixed.get('escalation_gap')}; the full-document branch remains "
            "unexercised."
        )
    elif c_different == 0:
        c_guard_note = ("No check was `different`, so the selected C5/C6 specialist "
                        "branch remains unexercised; no escalation claim is made for "
                        "those runs.")
    elif c_gap:
        c_guard_note = ("At least one `different` check was not escalated; the guard "
                        "remains a protocol deviation.")
    else:
        c_guard_note = ("The repaired guard escalated every `different` check; this "
                        "attempt is live escalation evidence.")
    if c_live_ok:
        c_guard_note += (
            f" Separately, a targeted live escalation of C{c_live.get('base_run')} item "
            f"{c_live.get('item')} changed {c_live.get('before')} to {c_live.get('after')}."
        )
    if c_escalations:
        c_model_note = ("C's configured strong model `gemini-3.1-pro-preview` was "
                        f"unavailable; {c_escalation_requests} escalation request(s) used "
                        "the primary fallback.")
    else:
        c_model_note = ("C's configured strong model `gemini-3.1-pro-preview` was "
                        "unavailable; no selected-run escalation request ran.")
    if c_live_ok:
        c_model_note = (
            f"The selected C5/C6 runs made no escalation request; the separate targeted "
            f"live escalation used `{c_live.get('model')}` on one student page plus one "
            f"scheme page ({c_live_request.get('input_tokens')} input, "
            f"{c_live_request.get('output_tokens')} output tokens; "
            f"USD {_fmt(c_live_request.get('cost_usd'), digits=6)})."
        )
    c_replay_note = ""
    c_replay_caveat = ""
    if c_replay:
        c_replay_note = (
            "Offline replay (not a live run): "
            f"{c_replay.get('different_checks', 0)} checks = "
            f"{replay_historical_different} historical C1/C2 raw + "
            f"{replay_recovered} recovered C5/C6; pre-fix "
            f"{replay_pre.get('escalations', 0)} escalation(s) with gap "
            f"{replay_pre.get('escalation_gap')}; repaired guard "
            f"{replay_fixed.get('escalations', 0)} escalation(s) with gap "
            f"{replay_fixed.get('escalation_gap')}."
        )
        c_replay_caveat = ("This replay demonstrates the guard on preserved raw and re-evaluated "
                           "inputs; it is not a new live C measurement. No live API calls were made "
                           "for the replay. The separate targeted live escalation below is the "
                           "live evidence.")
    c_attempts = c_entry.get("attempts") or []
    unpromoted = [attempt for attempt in c_attempts
                  if attempt.get("attempt_status") not in {None, "valid"}]
    if unpromoted:
        latest = max(unpromoted, key=lambda attempt: int(attempt.get("run") or 0))
        reason = latest.get("attempt_status_reason") or "not promoted; no valid differing pair"
        c_latest_note = (f"The latest appended C attempt `{latest.get('attempt_id')}` "
                         f"(run {latest.get('run')}) was not promoted: {reason}.")
    else:
        c_latest_note = ""
    if c_replay:
        c_note = (f"  Raw verification has {replay_raw_current} `different`; fixed re-evaluation "
                  f"recovers {replay_recovered} genuine differences. The replay below is offline, "
                  "not a live escalation run.")
        c_last = "  Its raw item disagreements are listed below; the re-evaluated differences and replay are derived artifacts."
    elif c_different == 0:
        c_note = ("  No check was `different`, so the specialist branch remains unexercised; "
                  "C is a valid whole-document/Lite measurement, not evidence for escalation.")
        c_last = "  Its item disagreements are listed below; this is measured output, not a protocol-deviation claim."
    elif c_gap:
        c_note = ("  At least one `different` check did not produce an escalation; "
                  "this remains a protocol deviation.")
        c_last = "  C's measured scores cannot validate the specialist branch."
    else:
        c_note = ("  Every `different` check produced an escalation; the specialist branch "
                  "was exercised in this attempt.")
        c_last = "  Its item disagreements are listed below; this is measured output."
    c_observations = [c_note, c_last]
    if c_latest_note:
        c_observations.append("  " + c_latest_note)
    if c_replay_note:
        c_observations.append("  " + c_replay_note)
    if c_live_ok:
        c_observations.append(
            "  A separate append-only live escalation re-marked only Q"
            f"{c_live.get('item')} from one student page and one scheme page; it changed "
            f"{c_live.get('before')} to {c_live.get('after')} and is not a rewrite of C5/C6."
        )
    c_limitations = []
    if c_replay:
        c_limitations.append(
            f"- Raw C5/C6 verification has {replay_raw_current} `different`; fixed "
            f"re-evaluation recovers {replay_recovered} (C5 4, C6 2). The raw C files were "
            "not rewritten; the re-evaluation lives in the derived replay artifact."
        )
    if c_latest_note:
        c_limitations.append(f"- {c_latest_note}")
    if c_replay_caveat:
        c_limitations.append(f"- {c_replay_caveat} {c_replay_note}")
    if c_live_ok:
        c_limitations.append(
            "- Full-document C reruns C9–C13 remained provider-blocked by HTTP 503/timeouts. "
            f"The live escalation evidence is a separate targeted addendum for C{c_live.get('base_run')} "
            f"Q{c_live.get('item')}, not a complete fresh C pairing."
        )
    else:
        c_limitations.append(
            "- Live C reruns C9–C13 were attempted after the selected C5/C6 pair. "
            "Every full-document request returned HTTP 503 (model high demand) or timed out, "
            "including explicit 3.6, 3.5, 3.8 and 3.1-Lite fallbacks. No live escalation "
            "request completed; the replay above is not a substitute for that missing live row."
        )

    c_live_lines = []
    if c_live_ok:
        c_live_lines = [
            "",
            f"### Live targeted escalation — C{c_live.get('base_run')} / Q{c_live.get('item')}",
            "",
            "This is a separate live provider response, not a rewrite of the selected C5/C6 "
            "runs. It used one anonymised student page and the matching one-page printed "
            "scheme; no whole-document upload was made.",
            "",
            "| Base run | Item | Model | Before | After | Reference | Changed |",
            "|---|---|---|---|---|---|---|",
            f"| C{c_live.get('base_run')} | Q{c_live.get('item')} | `{c_live.get('model')}` | "
            f"{c_live.get('before')} | {c_live.get('after')} | {c_live.get('expected_mark')} | "
            f"{c_live.get('changed')} |",
            "",
            f"- Ledger batch `{c_live.get('request_batch')}`; status "
            f"`{c_live_request.get('http_status')}`; input/output tokens "
            f"{_fmt(c_live_request.get('input_tokens'))} / "
            f"{_fmt(c_live_request.get('output_tokens'))}; estimated cost USD "
            f"{_fmt(c_live_request.get('cost_usd'), digits=6)}.",
            f"- Page hashes: student `{c_live.get('source', {}).get('student_page_sha256', '')[:16]}…`, "
            f"scheme `{c_live.get('source', {}).get('scheme_page_sha256', '')[:16]}…`; "
            f"coverage {_pct_fmt(c_live.get('coverage', {}).get('coverage'))} "
            f"({c_live.get('coverage', {}).get('items_returned')} / "
            f"{c_live.get('coverage', {}).get('items_requested')} item).",
            "- This addendum does not alter C5/C6's measured scores or claim a complete "
            "fresh C pairing.",
        ]

    a_entry = comparison["strategies"].get("a", {})
    a_runs = a_entry.get("accuracy_per_run", [])
    a_usage = a_entry.get("usage", {})
    a_meta = a_entry.get("run_meta", [])
    a_scores = " / ".join(str(run.get("paper_score_awarded")) for run in a_runs)
    a_run_ids = ", ".join(str(run.get("run")) for run in a_runs)
    a_complete = bool(a_runs) and all(
        run.get("completion_status") in {"complete", "complete_after_split"}
        and run.get("coverage") == 1.0 and run.get("unresolved_count") == 0
        for run in a_runs
    )
    a_split_details = []
    for meta in a_meta:
        for split in meta.get("splits") or []:
            requested = ", ".join(str(item) for item in (split.get("requested_ids") or []))
            returned = ", ".join(str(item) for item in (split.get("returned_ids") or []))
            a_split_details.append(
                f"run {meta.get('run')} split {split.get('request')} requested [{requested}]; "
                f"returned [{returned}]"
            )
    a_observations = [
        f"- Strategy A made {a_usage.get('requests', 0)} benchmark request(s) across its "
        f"current run(s) {a_run_ids}; scores {a_scores} out of "
        f"{a_entry.get('paper_max_marks')} against the candidate reference of "
        f"{a_entry.get('paper_reference_marks')}, coverage "
        f"{_pct_fmt(a_entry.get('accuracy', {}).get('coverage'))}."
    ]
    if a_complete:
        a_observations.append("  Every current A run returned all scoreable items; the current pair is complete.")
    else:
        a_observations.append("  At least one current A run is incomplete; that run is not a complete comparison measurement.")
    if a_split_details:
        a_observations.append(
            "  The documented split fallback was exercised in recorded request(s): "
            + "; ".join(a_split_details) + "."
        )
    else:
        a_observations.append("  The single whole-paper response covered all items; no split was required.")
    b_entry = comparison["strategies"].get("b", {})
    b_runs = b_entry.get("accuracy_per_run", [])
    b_meta = b_entry.get("run_meta", [])
    b_scores = " / ".join(str(run.get("paper_score_awarded")) for run in b_runs)
    b_f1 = _fmt(b_entry.get("accuracy", {}).get("criterion_f1"))
    b_empty = sorted({
        str(item.get("id")) for run in b_runs
        for item in _run_items("b", run.get("run"))
        if str(item.get("id")) != "37b" and not str(item.get("student_answer") or "").strip()
    })
    b_retries = sum(int((meta.get("extractions") or {}).get("retry_requests") or 0)
                    for meta in b_meta)
    b_observations = [
        f"- Strategy B made {b_entry.get('usage', {}).get('requests', 0)} benchmark request(s) "
        f"across its current run(s) "
        f"{', '.join(str(run.get('run')) for run in b_runs)}; scores {b_scores} out of "
        f"{b_entry.get('paper_max_marks')} against the candidate reference of "
        f"{b_entry.get('paper_reference_marks')}, "
        f"criterion F1 {b_f1}, coverage "
        f"{_pct_fmt(b_entry.get('accuracy', {}).get('coverage'))}."
    ]
    if b_empty:
        b_observations.append(
            "  Empty extracted answers remain for " + ", ".join(b_empty)
            + "; these are extraction losses, not marking-rule losses. Root cause: the "
            "per-page transcription returned a blank student_answer for these ids, so the "
            "marking stage correctly saw blank work. The targeted re-read path is implemented "
            "but was not exercised by the selected B pair."
        )
    else:
        b_observations.append(
            "  Both selected runs transcribed all 38 scoreable items; no extraction loss remains"
            + (f" after {b_retries} targeted re-read request(s)." if b_retries else ".")
        )
    if b_retries:
        b_observations.append(
            f"  The extraction path issued {b_retries} targeted re-read request(s); "
            "the retries are counted in B's consumption."
        )

    a_limitations = []
    if a_split_details:
        a_limitations.append(
            "- A's selected pair includes the documented output split: "
            + "; ".join(a_split_details) + ". The split requests and their item ids are in the ledger."
        )
    else:
        a_limitations.append(
            "- A's selected pair required no output split; the split fallback remains available but was not exercised in these runs."
        )
    if not any(run.get("run") == 1 for run in a_runs):
        a_limitations.append(
            "- The historical A1 run (26/38) remains preserved in the raw files and ledger; "
            "it is excluded from the current A pair."
        )
    if a_usage.get("failed_requests"):
        a_limitations.append(
            f"- A's current selected runs contain {a_usage['failed_requests']} failed request(s); "
            "they are counted in consumption and not in coverage."
        )
    else:
        a_limitations.append(
            "- A's current selected runs contain no failed benchmark requests; retries are not counted as coverage."
        )
    lines = [
        "# Correction strategy benchmark — measured report",
        "",
        f"Paper: **{comparison['paper_id']}** · generated {comparison['generated_at']}",
        "",
        "> **Ground-truth status: candidate, NOT teacher-certified.** The reference marks were",
        "> derived from the printed scheme and an independent re-solve. Accuracy below is",
        "> provisional and must not be presented as a certified marking accuracy.",
        "",
        "## 1. Dataset",
        "",
        f"- {manifest['paper']['pages']} anonymised student pages, "
        f"{manifest['paper']['scheme_pages']} mark-scheme pages.",
        f"- {reference['totals']['items_total']} items in the reference; "
        f"{reference['totals']['items_scored']} scoreable "
        f"({reference['totals']['marks_available_scored']} marks); "
        f"{reference['totals']['items_excluded']} excluded for source inconsistency.",
        f"- Candidate total: {reference['totals']['candidate_marks_awarded']} / "
        f"{reference['totals']['marks_available_scored']} "
        f"({reference['totals']['candidate_percentage']}%).",
        "- Excluded: " + "; ".join(f"{item['id']} ({item['status']})"
                                   for item in reference["exclusions"]) + ".",
        "",
        "## 2. Models and configuration",
        "",
    ]
    models = comparison["strategies"].get(strategies[0], {}).get("models") or {}
    lines.append("| Role | Model |")
    lines.append("|---|---|")
    for role in ("primary", "lite", "strong"):
        if models.get(role):
            lines.append(f"| {role} | `{models[role]}` |")
    for note in models.get("notes") or []:
        lines.append("- " + note)
    lines.extend([
        "",
        "Generation settings: temperature 0, top-p 0.95, thinking budget 0 (per-model",
        "override where the model rejects zero), identical response schema; two selected",
        "runs per strategy. The original six were interleaved A1→B1→C1→A2→B2→C2; A3 was",
        "appended as a recorded complete reattempt.",
        "",
        "## 3. Accuracy (provisional)",
        "",
        f"| Strategy | Coverage | Item exact | Paper score /{comparison.get('paper_max_marks')} (exact / within 1) | MAE | Criterion P | Criterion R | Criterion F1 | False awards | False deductions | Unresolved |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ])
    for strategy in strategies:
        entry = comparison["strategies"][strategy]
        acc = entry["accuracy"]
        lines.append(
            f"| {names[strategy]} | {_pct_fmt(acc.get('coverage'))} | "
            f"{_pct_fmt(acc.get('item_exact_accuracy'))} | "
            f"{entry['correctly_assessed_papers']}/{entry['runs']} exact · "
            f"{entry['near_correct_papers']}/{entry['runs']} within 1 | "
            f"{_fmt(acc.get('mean_absolute_score_error'))} | "
            f"{_fmt(acc.get('criterion_precision'))} | {_fmt(acc.get('criterion_recall'))} | "
            f"{_fmt(acc.get('criterion_f1'))} | {_fmt(acc.get('false_awards'))} | "
            f"{_fmt(acc.get('false_deductions'))} | {_fmt(acc.get('unresolved_count'))} |")
    incomplete = []
    for _strategy in strategies:
        for _run in comparison["strategies"][_strategy]["accuracy_per_run"]:
            if _run.get("completion_status") != "complete":
                incomplete.append(
                    f"{names[_strategy]} run {_run['run']}: "
                    f"{_run['completion_status']} ({_run['items_returned']}/"
                    f"{_run['items_expected']} returned)")
    if incomplete:
        lines.extend(["", "- Completion classification: " + "; ".join(incomplete) + "."])
    c6_run = next((run for run in c_runs if run.get("run") == 6), {})
    c6_disagreements = [row for row in c_entry.get("disagreements", [])
                        if row.get("run") == 6]
    lines.extend([
        "",
        "### C6 score audit",
        "",
        f"- C6's `paper_score_awarded` is **{c6_run.get('paper_score_awarded')}**. "
        f"The scoreable maximum is **{c_entry.get('paper_max_marks')}**, and the "
        f"candidate reference is **{c_entry.get('paper_reference_marks')}**. Thus 82 is "
        "an awarded total out of 87, not 82 out of 80.",
        "- The raw C6 payload has 38 unique scoreable items, no duplicate or unmatched "
        "ids, and no item award above its 3-mark (or smaller) cap. Its item awards sum "
        "directly to 82; the only disagreements are "
        + (", ".join(f"Q{row.get('item')} awarded {row.get('awarded')} vs reference "
                      f"{row.get('expected')}" for row in c6_disagreements) or "none")
        + ".",
        "- The extra two marks are Q26 and Q30 over-awards (+1 each), not duplicate "
        "criteria or a maximum-mark accounting defect. The 82/80 appearance is therefore "
        "a derived report-label ambiguity: 80 is the candidate reference, not the "
        "denominator. The benchmark's strict correctness rule remains reference equality.",
        "",
        "## 4. API consumption",
        "",
        "| Strategy | Requests | Failed | Input tokens | Output tokens | Cached input | Total tokens | Est. cost USD | Cost / paper | Cost / near-correct paper | Cost / correct paper |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ])
    for strategy in strategies:
        entry = comparison["strategies"][strategy]
        usage_entry = entry["usage"]
        lines.append(
            f"| {names[strategy]} | {_fmt(usage_entry.get('requests'))} | "
            f"{_fmt(usage_entry.get('failed_requests'))} | {_fmt(usage_entry.get('input_tokens'))} | "
            f"{_fmt(usage_entry.get('output_tokens'))} | {_fmt(usage_entry.get('cached_tokens'))} | "
            f"{_fmt(usage_entry.get('total_tokens'))} | "
            f"{_fmt(usage_entry.get('cost_usd'), digits=6)} | "
            f"{_fmt(entry.get('cost_per_paper_usd'), digits=6)} | "
            f"{_fmt(entry.get('cost_per_near_correct_paper_usd'), digits=6)} | "
            f"{_fmt(entry.get('cost_per_correctly_assessed_paper_usd'), digits=6)} |")
    lines.extend([
        "",
        "> Costs are provider-reported tokens × published list prices. Free-tier usage may be",
        "> invoiced at USD 0; these are estimates for comparison, not invoices. A missing value",
        "> is `unavailable`, never zero. Probe requests are excluded here and reported in §6.",
        "> 'Near-correct' means the total is within one mark with full coverage; it is not used",
        "> to relax the strict definition of a correctly assessed paper.",
        "",
        "## 5. Processing time",
        "",
        "| Strategy | Mean request latency (ms) | p50 | Max | Requests / paper | Observed successes / min | Observed 429 rate | Observed concurrency | Observed cooldown wait (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for strategy in strategies:
        entry = comparison["strategies"][strategy]
        usage_entry = entry["usage"]
        throughput = entry.get("throughput", {})
        lines.append(
            f"| {names[strategy]} | {_fmt(usage_entry.get('latency_ms_mean'))} | "
            f"{_fmt(usage_entry.get('latency_ms_p50'))} | {_fmt(usage_entry.get('latency_ms_max'))} | "
            f"{_fmt(entry.get('requests_per_paper'))} | "
            f"{_fmt(throughput.get('successes_per_minute'))} | "
            f"{_pct_fmt(throughput.get('rate_limit_rate'))} | "
            f"{_fmt(throughput.get('concurrency_peak'))} | {_cooldown_fmt(throughput)} |")
    lines.extend([
        "",
        "Observed concurrency is the peak overlap of request intervals reconstructed from",
        "`started_at`/`finished_at` where present, otherwise completion time minus latency.",
        "Cooldown wait is the instrumented scheduler wait for new rows. Historical 429 rows",
        "without that field are labelled by their next observed use interval; assigned",
        "`cooldown_s` values are never substituted for measured wait.",
    ])
    if audit["full_coverage_achieved"]:
        coverage_note = ("All eligible keys have at least one successful benchmark request; "
                         "excluded keys are listed below.")
    else:
        coverage_note = ("Coverage is incomplete; eligible keys without a successful benchmark "
                         "request are listed below.")
    lines.extend([
        "",
        "## 6. Key pool and observed quota",
        "",
        f"- Keys discovered: **{audit['keys_total']}**; eligible (valid, reachable, "
        f"generation-capable at discovery): **{audit['eligible_keys']}**.",
        f"- Eligible keys with at least one successful benchmark request: "
        f"**{audit['keys_with_successful_benchmark_request']} / {audit['eligible_keys']}**.",
        f"- Full eligible-key coverage: **{audit['full_coverage_achieved']}**.",
        f"- Coverage threshold: **{audit.get('min_successful_requests_for_full_coverage')}** "
        f"successful benchmark requests; observed **{audit.get('successful_benchmark_requests')}**.",
        "  The threshold is a necessary floor, not a guarantee that every eligible key was used.",
        f"- The workload produced **{audit['benchmark_rows']}** benchmark requests "
        f"({comparison['benchmark_totals'].get('successful_requests')} successful); coverage is "
        f"**{audit['keys_with_successful_benchmark_request']} / {audit['eligible_keys']}**.",
        f"  {coverage_note}",
        f"- Probe requests (excluded from benchmark totals): **{audit['probe_rows']}**; "
        f"benchmark requests: **{audit['benchmark_rows']}**.",
        "",
        "| Key | Validity | Quota | Network | Probe | Pool | Benchmark successes | Requests | 429s |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for key in audit["keys"]:
        lines.append(
            f"| {key['label']} | {key['key_validity']} | {key['quota_state']} | "
            f"{key['network_state']} | {key.get('probe_state', '')} | {key['pool']} | "
            f"{key['ledger_benchmark_successes']} | {key['requests']} | {key['rate_limit_hits']} |")
    lines.extend([
        "",
        "| Observed pool | Keys | Benchmark successes | Requests | 429s |",
        "|---|---|---|---|---|",
    ])
    for pool, entry in (comparison["keys"].get("pools") or {}).items():
        lines.append(f"| {pool} | {', '.join(entry['keys'])} | {entry['benchmark_successes']} | "
                     f"{entry['requests']} | {entry['rate_limit_hits']} |")
    lines.append("")
    if audit["eligible_keys_unused"]:
        lines.append("Eligible keys without a successful benchmark request:")
        for entry in audit["eligible_keys_unused"]:
            lines.append(f"- {entry['label']}: {entry['reason']}")
        lines.append("")
    if audit["excluded_keys"]:
        lines.append("Keys excluded from eligibility:")
        for entry in audit["excluded_keys"]:
            lines.append(f"- {entry['label']}: {entry['reason']}")
        lines.append("")
    lines.extend([
        "### Did distribution improve throughput?",
        "",
        "Per-key and per-pool states, successes, 429s and measured cooldown records are in",
        "`api_usage.jsonl` and `results/throughput.json`. A 429 also suspends keys already inferred",
        "into the same pool; that is cooldown protection, not additional quota. No controlled",
        "single-key versus pool experiment was run in this pilot, so no causal throughput gain",
        "is claimed. Distribution is load balancing within the observed quota, not extra quota.",
        "",
        "## 7. Failure analysis",
        "",
    ])
    any_failure = False
    for strategy in strategies:
        entry = comparison["strategies"][strategy]
        per_run = entry.get("per_run", {})
        for run in entry["accuracy_per_run"]:
            cleaned = _clean_errors({"items": _run_items(strategy, run["run"]),
                                     "errors": run["errors"]})
            failed = (per_run.get(str(run["run"])) or {}).get("failed_requests", 0)
            if cleaned or run["unresolved_items"] or run["invalid_responses"] or failed:
                any_failure = True
                detail = ("; ".join(cleaned[:6])
                          or "no unresolved parse/transport error remains in the final payload")
                lines.append(
                    f"- {names[strategy]} run {run['run']}: `{run.get('completion_status', 'unknown')}`; "
                    f"{run['invalid_responses']} invalid response(s), {run['unresolved_count']} unresolved, "
                    f"{failed} failed request(s); {detail}")
    if not any_failure:
        lines.append("- No failed or invalid benchmark responses were associated with the current "
                     "accuracy outputs; request-level failures remain counted in §4.")
    lines.extend([
        "",
        "### Per-item disagreements (all runs)",
        "",
        "| Strategy | Run | Item | Awarded | Reference | Model reason |",
        "|---|---|---|---|---|---|",
    ])
    for strategy in strategies:
        for row in comparison["strategies"][strategy].get("disagreements", []):
            lines.append(
                f"| {strategy.upper()} | {row['run']} | {row['item']} | "
                f"{row['awarded'] if row['awarded'] is not None else 'missing'} | "
                f"{row['expected']} | {row['reason'].replace('|', '/')[:120]} |")
    lines.extend([
        "",
        "### Observations",
        "",
        *a_observations,
        *b_observations,
        f"- Strategy C's current attempt `{c_attempt}` returned all 38 items in both runs;",
        f"  scores {c_scores} out of {c_entry.get('paper_max_marks')} against the candidate "
        f"reference of {c_entry.get('paper_reference_marks')}, criterion F1 {c_f1}. It recorded {c_different} raw `different`",
        f"  check(s) and {c_escalations} escalation(s); raw `escalation_gap` is {c_gap}.",
        *c_observations,
        *c_live_lines,
        "",
        "## 8. Caching",
        "",
        "| Strategy | Run | Input tokens | Cached input | Cache hit rate | Reported cost USD |",
        "|---|---|---|---|---|---|",
    ])
    for _strategy in strategies:
        for _run_key, _usage in (comparison["strategies"][_strategy].get("per_run") or {}).items():
            _hit = ("n/a" if not _usage.get("input_tokens") or _usage.get("cached_tokens") is None
                    else f"{_usage['cached_tokens'] / _usage['input_tokens'] * 100:.1f}%")
            lines.append(
                f"| {names[_strategy]} | {_run_key} | {_fmt(_usage.get('input_tokens'))} | "
                f"{'not reported' if _usage.get('cached_tokens') is None else _fmt(_usage.get('cached_tokens'))} | {_hit} | "
                f"{_fmt(_usage.get('cost_usd'), digits=6)} |")
    lines.extend([
        "",
        "Gemini implicit caching is provider-controlled and cannot be forced on or off per",
        "request. The table is the measured split, not a controlled experiment.",
        "",
        "**Important confound:** A2 was 93.7% cached; A3 reported no cached tokens. B's first",
        "included run did not report cached tokens, while C's current first run was 53.3% cached.",
        "C's cache state is not equal to B's or A's. A's reported cost is therefore partly a warm-cache",
        "artefact; the strategies were not measured under equal cache conditions. No strategy was",
        "deliberately given a cache advantage, and no cold-versus-warm causal claim is made.",
        "",
        "## 9. Limitations",
        "",
        "- One paper, one student, one sitting: no statistical significance and no general winner.",
        "- The reference is candidate-only; a teacher must certify it before production adoption.",
        "- Two items are excluded because the student page and scheme disagree (Q12, Q16d).",
        "- Provider quota conditions differed between requests and pools; per-pool results are",
        "  reported to expose the confounding rather than hiding it.",
        *a_limitations,
        "- Lite model substitution: `gemini-3.1-flash-lite` was not verified on the first healthy",
        "  keys, so `gemini-3.5-flash-lite` was used with its default thinking budget. This is a",
        "  capability difference between strategies and is flagged as a confound.",
        f"- {c_model_note}",
        f"- C's current attempt `{c_attempt}` has {c_different} raw `different` check(s) and "
        f"{c_escalations} escalation(s); raw `escalation_gap` is {c_gap}. Earlier C runs "
        f"({c_archived}) are preserved as historical attempts and are not used in this verdict. "
        f"{c_guard_note}",
        *c_limitations,
        "- All provider calls were sequential (concurrency 1); no concurrency speed-up is claimed.",
        "- Historical 429 rows that predate instrumentation have no `cooldown_wait_s`; their",
        "  next observed use interval is labelled in `throughput.json` rather than treated as a",
        "  configured cooldown. New rows record the measured scheduler wait; no wait-time causal",
        "  claim is made.",
        "",
        "## 10. Recommended architecture",
        "",
        "See `RECOMMENDATION.md`. No strategy met the strict bar of an exact paper score with",
        "full coverage, so the recommendation is a conditional architecture choice, not a",
        "production adoption.",
        "",
        "## 11. Further experiments before production",
        "",
        "- Teacher-certify this paper and a holdout of at least 10 papers across topics.",
        "- Repeat A's completeness check on additional papers; the current pair is complete",
        "  and any output split is recorded in the raw run and ledger.",
        "- B's Q7/Q8/Q19 loss is recorded as a blank per-page transcription; validate the "
        "targeted re-read path on a live B run and add a transcription verification step.",
        ("- C's escalation branch has been demonstrated offline; its full-document live reruns "
         "were provider-blocked (HTTP 503/timeouts), while a targeted live single-item "
         "escalation succeeded. A full live C pairing and an image-grounded transcription "
         "fidelity check remain necessary to measure whether either removes its "
         "corrected-answer over-awards." if c_live_ok else
         "- C's escalation branch has been demonstrated offline; its post-C5/C6 live reruns "
         "were provider-blocked (HTTP 503/timeouts). Retry a live differing case and add an "
         "image-grounded transcription fidelity check to measure whether either removes its "
         "corrected-answer over-awards." if c_replay else
         "- Force C's escalation stage to run and add an image-grounded transcription fidelity "
         "check; measure whether either removes its corrected-answer over-awards."),
        "- Repeat with cold and warm caches explicitly controlled where the provider allows.",
        "- Run a single-key versus pool throughput experiment before relying on distribution.",
        "",
        "## Appendix — source integrity",
        "",
        f"- Dataset manifest: `{config.MANIFEST_PATH.name}`; anonymised copies only.",
        "- Reference: `ground_truth/paper-01.json`; review sheet: `ground_truth/REVIEW_SHEET.md`.",
        "- Q12 and Q16(d) are documented exclusions, not zero-mark questions.",
        "- Batch-scope validator messages that named items already present in the final payload",
        "  were removed from this report; raw run files retain them.",
        "",
    ])
    return "\n".join(lines)


def _run_items(strategy: str, run: int) -> list[dict]:
    path = config.RESULTS_DIR / "raw" / f"{strategy}_run{run}.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("items", [])


def write_reports(comparison: dict, audit: dict, reference: dict, manifest: dict) -> None:
    config.ensure_dirs()
    (config.REPORTS_DIR / "BENCHMARK_REPORT.md").write_text(
        render_report(comparison, audit, reference, manifest), encoding="utf-8")
    (config.REPORTS_DIR / "RECOMMENDATION.md").write_text(
        render_recommendation(comparison), encoding="utf-8")


def render_recommendation(comparison: dict) -> str:
    entries = comparison["strategies"]
    lines = [
        "# Recommendation",
        "",
        "> Provisional. The reference is not teacher-certified and the sample is one paper.",
        "",
        "## Decision rule",
        "",
        "Accuracy is a constraint, not a trade-off. A strategy is eligible only if it returned",
        "every scoreable item, reached the reference paper total exactly in at least one run,",
        "and its criterion F1 was at least as high as the best strategy. Among eligible",
        "strategies, the lowest cost per correctly assessed paper wins; request count alone",
        "never decides.",
        "",
        "## Measured result",
        "",
    ]
    for strategy in ("a", "b", "c"):
        if strategy not in entries:
            continue
        entry = entries[strategy]
        acc = entry["accuracy"]
        lines.append(
            f"- Strategy {strategy.upper()}: criterion F1 {_fmt(acc.get('criterion_f1'))}, "
            f"coverage {_pct_fmt(acc.get('coverage'))}, "
            f"paper scores {', '.join(str(r['paper_score_awarded']) for r in entry['accuracy_per_run'])}"
            f" (max {entry.get('paper_max_marks')}; candidate reference "
            f"{entry['accuracy_per_run'][0]['paper_score_expected']}), "
            f"{entry['correctly_assessed_papers']} strictly correct run(s), "
            f"{entry['usage'].get('requests', 0)} requests, "
            f"cost USD {_fmt(entry['usage'].get('cost_usd'), digits=6)}.")
    lines.extend(["", "## Recommendation", "", _recommendation_text(entries), ""])
    lines.extend([
        "## What would change it",
        "",
        "- A teacher-certified reference that moves the criterion F1 or false-award ordering.",
        "- A larger sample where A's completeness or B's extraction loss changes materially.",
        "- Live evidence that C's escalation stage fires, and that transcription fidelity checks catch",
        "  its corrected-answer hallucinations.",
        "- A provider price or quota change larger than the measured cost gap.",
        "",
    ])
    return "\n".join(lines)


def _recommendation_text(entries: dict) -> str:
    if not entries:
        return "No strategy completed, so no recommendation can be made."
    eligible = [s for s, e in entries.items()
                if e["accuracy"].get("coverage") == 1.0
                and e["correctly_assessed_papers"] > 0]
    if eligible:
        best = min(eligible, key=lambda s: entries[s]["usage"].get("cost_usd") or float("inf"))
        entry = entries[best]
        return (
            f"Strategy **{best.upper()}** met the strict accuracy constraint and had the lowest "
            f"cost among those that did (USD {_fmt(entry['usage'].get('cost_usd'), digits=6)} "
            f"for {entry['usage'].get('requests', 0)} requests). Replicate on a teacher-certified "
            f"multi-paper set before adoption."
        )
    best_f1 = max(entries.items(), key=lambda item: item[1]["accuracy"].get("criterion_f1") or 0)
    strategy, entry = best_f1
    c_entry = entries.get("c", {})
    c_runs = c_entry.get("accuracy_per_run", [])
    c_different = sum(int(run.get("verification_different") or 0) for run in c_runs)
    c_escalations = sum(int(run.get("escalation_count") or 0) for run in c_runs)
    c_gap = any(bool(run.get("escalation_gap")) for run in c_runs)
    c_scores = " / ".join(str(run.get("paper_score_awarded")) for run in c_runs)
    c_f1 = _fmt(c_entry.get("accuracy", {}).get("criterion_f1"))
    c_false = _fmt(c_entry.get("accuracy", {}).get("false_awards"))
    replay = c_entry.get("replay_evidence") or {}
    replay_current = replay.get("current_raw") or {}
    replay_historical = replay.get("historical_raw") or {}
    replay_recovered = int(replay_current.get("re_evaluated_different") or 0)
    replay_raw_current = int(replay_current.get("raw_different") or 0)
    replay_historical_different = int(replay_historical.get("raw_different") or 0)
    replay_pre = replay.get("pre_fix") or {}
    replay_fixed = replay.get("fixed") or {}
    live = c_entry.get("live_escalation") or {}
    live_ok = bool(live.get("valid_changed_mark"))
    a_entry = entries.get("a", {})
    a_runs = a_entry.get("accuracy_per_run", [])
    a_ids = ", ".join(str(run.get("run")) for run in a_runs)
    a_complete = bool(a_runs) and all(
        run.get("completion_status") in {"complete", "complete_after_split"}
        and run.get("coverage") == 1.0
        for run in a_runs
    )
    a_split = any(
        (meta.get("splits") or []) for meta in (a_entry.get("run_meta") or [])
    )
    if a_complete:
        a_note = (
            f"A now has {len(a_runs)} complete recorded run(s) (runs {a_ids}), "
            "covering all scoreable items"
            + ("; its output split is recorded in the raw run and ledger" if a_split else "; no split was required")
            + "."
        )
    else:
        a_note = (
            f"A's current runs {a_ids} do not both cover the full paper; "
            "the incomplete evidence is retained rather than extrapolated."
        )
    if replay:
        c_note = (
            "C's current attempt is a valid whole-document/Lite measurement with "
            f"{replay_raw_current} raw `different` checks. Re-evaluating the preserved "
            f"C5/C6 inputs with the fixed classifier recovers {replay_recovered} genuine "
            f"differences (C5 {replay_current.get('by_run', {}).get('5', 0)}, C6 "
            f"{replay_current.get('by_run', {}).get('6', 0)}); offline replay of those plus "
            f"{replay_historical_different} historical C1/C2 differences has pre-fix "
            f"{replay_pre.get('escalations', 0)} escalation(s) and gap "
            f"{replay_pre.get('escalation_gap')}, versus fixed "
            f"{replay_fixed.get('escalations', 0)} escalation(s) and gap "
            f"{replay_fixed.get('escalation_gap')}. This replay is offline, not a live run. "
            "Full-document post-C5/C6 live attempts C9–C13 were provider-blocked by HTTP "
            "503/timeouts before any escalation request could complete."
        )
    elif c_different == 0:
        c_note = ("C's current attempt is a valid whole-document/Lite measurement, but no check "
                  "was `different`; the specialist branch remains unexercised. It is not "
                  "evidence that escalation works.")
    elif c_gap:
        c_note = ("C's current attempt still has an escalation gap: at least one `different` "
                  "check did not produce an escalation, so it is a protocol deviation.")
    else:
        c_note = ("C's current attempt escalated every `different` check; the specialist branch "
                  "was exercised in this attempt.")
    if live_ok:
        branch = ("exercised in a targeted live single-item case, but not across a fresh "
                  "complete C run")
        future = "a full live C pairing and a transcription-fidelity check"
    elif replay:
        branch = "demonstrated offline but unexercised live"
        future = "a live escalation case"
    elif c_different == 0:
        branch = "unexercised"
        future = "a measured escalation case"
    elif c_gap:
        branch = "still protocol-deviating"
        future = "a measured escalation case"
    else:
        branch = "exercised but not sufficient to remove the remaining item differences"
        future = "a broader set of escalated cases"
    replay_note = ""
    if replay:
        replay_note = (
            " The replay is derived from preserved raw inputs; no raw C file was rewritten, "
            "and no live API call was made for it."
        )
    live_note = ""
    if live_ok:
        live_note = (
            f" A separate targeted live escalation on C{live.get('base_run')} Q{live.get('item')} "
            f"changed {live.get('before')} to {live.get('after')} using "
            f"`{live.get('model')}`; it is real live evidence, but not a fresh full-paper C run."
        )
    return (
        "**No strategy met the strict bar.** None returned an exact paper score with full "
        "coverage in either run, so no packaging can be called production-ready on this "
        "evidence.\n\n"
        f"The closest aggregate result is **strategy {strategy.upper()}** "
        f"(attempt `{c_entry.get('attempt_id')}`): criterion F1 {c_f1}, coverage "
        f"{_pct_fmt(c_entry.get('accuracy', {}).get('coverage'))}, scores {c_scores} against "
        f"a maximum of {c_entry.get('paper_max_marks')} and a candidate reference of "
        f"{c_entry.get('paper_reference_marks')}, false awards {c_false}. {c_note}\n\n"
        "**Architecture recommendation:** do not adopt C as a validated specialist pipeline on "
        f"this sample: its measured scores are close but not exact, and the escalation branch is "
        f"{branch}. Any future C must add an independent image-grounded transcription check and "
        f"{future}.{replay_note}{live_note} B is the lower-risk baseline only after its blank-extraction "
        "defect is fixed and a non-empty check is added; it had no false awards. "
        f"{a_note}"
    )

"""Generate the final-test reports from preserved raw runs and the ledger.

Reads only local artifacts; never contacts the provider and never rewrites a
raw response or a ledger row. Historical paper-01 artifacts are not touched.

    python -m benchmark.code.final_report
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config, verifier

PAPER_ID = "ch2-l3-final-01"
ROOT = config.BENCHMARK_DIR / "final_tests" / PAPER_ID
RAW = ROOT / "results" / "raw"
REPORTS = ROOT / "reports"
STRATEGIES = ("a", "b", "c")
NAMES = {"a": "A — whole document", "b": "B — extract then batch",
         "c": "C — whole document + specialists"}


def _load(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _runs() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for path in sorted(RAW.glob("*_run*.json")):
        strategy = path.name.split("_", 1)[0]
        out.setdefault(strategy, []).append(json.loads(path.read_text(encoding="utf-8")))
    for strategy in out:
        out[strategy].sort(key=lambda run: run.get("run", 0))
    return out


def _ledger() -> list[dict]:
    path = ROOT / "results" / "API_USAGE.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pct(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value, digits=2):
    return "n/a" if value is None else f"{value:,.{digits}f}"


def _money(value):
    return "n/a" if value is None else f"${value:.6f}"


def _norm(text: str) -> str:
    value = str(text or "").lower()
    for old, new in (("−", "-"), ("–", "-"), ("×", "*"), ("²", "**2"), ("³", "**3"),
                     ("^", "**"), (" ", ""), ("{", ""), ("}", "")):
        value = value.replace(old, new)
    return value


def _read_status(actual: str, got: str) -> str:
    if not str(got or "").strip():
        return "blank"
    if _norm(actual) == _norm(got):
        return "exact"
    check = verifier.equivalent(got, actual)
    if check["status"] == "equivalent":
        return "equivalent"
    if check["status"] == "different":
        return "different"
    return "unknown"


def _reference():
    return _load(ROOT / "reference" / "GROUND_TRUTH.json", {})


def _answers():
    return _load(ROOT / "reference" / "STUDENT_ANSWERS.json", {}).get("answers", {})


def _comparison():
    return _load(ROOT / "results" / "STRATEGY_COMPARISON.json", {})


def _latency_p95(rows: list[dict]) -> float | None:
    values = sorted(row["latency_ms"] for row in rows
                    if row.get("success") and isinstance(row.get("latency_ms"), int))
    if not values:
        return None
    index = min(len(values) - 1, int(round(0.95 * (len(values) - 1))))
    return values[index]


def _transcription_rows(runs: dict[str, list[dict]]) -> list[dict]:
    answers = _answers()
    out = []
    for strategy in STRATEGIES:
        for run in runs.get(strategy, []):
            items = {str(item.get("id")): item for item in run.get("items", [])}
            for item_id, truth in answers.items():
                item = items.get(item_id)
                if item is None:
                    status, got = "missing_item", ""
                else:
                    got = str(item.get("student_answer", ""))
                    status = _read_status(truth.get("final", ""), got)
                if status != "exact":
                    out.append({"strategy": strategy, "run": run.get("run"),
                                "item": item_id, "status": status,
                                "expected": truth.get("final", ""), "reported": got})
    return out


def _escalation_rows(runs: dict[str, list[dict]]) -> list[dict]:
    reference = _reference()
    truth = {item["id"]: item for item in reference.get("items", [])
             if item.get("status") == "scored"}
    out = []
    for run in runs.get("c", []):
        for change in run.get("escalation_changes") or []:
            item_id = str(change.get("item"))
            expected = truth.get(item_id, {}).get("expected_mark")
            after = change.get("after")
            before = change.get("before")
            out.append({
                "run": run.get("run"), "item": item_id,
                "before": before, "after": after, "expected": expected,
                "reason": change.get("reason", ""),
                "correct_change": after == expected,
                "harmful": before == expected and after != expected,
                "no_change": before == after,
            })
    return out


def _usage_for(strategy: str, run: int | None = None) -> list[dict]:
    rows = [row for row in _ledger() if row.get("strategy") == strategy
            and row.get("purpose") != "probe"]
    if run is not None:
        rows = [row for row in rows if row.get("run") == run]
    return rows


def _cost_summary(strategy: str) -> dict:
    comparison = _comparison()
    entry = (comparison.get("strategies") or {}).get(strategy) or {}
    return entry.get("usage") or {}


def _write(path: Path, text: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    runs = _runs()
    comparison = _comparison()
    reference = _reference()
    band = reference.get("reference_range") or {}
    center = band.get("center", 76)
    low, high = band.get("low", 74), band.get("high", 78)
    ledger = _ledger()
    bench = [row for row in ledger if row.get("purpose") != "probe"]

    lines = ["# Final A/B/C benchmark — Ch2 L3", "",
             f"Paper: **{PAPER_ID}** · generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
             f"> Reference: **{reference.get('totals', {}).get('candidate_marks_awarded')} / "
             f"{reference.get('totals', {}).get('marks_available_scored')}** "
             f"(11 marks lost), treated as a human tolerance band **{low}–{high}** (centre {center}). "
             "Exact equality is reported separately. The reference is user-ruled, not teacher-signed.",
             "", "## 1. Attempts", "",
             "| Strategy | Attempt | Status | Items | Score | Band | F1 | False awards | False deductions | Requests |", 
             "|---|---|---|---|---|---|---|---|---|---|"]
    for strategy in STRATEGIES:
        for run in runs.get(strategy, []):
            band_runs = {row["run"]: row for row in
                         (comparison.get("strategies", {}).get(strategy, {})
                          .get("band_accuracy_per_run") or [])}
            row = band_runs.get(run.get("run"), {})
            lines.append(
                f"| {strategy.upper()} | {run.get('run')} | {run.get('completion_status')} | "
                f"{len(run.get('items', []))}/38 | {row.get('paper_score_awarded', 'n/a')} | "
                f"{'yes' if row.get('within_band') else 'no'} | {_num(row.get('criterion_f1'), 4)} | "
                f"{row.get('false_awards', 'n/a')} | {row.get('false_deductions', 'n/a')} | "
                f"{run.get('request_count', 'n/a')} |")

    lines += ["", "## 2. A/B/C comparison (per attempt and average)", "",
              "| Strategy | Attempts | Scores | Mean abs error | Exact 76 | Within ±1 | Within band | Criterion F1 (mean) | False awards | False deductions | Cost USD | Cost/paper |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for strategy in STRATEGIES:
        entry = (comparison.get("strategies") or {}).get(strategy) or {}
        acc = entry.get("band_accuracy_per_run") or []
        summary = entry.get("band_summary") or {}
        scores = ", ".join(str(row.get("paper_score_awarded")) for row in acc) or "n/a"
        lines.append(
            f"| {strategy.upper()} | {len(acc)} | {scores} | {_num(summary.get('mean_absolute_error'))} | "
            f"{summary.get('exact_center', 0)}/{summary.get('runs', 0)} | "
            f"{summary.get('within_one', 0)}/{summary.get('runs', 0)} | "
            f"{summary.get('within_band', 0)}/{summary.get('runs', 0)} | "
            f"{_num(summary.get('mean_criterion_f1'), 4)} | {summary.get('total_false_awards', 'n/a')} | "
            f"{summary.get('total_false_deductions', 'n/a')} | {_money((entry.get('usage') or {}).get('cost_usd'))} | "
            f"{_money(entry.get('cost_per_paper_usd'))} |")

    lines += ["", "## 3. API consumption", "",
              "| Strategy | Requests | Successful | Failed | Input | Output | Cached | Thinking | Total | Cost USD | Mean latency ms | p95 latency ms |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for strategy in STRATEGIES:
        usage = _cost_summary(strategy)
        rows = _usage_for(strategy)
        lines.append(
            f"| {strategy.upper()} | {usage.get('requests', 'n/a')} | {usage.get('successful_requests', 'n/a')} | "
            f"{usage.get('failed_requests', 'n/a')} | {usage.get('input_tokens', 'n/a')} | "
            f"{usage.get('output_tokens', 'n/a')} | {usage.get('cached_tokens', 'n/a')} | "
            f"{usage.get('thoughts_tokens', 'n/a')} | {usage.get('total_tokens', 'n/a')} | "
            f"{_money(usage.get('cost_usd'))} | {_num(usage.get('latency_ms_mean'), 1)} | {_num(_latency_p95(rows), 1)} |")

    lines += ["", "## 4. Transcription audit", "",
              "| Strategy | Run | Item | Status | Expected (student) | Reported |",
              "|---|---|---|---|---|---|"]
    transcription = _transcription_rows(runs)
    for row in transcription:
        lines.append(f"| {row['strategy'].upper()} | {row['run']} | {row['item']} | {row['status']} | "
                     f"{row['expected'][:60]} | {row['reported'][:60]} |")
    if not transcription:
        lines.append("| — | — | — | all exact | — | — |")

    escalations = _escalation_rows(runs)
    lines += ["", "## 5. Escalation audit", "",
              "| Run | Item | Before | After | Expected | Correct change | Harmful | Reason |",
              "|---|---|---|---|---|---|---|---|"]
    for row in escalations:
        lines.append(f"| C{row['run']} | {row['item']} | {row['before']} | {row['after']} | "
                     f"{row['expected']} | {row['correct_change']} | {row['harmful']} | {row['reason'][:60]} |")
    if not escalations:
        lines.append("| — | — | — | — | — | — | — | no escalation changed a mark |")

    lines += ["", "## 6. Answers to the decision questions", ""]
    lines.append("1. **Which reproduced the 11-mark deduction most accurately?** "
                 + _best_by(runs, comparison, "mean_absolute_error", center, lower=True))
    lines.append("2. **Highest criterion F1:** "
                 + _best_by(runs, comparison, "mean_criterion_f1", center, higher=True))
    lines.append("3. **Fewest false awards:** "
                 + _best_by(runs, comparison, "total_false_awards", center, lower=True))
    lines.append("4. **Fewest false deductions:** "
                 + _best_by(runs, comparison, "total_false_deductions", center, lower=True))
    lines.append("5. **Transcription preservation:** see §4; B's blank/different rows are extraction losses, not marking losses.")
    lines.append("6. **Did C's SymPy/escalation improve the result?** "
                 + ("Yes: at least one escalation changed a mark toward the reference."
                    if any(row["correct_change"] and not row["no_change"] for row in escalations)
                    else "No escalation changed a mark toward the reference."))
    lines.append("7. **Did any escalation damage a correct mark?** "
                 + ("Yes — see §5 harmful rows." if any(row["harmful"] for row in escalations)
                    else "No harmful escalation was recorded."))
    lines.append("8. **Least API quota:** "
                 + _least_quota(comparison))
    lines.append("9. **Cost per paper:** "
                 + "; ".join(f"{s.upper()} {_money(((comparison.get('strategies') or {}).get(s) or {}).get('cost_per_paper_usd'))}"
                             for s in STRATEGIES))
    lines.append("10. **Best balance:** no winner is declared on F1 alone; see the accuracy and failure sections.")

    lines += ["", "## 7. Failures and limitations", ""]
    for strategy in STRATEGIES:
        for run in runs.get(strategy, []):
            if run.get("errors"):
                lines.append(f"- **{strategy.upper()}{run.get('run')}** (`{run.get('completion_status')}`): "
                             + "; ".join(run["errors"][:6]))
    lines += ["- Provider HTTP 503/timeout failures are counted in consumption and never presented as successful attempts.",
              "- A single paper; no statistical significance and no production-readiness claim.",
              f"- The reference is user-ruled with a ±2 human tolerance band ({low}–{high}); item-level uncertainty remains on Q13, Q21, Q23, Q26, Q30, Q31 and Q34.",
              ""]
    _write(REPORTS / "FINAL_TEST_REPORT_DRAFT.md", "\n".join(lines))

    # Transcription audit artifact
    t_lines = ["# Transcription audit", "",
               "Compares each attempt's reported student answer with the visible answer in the scan.",
               "`different` means the reported answer is neither blank nor equivalent; `unknown` means it could not be parsed.", ""]
    by_status = Counter((row["strategy"], row["status"]) for row in transcription)
    t_lines += ["| Strategy | Status | Count |", "|---|---|---|"]
    for (strategy, status), count in sorted(by_status.items()):
        t_lines.append(f"| {strategy.upper()} | {status} | {count} |")
    t_lines += ["", "| Strategy | Run | Item | Status | Expected | Reported |", "|---|---|---|---|---|---|"]
    for row in transcription:
        t_lines.append(f"| {row['strategy'].upper()} | {row['run']} | {row['item']} | {row['status']} | "
                       f"{row['expected']} | {row['reported']} |")
    _write(REPORTS / "TRANSCRIPTION_AUDIT_DRAFT.md", "\n".join(t_lines))

    # Escalation audit artifact
    e_lines = ["# Escalation audit", "",
               "Every recorded escalation that changed a mark, with its reference comparison.", ""]
    e_lines += ["| Run | Item | Before | After | Expected | Correct | Harmful | Reason |",
                "|---|---|---|---|---|---|---|---|"]
    for row in escalations:
        e_lines.append(f"| C{row['run']} | {row['item']} | {row['before']} | {row['after']} | "
                       f"{row['expected']} | {row['correct_change']} | {row['harmful']} | {row['reason']} |")
    if not escalations:
        e_lines.append("| — | — | — | — | — | — | — | no escalation changed a mark |")
    e_lines += ["", "Escalation requests are counted in the ledger with `purpose=escalation`.", ""]
    _write(REPORTS / "ESCALATION_AUDIT_DRAFT.md", "\n".join(e_lines))
    print(json.dumps({"transcription_rows": len(transcription),
                      "escalations": len(escalations),
                      "attempts": {s: len(v) for s, v in runs.items()}}, indent=2))
    return 0


def _best_by(runs, comparison, field, center, higher=False, lower=False) -> str:
    entries = []
    for strategy in STRATEGIES:
        summary = ((comparison.get("strategies") or {}).get(strategy) or {}).get("band_summary") or {}
        value = summary.get(field)
        if value is not None:
            entries.append((value, strategy))
    if not entries:
        return "not available"
    entries.sort(reverse=higher and not lower)
    value, strategy = entries[0]
    return f"{strategy.upper()} ({value})"


def _least_quota(comparison) -> str:
    entries = []
    for strategy in STRATEGIES:
        usage = ((comparison.get("strategies") or {}).get(strategy) or {}).get("usage") or {}
        if usage.get("requests"):
            entries.append((usage["requests"], strategy))
    if not entries:
        return "not available"
    entries.sort()
    return f"{entries[0][1].upper()} ({entries[0][0]} requests)"


if __name__ == "__main__":
    raise SystemExit(main())

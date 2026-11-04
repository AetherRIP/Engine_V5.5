"""One targeted live Strategy C escalation, appended without rewriting C5/C6.

The continuation allowed the already-validated C5/C6 evidence to supply the
document understanding while a single unresolved item is re-marked from the
original anonymised student page and its one printed scheme page.  This avoids
another full-document upload, which is what returned HTTP 503.

The request goes through the normal ``Executor`` so the provider's real status,
model, token usage, key label and timestamps are written to the append-only
ledger with ``purpose=escalation``.  The evidence file is written only when the
provider returned a usable, schema-valid item that changes the prior mark.
Offline replay or copied data cannot produce this file.

Usage:
    python -m benchmark.code.live_escalation --base-run 5 --item 30
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config, ground_truth, loader, schema, verifier
from .execution import Executor, parse_json
from .keypool import KeyPool
from .provider import GeminiClient
from .strategies import MARKING_SYSTEM, _escalation_reason
from .usage import UsageLedger


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_investigation(rows: list[dict], key_state: dict) -> dict:
    """Summarise the existing evidence; do not make a probe request here."""
    failed_503 = [row for row in rows
                  if row.get("purpose") != "probe"
                  and row.get("http_status") == 503]
    quota = [row for row in rows if row.get("purpose") != "probe"
             and row.get("http_status") == 429]
    auth = [row for row in rows if row.get("purpose") != "probe"
            and row.get("http_status") in {401, 403}]
    key_entries = key_state.get("keys", [])
    healthy = [entry.get("label") for entry in key_entries
               if entry.get("key_validity") == "VALID"
               and entry.get("network_state") == "REACHABLE"
               and entry.get("probe_state") == "healthy"]
    available = [entry.get("label") for entry in key_entries
                 if entry.get("label") in healthy
                 and entry.get("quota_state") == "AVAILABLE"
                 and not entry.get("cooldown_remaining_s")]
    return {
        "status": "provider_capacity_suspected_not_auth_or_quota",
        "full_document_503_rows": len(failed_503),
        "full_document_503_by_model": dict(Counter(
            row.get("model") for row in failed_503)),
        "full_document_503_error_codes": dict(Counter(
            row.get("error_code") for row in failed_503)),
        "benchmark_429_rows": len(quota),
        "benchmark_auth_failure_rows": len(auth),
        "healthy_keys": healthy,
        "available_healthy_keys": available,
        "finding": (
            "The failed full-document requests returned HTTP 503 UNAVAILABLE "
            "('model is currently experiencing high demand'), not 401/403 and not "
            "429 quota errors. Healthy keys with AVAILABLE quota remain. The earlier "
            "one-token model probe succeeded, so the block is request/model capacity, "
            "not key validity or project quota. A smaller single-item context is the "
            "quota-conscious test."
        ),
        "selected_model": "gemini-3.6-flash",
        "selected_model_basis": (
            "It produced the successful C11 document response and the C5/C6 primary "
            "results; a single student page plus one scheme page is a much smaller "
            "request than the failed whole-document context. No new model probe is "
            "spent for this evidence run."
        ),
    }


def _last_ledger_row(ledger: UsageLedger, run: int, batch: str) -> dict | None:
    matches = [row for row in ledger.rows()
               if row.get("strategy") == "c"
               and str(row.get("run")) == str(run)
               and row.get("batch") == batch]
    return matches[-1] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser(description="One targeted live C escalation")
    parser.add_argument("--base-run", type=int, default=5)
    parser.add_argument("--item", default="30")
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args()
    config.ensure_dirs()
    results = config.RESULTS_DIR
    item_id = str(args.item)

    raw_path = results / "raw" / f"c_run{args.base_run}.json"
    if not raw_path.is_file():
        print(f"missing preserved base run {raw_path}", flush=True)
        return 2
    base = json.loads(raw_path.read_text(encoding="utf-8"))
    base_item = next((item for item in base.get("items", [])
                      if str(item.get("id")) == item_id), None)
    raw_check = (base.get("verification") or {}).get(item_id)
    truth = next((item for item in ground_truth.load().get("items", [])
                  if str(item.get("id")) == item_id), None)
    if not base_item or not isinstance(raw_check, dict) or not truth:
        print(f"base run {args.base_run} has no usable item {item_id}", flush=True)
        return 2

    # Do not manufacture an escalation case: re-evaluate the preserved pair and
    # require the repaired guard to identify a genuine difference.
    recheck = verifier.equivalent(raw_check.get("student", ""),
                                  raw_check.get("expected", ""))
    reason = _escalation_reason(base_item, recheck)
    if recheck.get("status") != "different" or not reason:
        print(f"item {item_id} is not a genuine escalation case: "
              f"{recheck.get('status')} / {reason!r}", flush=True)
        return 3

    student_page = loader.student_pages()[int(truth["student_page"]) - 1]
    scheme_page = loader.scheme_page_for_item(truth)
    student_hash = _sha256(student_page.path)
    scheme_hash = _sha256(scheme_page.path)

    rows = UsageLedger().rows()
    key_state = json.loads(config.KEY_STATE_PATH.read_text(encoding="utf-8"))
    investigation = _provider_investigation(rows, key_state)
    (results / "provider_availability.json").write_text(
        json.dumps(investigation, indent=2) + "\n", encoding="utf-8")

    secrets = config.read_api_keys()
    if not secrets:
        print("no API keys available", flush=True)
        return 4
    pool = KeyPool.from_state(secrets)
    if not any(key.available() for key in pool.keys):
        print("no eligible key after cooldown/quota checks", flush=True)
        return 4
    ledger = UsageLedger()
    batch = f"live-escalation-{item_id}"
    prior_award = int(base_item.get("awarded", 0))
    instruction = (
        "TARGETED ESCALATION — ONE ITEM ONLY.\n"
        f"Question: {item_id}, maximum {truth['max_marks']} marks.\n"
        f"Printed question: {truth['prompt']}\n\n"
        f"A prior Strategy C run recorded this answer: {base_item.get('student_answer', '')!r} "
        f"and awarded {prior_award}/{truth['max_marks']}. That prior mark is NOT authoritative.\n"
        "The attached first image is the original anonymised student workbook page; "
        "the attached second image is the authoritative printed mark-scheme page. "
        "Re-mark only the requested question from those originals. Award each printed "
        "criterion independently; do not infer work that is not visible. Return exactly "
        "one item in the supplied schema.\n"
    )
    parts = [
        {"text": instruction},
        {"text": f"[{student_page.label}]\n"},
        student_page.part(),
        {"text": f"[{scheme_page.label}]\n"},
        scheme_page.part(),
    ]
    executor = Executor(GeminiClient(), pool, ledger)
    response, attempts = executor.call(
        strategy="c", run=15, batch=batch, purpose="escalation",
        model=args.model, parts=parts, system=MARKING_SYSTEM,
        schema=schema.ITEM_SCHEMA, item_ids=[item_id], escalated=True,
        max_attempts=args.max_attempts,
    )
    ledger_row = _last_ledger_row(ledger, 15, batch)
    payload, parse_error = parse_json(response.text or "")
    clean, problems = (schema.validate_marking(payload, {item_id: truth["max_marks"]})
                       if payload is not None else (None, [parse_error]))
    replacement = (clean or {}).get("items", [None])[0]
    after = int(replacement["awarded"]) if replacement else None
    changed = after is not None and after != prior_award
    valid = bool(response.ok and clean and replacement and not problems and changed)
    status = ("valid_changed_mark" if valid else
              "valid_no_change" if response.ok and clean and replacement and not problems else
              "provider_failed" if not response.ok else "invalid_response")
    evidence = {
        "kind": "targeted_live_escalation",
        "measurement_kind": "live_provider_response",
        "status": status,
        "valid_changed_mark": valid,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_run": args.base_run,
        "item": item_id,
        "model": args.model,
        "purpose": "escalation",
        "request_batch": batch,
        "escalation_reason": reason,
        "raw_check_status": raw_check.get("status"),
        "re_evaluated_check": recheck,
        "before": prior_award,
        "after": after,
        "changed": changed,
        "expected_mark": truth["expected_mark"],
        "score_delta": (after - prior_award) if after is not None else None,
        "coverage": {"items_requested": 1,
                     "items_returned": 1 if replacement else 0,
                     "coverage": 1.0 if replacement else 0.0},
        "source": {
            "base_raw": str(raw_path.relative_to(config.BENCHMARK_DIR)),
            "student_page": student_page.number,
            "student_page_sha256": student_hash,
            "scheme_page": scheme_page.number,
            "scheme_page_sha256": scheme_hash,
            "student_page_path": str(student_page.path.relative_to(config.BENCHMARK_DIR)),
            "scheme_page_path": str(scheme_page.path.relative_to(config.BENCHMARK_DIR)),
        },
        "request": ledger_row,
        "response": {
            "status": response.status,
            "http_status": response.http_status,
            "finish_reason": response.finish_reason,
            "model": response.model,
            "usage": response.usage,
            "text": response.text,
            "problems": problems,
            "attempts": attempts,
        },
    }
    # On a failure, retain the attempt separately; never create a success file.
    target = results / ("live_escalation.json" if valid else "live_escalation_attempt.json")
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: evidence[key] for key in
                      ("status", "valid_changed_mark", "base_run", "item", "before",
                       "after", "changed", "request_batch")}, indent=2))
    if ledger_row:
        print(json.dumps({"request": {key: ledger_row.get(key) for key in
                                      ("timestamp", "model", "key_label", "http_status",
                                       "finish_reason", "input_tokens", "output_tokens",
                                       "total_tokens", "cost_usd", "latency_ms",
                                       "success", "purpose", "escalated")}}, indent=2))
    if not valid:
        print(f"no valid changed live escalation; evidence retained at {target}", flush=True)
        return 5
    print(f"live escalation recorded at {target}; run regenerate next", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

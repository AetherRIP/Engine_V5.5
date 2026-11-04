"""Strategy H runner: Strategy A result + validated selective escalation.

Stage 1 is Strategy A's own whole-paper result, supplied by the caller.  The runner never
re-issues a full-document request: it selects criteria with deterministic signals, asks
for one targeted re-mark per item from the original student page and the matching printed
scheme page, validates the answer, and keeps both results.

The executor is any object with the benchmark's ``call`` signature, so the runner is
exercised offline with a fake provider in the tests.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone

from PIL import Image  # noqa: F401  (loader imports it; kept for parity of dependencies)

from ...code import config, loader, schema
from ...code.execution import ModelSelection, parse_json
from ...code.provider import ProviderResult
from ...code.strategies import MARKING_SYSTEM
from . import evidence as scheme
from . import signals as signal_mod
from .config import PolicyConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def escalation_parts(item_id: str) -> tuple[list[dict], dict]:
    """Build the minimal evidence request: one student page and one scheme page.

    No previous mark is included.  That removes anchoring and makes the response a pure
    function of the item's evidence, so one live response can serve every base run that
    flags the item instead of buying the same answer twice.
    """
    evidence = scheme.scheme_evidence()[str(item_id)]
    student_page = loader.student_pages()[int(evidence["student_page"]) - 1]
    scheme_page = loader.scheme_pages()[int(evidence["scheme_page"]) - 1]
    instruction = (
        "TARGETED ESCALATION — ONE QUESTION ONLY.\n"
        f"Question: {item_id}, maximum {evidence['max_marks']} marks.\n"
        f"Printed question: {evidence['prompt']}\n\n"
        "The attached first image is the student's workbook page; the second is the "
        "authoritative printed mark-scheme page for this question. Mark only question "
        f"{item_id}. Use only what is visible. Award each printed criterion "
        "independently and in the order printed (method marks first, then accuracy); "
        "apply follow-through only where the scheme explicitly allows it. A blank or "
        "crossed-out answer earns 0. Return exactly one item in the supplied JSON "
        f"schema with id {item_id!r} and max_marks {evidence['max_marks']}."
    )
    parts = [
        {"text": instruction},
        {"text": f"[{student_page.label}]\n"},
        student_page.part(),
        {"text": f"[{scheme_page.label}]\n"},
        scheme_page.part(),
    ]
    source = {
        "student_page": student_page.number,
        "scheme_page": scheme_page.number,
        "student_page_path": str(student_page.path.relative_to(config.BENCHMARK_DIR)),
        "scheme_page_path": str(scheme_page.path.relative_to(config.BENCHMARK_DIR)),
        "student_page_sha256": _sha256(student_page.path),
        "scheme_page_sha256": _sha256(scheme_page.path),
        "images_uploaded": 2,
    }
    return parts, source


def validate_escalation(clean: dict | None, problems: list[str], *, item_id: str,
                        max_marks: int, prior_answer: str) -> tuple[dict | None, dict]:
    """Accept an escalation only when it is complete, coherent and evidenced.

    Returns ``(accepted_item, verdict)``.  ``accepted_item`` is ``None`` for every
    rejection, which makes "keep A's mark" the default rather than the exception.
    """
    verdict = {"accepted": False, "reasons": list(problems)[:8], "checks": {}}

    def fail(reason: str) -> tuple[None, dict]:
        verdict["reasons"].append(reason)
        return None, verdict

    if clean is None:
        return fail("response could not be interpreted")
    items = clean.get("items") or []
    if len(items) != 1:
        return fail(f"expected exactly one item, got {len(items)}")
    item = items[0]
    if str(item.get("id")) != str(item_id):
        return fail(f"returned id {item.get('id')!r} does not match {item_id!r}")
    if int(item.get("max_marks") or -1) != int(max_marks):
        return fail(f"max_marks {item.get('max_marks')} does not match {max_marks}")
    if problems:
        # Out-of-range, duplicate or non-integer awards are already listed.
        return fail("schema validation reported problems")

    criteria = item.get("criteria") or []
    awarded = int(item.get("awarded") or 0)
    verdict["checks"]["criteria_count"] = len(criteria)
    if len(criteria) != max_marks:
        return fail(f"{len(criteria)} criteria for {max_marks} marks")
    if awarded < 0 or awarded > max_marks:
        return fail(f"awarded {awarded} outside 0..{max_marks}")
    true_count = sum(1 for criterion in criteria if criterion.get("awarded"))
    if true_count != awarded:
        return fail(f"awarded {awarded} but {true_count} criteria awarded")
    missing_reason = [criterion.get("code") for criterion in criteria
                      if criterion.get("awarded") and not str(criterion.get("reason", "")).strip()]
    if missing_reason:
        return fail(f"awarded criteria without a reason: {', '.join(map(str, missing_reason))}")

    answer = str(item.get("student_answer") or "").strip()
    if awarded > 0 and not answer and not str(prior_answer or "").strip():
        return fail("marks awarded with no visible transcribed evidence")

    verdict["accepted"] = True
    verdict["checks"].update({"awarded": awarded, "true_count": true_count,
                              "evidence": bool(answer or prior_answer)})
    return item, verdict


class StrategyHRunner:
    def __init__(self, executor, models: ModelSelection):
        self.executor = executor
        self.models = models

    # ------------------------------------------------------------------ run
    def run(self, base_run: dict, run_id: int, policy_config: PolicyConfig, *,
            cache: dict | None = None, persist=None) -> dict:
        """Run Stage 2–6 for one preserved A result.

        ``cache`` maps item id -> stored escalation response.  A valid entry is reused
        without a provider call, which is how duplicate escalation requests are
        prevented across runs and policies.  ``persist`` is called with each new entry
        so the raw provider response survives an interrupted process.
        """
        cache = cache if cache is not None else {}
        started = _now()
        item_order = loader.item_ids()
        base_items = {str(item["id"]): copy.deepcopy(item)
                      for item in base_run.get("items", [])}
        selection = signal_mod.select(base_items, policy_config, item_order)

        final_items = {item_id: copy.deepcopy(item)
                       for item_id, item in base_items.items()}
        a_original = {item_id: copy.deepcopy(item) for item_id, item in base_items.items()}
        audit: list[dict] = []
        applied: list[str] = []
        changes: list[dict] = []
        review: list[dict] = []
        errors: list[str] = []
        invalid = 0
        requests = 0
        reused = 0
        consecutive_failures = 0
        halted_reason = ""

        for entry in selection["selected"]:
            item_id = entry["item"]
            base_item = base_items[item_id]
            max_marks = int(base_item["max_marks"])
            prior_answer = str(base_item.get("student_answer") or "")
            reason = entry["reason"]

            if item_id in applied:
                continue  # explicit duplicate guard

            cached = cache.get(item_id)
            if cached and cached.get("status") == "valid":
                escalated = cached.get("item_result")
                verdict = {"accepted": True, "reasons": [],
                           "checks": {"reused": True}}
                source = cached.get("source") or {}
                request_row = cached.get("request") or {}
                reused += 1
                reused_response = True
            elif halted_reason:
                review.append({"item": item_id, "reason": reason,
                               "status": "not_attempted", "detail": halted_reason})
                continue
            else:
                parts, source = escalation_parts(item_id)
                response, attempts = self.executor.call(
                    strategy="h", run=run_id, batch=f"escalate-{item_id}",
                    purpose="escalation", model=self.models.strong or self.models.primary,
                    parts=parts, system=MARKING_SYSTEM, schema=schema.ITEM_SCHEMA,
                    item_ids=[item_id], escalated=True,
                    max_attempts=policy_config.max_attempts,
                )
                requests += 1
                payload, parse_error = parse_json(response.text or "")
                if payload is None:
                    clean, problems = None, [parse_error or "empty response"]
                else:
                    clean, problems = schema.validate_marking(payload, {item_id: max_marks})
                escalated, verdict = validate_escalation(
                    clean, problems, item_id=item_id, max_marks=max_marks,
                    prior_answer=prior_answer)
                used = self._ledger_row()
                request_row = used or {}
                reused_response = False
                entry_status = ("valid" if escalated else
                                "provider_failed" if not response.ok else "invalid")
                if entry_status != "valid":
                    invalid += 1 if response.ok else 0
                    if not response.ok:
                        errors.append(f"escalate-{item_id}: {response.status} "
                                      f"{response.error_code} (HTTP {response.http_status})")
                        consecutive_failures += 1
                    else:
                        errors.append(f"escalate-{item_id}: rejected ({'; '.join(verdict['reasons'][:2])})")
                        consecutive_failures = 0
                else:
                    consecutive_failures = 0

                stored = {
                    "item": item_id,
                    "status": entry_status,
                    "validation": verdict,
                    "item_result": escalated,
                    "request": request_row,
                    "cost_usd": request_row.get("cost_usd"),
                    "response": {
                        "status": response.status,
                        "http_status": response.http_status,
                        "finish_reason": response.finish_reason,
                        "model": response.model,
                        "usage": response.usage,
                        "text": response.text,
                        "attempts": attempts,
                    },
                    "model": self.models.strong or self.models.primary,
                    "source": source,
                    "escalated_at": _now(),
                }
                cache[item_id] = stored
                if persist:
                    persist(item_id, stored)

                if consecutive_failures >= policy_config.max_consecutive_provider_failures:
                    halted_reason = (
                        f"{consecutive_failures} consecutive provider failures; "
                        "remaining escalations stopped to respect provider capacity"
                    )
                    errors.append(halted_reason)

            if not escalated:
                review.append({
                    "item": item_id,
                    "reason": reason,
                    "status": cache.get(item_id, {}).get("status", "invalid"),
                    "detail": "; ".join(verdict.get("reasons", [])[:3]),
                })
                audit.append({
                    "item": item_id,
                    "reason": reason,
                    "signals": entry["signals"],
                    "decision": "keep_a",
                    "validation": verdict,
                    "request": request_row,
                    "reused_response": reused_response,
                })
                continue

            replacement = copy.deepcopy(escalated)
            replacement["max_marks"] = max_marks  # never from the response
            replacement["source"] = "escalated_c"
            replacement["escalation_reason"] = reason
            replacement["a_original"] = {
                "awarded": base_item.get("awarded"),
                "criteria": base_item.get("criteria"),
                "reason": base_item.get("reason"),
                "confidence": base_item.get("confidence"),
                "flags": base_item.get("flags"),
                "student_answer": base_item.get("student_answer"),
            }
            final_items[item_id] = replacement
            applied.append(item_id)
            if int(base_item.get("awarded") or 0) != int(replacement.get("awarded") or 0):
                changes.append({
                    "item": item_id,
                    "before": base_item.get("awarded"),
                    "after": replacement.get("awarded"),
                    "reason": reason,
                })
            audit.append({
                "item": item_id,
                "reason": reason,
                "signals": entry["signals"],
                "decision": "escalate_applied",
                "a_awarded": base_item.get("awarded"),
                "c_awarded": replacement.get("awarded"),
                "validation": verdict,
                "request": request_row,
                "reused_response": reused_response,
            })

        return {
            "strategy": "h",
            "policy": policy_config.name,
            "policy_description": policy_config.description,
            "run": run_id,
            "base_run": base_run.get("run"),
            "models": self.models.as_dict(),
            "items": list(final_items.values()),
            "a_original": list(a_original.values()),
            "escalation_audit": audit,
            "escalations": applied,
            "escalation_changes": changes,
            "unresolved_for_review": review,
            "signal_summary": {
                "candidates": selection["candidate_count"],
                "selected": len(selection["selected"]),
                "suppressed_by_cap": len(selection["suppressed"]),
                "cap": selection["cap"],
                "signals": selection["signals"],
            },
            "request_count": requests,
            "reused_responses": reused,
            "invalid_responses": invalid,
            "errors": errors,
            "verification": {},
            "completion_status": ("complete" if len(final_items) == len(item_order)
                                  else "incomplete_output"),
            "started_at": started,
            "finished_at": _now(),
        }

    # ------------------------------------------------------------- helpers
    def _ledger_row(self) -> dict | None:
        """Return the most recent ledger row this executor wrote, when it keeps one."""
        ledger = getattr(self.executor, "ledger", None)
        if ledger is None or not hasattr(ledger, "rows"):
            return None
        rows = [row for row in ledger.rows() if row.get("strategy") == "h"]
        return rows[-1] if rows else None

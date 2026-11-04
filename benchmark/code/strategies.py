"""The three correction strategies.

All three end in the same marking schema and use the same examiner rules.  What
differs is what the model is given and how many requests carry it:

* A — the whole paper and whole scheme in one multimodal request;
* B — extraction first (scheme, then each student page), then text-only batches;
* C — one whole-document understanding pass, a reusable scheme representation,
      Lite batch marking, SymPy checks and per-item escalation.

Extraction requests are counted under ``purpose=extraction``; marking requests
under ``purpose=marking`` and ``purpose=escalation``, so overhead is visible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config, loader, schema, verifier
from .execution import Executor, ModelSelection, parse_json
from .provider import ProviderResult

MARKING_SYSTEM = """You are an experienced mathematics examiner marking a student's handwritten workbook.
Rules you must follow:
1. Use only the printed question text, the printed mark scheme and the student's own working. Never invent work that is not visible.
2. A blank or crossed-out answer earns 0. Do not infer an answer from a mark scheme.
3. Award each printed mark-scheme criterion independently and in the order printed (method marks first, then accuracy). Apply follow-through only where the scheme explicitly allows it.
4. The awarded mark is the number of criteria you award, and must not exceed the maximum for the question.
5. Transcribe the student's final answer exactly as written; if it is illegible, say so in flags and do not award an accuracy mark on a guess.
6. Return JSON only, matching the supplied schema. Include every requested question id exactly once.
7. Use confidence 0..1 for how certain the mark is, and flags for ambiguity, illegible working, or a mismatch between the printed question and the scheme."""

EXTRACT_STUDENT_SYSTEM = """You transcribe a student's handwritten mathematics workbook for an examiner.
For every requested question, copy the printed question text, then transcribe the student's working line by line and the final answer exactly as written.
Never solve the question, never correct the student, and never add working that is not visible. If a question is blank, return an empty student_working and student_answer and say "blank" in legibility."""

EXTRACT_SCHEME_SYSTEM = """You transcribe a printed mathematics mark scheme into structured data.
For each numbered question, copy the printed criteria in order (M1, A1, B1, ...), the marks available, and the expected answer or acceptable alternatives exactly as printed.
Do not mark any student work and do not add criteria that are not printed. Render every power explicitly with caret notation (for example x^2, x^3); never use quote marks or omit a power."""

DOC_SYSTEM = """You read a complete handwritten mathematics workbook and produce a structured record of what the student wrote.
For every question, transcribe the printed question text, the student's working and final answer. Flag ambiguous handwriting and questions whose answer depends on a diagram.
Do not mark, do not correct, and do not infer missing work."""


@dataclass
class RunResult:
    strategy: str
    run: int
    models: dict
    final_items: dict[str, dict] = field(default_factory=dict)
    request_count: int = 0
    invalid_responses: int = 0
    errors: list[str] = field(default_factory=list)
    extractions: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    escalations: list[str] = field(default_factory=list)
    escalation_changes: list[dict] = field(default_factory=list)
    completion_status: str = "complete"
    splits: list[dict] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "run": self.run,
            "models": self.models,
            "items": list(self.final_items.values()),
            "request_count": self.request_count,
            "invalid_responses": self.invalid_responses,
            "errors": self.errors,
            "extractions": self.extractions,
            "verification": self.verification,
            "escalations": self.escalations,
            "escalation_changes": self.escalation_changes,
            "completion_status": self.completion_status,
            "splits": self.splits,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ids_text(ids: list[str]) -> str:
    marks = loader.max_marks()
    return "\n".join(f"- {item_id} (max {marks[item_id]})" for item_id in ids)


def _marking_user(ids: list[str], scheme_text: str, student_text: str) -> list[dict]:
    text = (
        f"Mark exactly these questions: \n{_ids_text(ids)}\n\n"
        "MARK SCHEME (authoritative):\n"
        f"{scheme_text}\n\n"
        "STUDENT WORK (as presented):\n"
        f"{student_text}\n\n"
        "Return one item per question id in the supplied JSON schema."
    )
    return [{"text": text}]


class StrategyRunner:
    def __init__(self, executor: Executor, models: ModelSelection):
        self.executor = executor
        self.models = models

    def _whole_paper_parts(self, ids: list[str], instruction: str) -> list[dict]:
        parts: list[dict] = [{"text": instruction}]
        for page in loader.student_pages():
            parts.append({"text": f"\n[{page.label}]\n"})
            parts.append(page.part())
        parts.append({"text": "\nThe following pages are the printed mark scheme for these questions.\n"})
        for page in loader.scheme_pages():
            parts.append({"text": f"\n[{page.label}]\n"})
            parts.append(page.part())
        return parts

    def run_a(self, run: int) -> RunResult:
        ids = loader.item_ids()
        result = RunResult("a", run, self.models.as_dict(), started_at=_now())
        instruction = (
            "ASSESSMENT TASK — WHOLE PAPER.\n"
            f"Mark exactly these questions: \n{_ids_text(ids)}\n\n"
            "The following pages are the student's complete workbook. Read every page, identify each numbered question and its parts, interpret the handwriting, and then apply the printed mark scheme that follows.\n"
        )
        response, _ = self.executor.call(
            strategy="a", run=run, batch="whole-paper", purpose="marking",
            model=self.models.primary, parts=self._whole_paper_parts(ids, instruction),
            system=MARKING_SYSTEM, schema=schema.ITEM_SCHEMA, item_ids=ids, max_attempts=4)
        result.request_count += 1
        self._absorb(result, response, ids)
        missing = [item_id for item_id in ids if item_id not in result.final_items]
        if not missing:
            result.completion_status = "complete"
        elif not response.ok:
            result.completion_status = "incomplete_request"
            result.errors.append(
                f"whole-paper request failed ({response.status} {response.error_code}); "
                f"{len(missing)} item(s) unresolved")
        else:
            # The provider returned HTTP 200 but the output omitted items.  The
            # plan's documented fallback is an output split, not another blind
            # repeat of the entire paper.
            result.completion_status = "incomplete_output"
            result.errors.append(
                f"whole-paper response omitted {len(missing)} of {len(ids)} item(s); "
                "classified incomplete_output")
            result.errors.append(
                "documented A split fallback triggered: missing items requested in "
                f"chunks of {config.A_SPLIT_CHUNK_SIZE}, max {config.MAX_A_SPLIT_REQUESTS} requests")
            chunks = [missing[index:index + config.A_SPLIT_CHUNK_SIZE]
                      for index in range(0, len(missing), config.A_SPLIT_CHUNK_SIZE)]
            chunks = chunks[:config.MAX_A_SPLIT_REQUESTS]
            for index, chunk in enumerate(chunks, start=1):
                split_instruction = (
                    "ASSESSMENT TASK — WHOLE PAPER COMPLETION SPLIT.\n"
                    f"Mark only these missing questions: \n{_ids_text(chunk)}\n\n"
                    "This is a documented output split after the first whole-paper response "
                    "omitted them. Use the student's complete workbook and the printed scheme "
                    "that follow; do not mark any other question id.\n"
                )
                split_response, _ = self.executor.call(
                    strategy="a", run=run, batch=f"whole-paper-split-{index}",
                    purpose="marking", model=self.models.primary,
                    parts=self._whole_paper_parts(chunk, split_instruction),
                    system=MARKING_SYSTEM, schema=schema.ITEM_SCHEMA, item_ids=chunk,
                    max_attempts=4)
                result.request_count += 1
                before = set(result.final_items)
                self._absorb(result, split_response, chunk)
                returned = sorted(set(result.final_items) - before)
                result.splits.append({
                    "request": index,
                    "batch": f"whole-paper-split-{index}",
                    "requested_ids": chunk,
                    "returned_ids": returned,
                    "finish_reason": split_response.finish_reason,
                    "status": split_response.status,
                })
                if not split_response.ok:
                    result.errors.append(
                        f"whole-paper-split-{index} failed: "
                        f"{split_response.status} {split_response.error_code}")
            remaining = [item_id for item_id in ids if item_id not in result.final_items]
            if remaining:
                result.completion_status = "incomplete_after_split"
                result.errors.append(
                    f"A split fallback left {len(remaining)} item(s) unresolved: "
                    f"{', '.join(remaining)}")
            else:
                result.completion_status = "complete_after_split"
        result.finished_at = _now()
        return result

    # ------------------------------------------------------------------ B

    def run_b(self, run: int) -> RunResult:
        ids = loader.item_ids()
        result = RunResult("b", run, self.models.as_dict(), started_at=_now())

        scheme_data, ok = self._extract_scheme(run, "b", result)
        if not ok:
            result.errors.append("scheme extraction failed; marking cannot proceed faithfully")
        student_data: dict[str, dict] = {}
        retried_ids: list[str] = []
        retry_requests = 0
        for page in loader.student_pages():
            page_ids = [item_id for item_id in ids
                        if loader.item_page_map().get(item_id) == page.number
                        and item_id not in {"12", "16d"}]
            if not page_ids:
                continue
            parts = [{"text": (
                f"Transcribe these questions from {page.label}: \n{_ids_text(page_ids)}\n"
                "Return one record per id in the schema."
            )}, page.part()]
            response, _ = self.executor.call(
                strategy="b", run=run, batch=f"extract-page-{page.number}",
                purpose="extraction", model=self.models.primary, parts=parts,
                system=EXTRACT_STUDENT_SYSTEM, schema=schema.EXTRACTION_SCHEMA,
                item_ids=page_ids, max_attempts=4)
            result.request_count += 1
            payload = self._parse_and_validate(response, result, schema.validate_extraction,
                                               page_ids)
            if payload:
                for question in payload["questions"]:
                    student_data[question["id"]] = question

            empty = [item_id for item_id in page_ids
                     if item_id not in student_data or _extraction_blank(student_data[item_id])]
            if empty:
                # One targeted re-read fixes the observed Q7/Q8/Q19 omission
                # without silently substituting ground truth.  The retry is a
                # normal extraction request in the ledger and is counted in B's
                # cost.  A truly blank question (Q37b) may still remain empty.
                retried_ids.extend(empty)
                retry_requests += 1
                retry_parts = [{"text": (
                    f"Your previous transcription omitted or left blank these questions from "
                    f"{page.label}: \n{_ids_text(empty)}\n"
                    "Re-read the attached page and transcribe their printed question text, "
                    "visible student working and final answer. Return one record per id. "
                    "Only leave an answer empty if the page is genuinely blank, and mark "
                    "legibility 'blank' in that case."
                )}, page.part()]
                retry_response, _ = self.executor.call(
                    strategy="b", run=run, batch=f"extract-page-{page.number}-retry",
                    purpose="extraction", model=self.models.primary, parts=retry_parts,
                    system=EXTRACT_STUDENT_SYSTEM, schema=schema.EXTRACTION_SCHEMA,
                    item_ids=empty, max_attempts=4)
                result.request_count += 1
                retry_payload = self._parse_and_validate(
                    retry_response, result, schema.validate_extraction, empty)
                if retry_payload:
                    for question in retry_payload["questions"]:
                        student_data[question["id"]] = question
        result.extractions = {
            "scheme_questions": len((scheme_data or {}).get("questions", [])),
            "student_questions": len(student_data),
            "retried_ids": sorted(set(retried_ids)),
            "retry_requests": retry_requests,
            "empty_after_retry": sorted(
                item_id for item_id in ids
                if item_id not in student_data or _extraction_blank(student_data[item_id])),
        }

        for batch, batch_ids in loader.batches_for_scored().items():
            missing = [item_id for item_id in batch_ids if item_id not in student_data]
            if missing:
                result.errors.append(
                    f"{batch}: no transcription for {', '.join(missing)}; left unresolved")
            usable = [item_id for item_id in batch_ids if item_id in student_data]
            if not usable:
                continue
            scheme_text = _scheme_text(scheme_data, usable)
            student_text = _student_text(student_data, usable)
            response, _ = self.executor.call(
                strategy="b", run=run, batch=batch, purpose="marking",
                model=self.models.primary,
                parts=_marking_user(usable, scheme_text, student_text),
                system=MARKING_SYSTEM, schema=schema.ITEM_SCHEMA, item_ids=usable)
            result.request_count += 1
            self._absorb(result, response, usable)
        result.completion_status = ("complete" if len(result.final_items) == len(ids)
                                   else "incomplete_output")
        result.finished_at = _now()
        return result

    # ------------------------------------------------------------------ C

    def run_c(self, run: int) -> RunResult:
        ids = loader.item_ids()
        result = RunResult("c", run, self.models.as_dict(), started_at=_now())
        if not self.models.lite:
            result.errors.append("no Lite model available; strategy C cannot run")
            result.completion_status = "blocked"
            result.finished_at = _now()
            return result

        # 1. Whole-document understanding (one multimodal pass).
        parts = [{"text": (
            "UNDERSTANDING TASK — read the whole workbook once and record what the student wrote.\n"
            f"Questions: \n{_ids_text(ids)}\n"
            "Return one record per question id. Do not mark."
        )}]
        for page in loader.student_pages():
            parts.append({"text": f"\n[{page.label}]\n"})
            parts.append(page.part())
        response, _ = self.executor.call(
            strategy="c", run=run, batch="doc-understanding", purpose="extraction",
            model=self.models.primary, parts=parts, system=DOC_SYSTEM,
            schema=schema.DOC_SCHEMA, item_ids=ids, max_attempts=4)
        result.request_count += 1
        doc_payload, doc_error = parse_json(response.text or "")
        doc_questions = {}
        if doc_payload and isinstance(doc_payload.get("questions"), list):
            for question in doc_payload["questions"]:
                if isinstance(question, dict) and str(question.get("id")) in ids:
                    doc_questions[str(question["id"])] = question
        else:
            result.invalid_responses += 1
            result.errors.append(f"document understanding invalid: {doc_error}")
        result.extractions["doc_questions"] = len(doc_questions)

        # 2. Reusable scheme representation (one multimodal pass).
        scheme_data, ok = self._extract_scheme(run, "c", result)
        if not ok:
            result.errors.append("scheme extraction failed; escalation checks are limited")

        # 3. SymPy check of transcribed answers against the scheme's expected answers.
        checks = {}
        for item_id in ids:
            expected = _expected_answer(scheme_data, item_id)
            student = str((doc_questions.get(item_id) or {}).get("student_answer", ""))
            checks[item_id] = verifier.equivalent(student, expected) if expected else {
                "status": "unknown", "detail": "no expected answer extracted"}
        result.verification = checks

        # 4. Routine marking with the Lite model, in text-only batches.
        for batch, batch_ids in loader.batches_for_scored().items():
            usable = [item_id for item_id in batch_ids if item_id in doc_questions]
            missing = [item_id for item_id in batch_ids if item_id not in doc_questions]
            if missing:
                result.errors.append(f"{batch}: understanding missing for {', '.join(missing)}")
            if not usable:
                continue
            scheme_text = _scheme_text(scheme_data, usable)
            student_text = _student_text(doc_questions, usable)
            response, _ = self.executor.call(
                strategy="c", run=run, batch=f"{batch}-lite", purpose="marking",
                model=self.models.lite,
                parts=_marking_user(usable, scheme_text, student_text),
                system=MARKING_SYSTEM, schema=schema.ITEM_SCHEMA, item_ids=usable)
            result.request_count += 1
            self._absorb(result, response, usable)

        # 5. Escalate only the items that need a stronger decision.  "Unknown"
        # is not a reason: transcription formatting makes it common and it would
        # spend the budget without evidence.  The cap keeps C a hybrid, not a
        # second whole-paper pass.
        candidates = []
        for item_id, item in list(result.final_items.items()):
            check = checks.get(item_id, {"status": "unknown"})
            reason = _escalation_reason(item, check)
            if reason:
                candidates.append((float(item.get("confidence") or 1.0), item_id, reason))
        candidates.sort()
        selected = candidates[:config.MAX_ESCALATIONS_PER_RUN]
        if len(candidates) > len(selected):
            result.errors.append(
                f"escalation cap {config.MAX_ESCALATIONS_PER_RUN} applied; "
                f"{len(candidates) - len(selected)} lower-priority item(s) not escalated")
        for _, item_id, reason in selected:
            item = result.final_items[item_id]
            scheme_text = _scheme_text(scheme_data, [item_id])
            student_text = _student_text(doc_questions, [item_id])
            response, _ = self.executor.call(
                strategy="c", run=run, batch=f"escalate-{item_id}",
                purpose="escalation", model=self.models.strong,
                parts=_marking_user([item_id], scheme_text, student_text),
                system=MARKING_SYSTEM, schema=schema.ITEM_SCHEMA, item_ids=[item_id],
                escalated=True)
            result.request_count += 1
            escalated = self._parse_and_validate(response, result, schema.validate_marking,
                                                 [item_id], marks={item_id: item["max_marks"]})
            if escalated and escalated["items"]:
                replacement = escalated["items"][0]
                before = item.get("awarded")
                after = replacement.get("awarded")
                replacement["escalation_reason"] = reason
                replacement["source"] = "escalated"
                result.final_items[item_id] = replacement
                result.escalations.append(item_id)
                if before != after:
                    result.escalation_changes.append({
                        "item": item_id, "before": before, "after": after,
                        "reason": reason,
                    })
        result.completion_status = ("complete" if len(result.final_items) == len(ids)
                                   else "incomplete_output")
        result.finished_at = _now()
        return result

    # -- shared helpers ----------------------------------------------------

    def _extract_scheme(self, run: int, strategy: str, result: RunResult) -> tuple[dict | None, bool]:
        ids = loader.item_ids()
        parts = [{"text": (
            "Transcribe the printed mark scheme for the whole paper.\n"
            f"Questions: \n{_ids_text(ids)}\n"
            "Return one record per question id with its criteria in printed order. Write powers as x^2 or x^3, never as quote marks."
        )}]
        for page in loader.scheme_pages():
            parts.append({"text": f"\n[{page.label}]\n"})
            parts.append(page.part())
        response, _ = self.executor.call(
            strategy=strategy, run=run, batch="extract-scheme", purpose="extraction",
            model=self.models.primary, parts=parts, system=EXTRACT_SCHEME_SYSTEM,
            schema=schema.SCHEME_SCHEMA, item_ids=ids, max_attempts=4)
        result.request_count += 1
        payload = self._parse_and_validate(response, result, schema.validate_scheme, ids)
        return payload, bool(payload)

    def _parse_and_validate(self, response: ProviderResult, result: RunResult, validator,
                            ids: list[str], marks: dict | None = None):
        if not response.ok:
            result.errors.append(f"request failed: {response.status} {response.error_code}")
            return None
        payload, error = parse_json(response.text)
        if payload is None:
            result.invalid_responses += 1
            result.errors.append(error)
            return None
        if marks is None:
            clean, problems = validator(payload, ids)
        else:
            clean, problems = validator(payload, marks)
        if problems:
            result.errors.extend(problems[:4])
        if clean is None:
            result.invalid_responses += 1
        return clean

    def _absorb(self, result: RunResult, response: ProviderResult, ids: list[str]) -> None:
        payload = self._parse_and_validate(response, result, schema.validate_marking, ids,
                                           marks=loader.max_marks())
        if not payload:
            return
        for item in payload["items"]:
            item["source"] = "escalated" if item.get("source") == "escalated" else "primary"
            result.final_items[item["id"]] = item


def _scheme_text(scheme_data: dict | None, ids: list[str]) -> str:
    if not scheme_data:
        return "(scheme extraction unavailable)"
    by_id = {str(question.get("id")): question for question in scheme_data.get("questions", [])}
    lines = []
    for item_id in ids:
        question = by_id.get(item_id)
        if not question:
            lines.append(f"{item_id}: scheme unavailable")
            continue
        criteria = "; ".join(f"{criterion.get('code')}: {criterion.get('text')}"
                             for criterion in question.get("criteria", []))
        lines.append(f"{item_id}: max {question.get('max_marks')}; {criteria}; "
                     f"expected: {question.get('expected_answer')}")
    return "\n".join(lines)


def _extraction_blank(question: dict) -> bool:
    return not (str(question.get("student_working", "")).strip()
                or str(question.get("student_answer", "")).strip())


def _student_text(student_data: dict, ids: list[str]) -> str:
    lines = []
    for item_id in ids:
        question = student_data.get(item_id) or {}
        lines.append(
            f"{item_id}:\n  question: {question.get('question_text', '')}\n"
            f"  working: {question.get('student_working', '')}\n"
            f"  answer: {question.get('student_answer', '')}\n"
            f"  legibility: {question.get('legibility', '')}"
        )
    return "\n".join(lines)


def _expected_answer(scheme_data: dict | None, item_id: str) -> str:
    if not scheme_data:
        return ""
    for question in scheme_data.get("questions", []):
        if str(question.get("id")) == item_id:
            return str(question.get("expected_answer", ""))
    return ""


def _escalation_reason(item: dict, check: dict) -> str:
    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.6:
        return "low confidence"
    flags = " ".join(item.get("flags") or []).lower()
    if "ambig" in flags or "illegib" in flags or "mismatch" in flags:
        return "flagged ambiguous or illegible"
    if check.get("status") == "different":
        return "SymPy says transcribed answer differs from the scheme's expected answer"
    return ""

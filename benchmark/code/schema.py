"""Response schema and defensive validation for marking output.

The same schema is sent to every strategy, so a difference in accuracy cannot
come from a difference in output shape.  Validation is local (no dependency on
a schema library) and returns structured problems instead of raising, because a
malformed response is a measurement, not a crash.
"""

from __future__ import annotations

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "student_answer": {"type": "string"},
                    "awarded": {"type": "integer"},
                    "max_marks": {"type": "integer"},
                    "criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "awarded": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["code", "awarded"],
                        },
                    },
                    "confidence": {"type": "number"},
                    "flags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["id", "awarded", "criteria"],
            },
        },
        "paper_total": {"type": "integer"},
        "notes": {"type": "string"},
    },
    "required": ["items"],
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question_text": {"type": "string"},
                    "student_working": {"type": "string"},
                    "student_answer": {"type": "string"},
                    "legibility": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["id", "question_text", "student_working", "student_answer"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["questions"],
}

SCHEME_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question_text": {"type": "string"},
                    "max_marks": {"type": "integer"},
                    "criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["code", "text"],
                        },
                    },
                    "expected_answer": {"type": "string"},
                },
                "required": ["id", "criteria"],
            },
        }
    },
    "required": ["questions"],
}

DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question_text": {"type": "string"},
                    "student_working": {"type": "string"},
                    "student_answer": {"type": "string"},
                    "confidence": {"type": "number"},
                    "ambiguous": {"type": "boolean"},
                    "visual_dependency": {"type": "boolean"},
                },
                "required": ["id", "student_working", "student_answer"],
            },
        },
        "document_notes": {"type": "string"},
    },
    "required": ["questions"],
}


def validate_marking(payload: object, expected: dict[str, int]) -> tuple[dict | None, list[str]]:
    """Validate a marking payload against ``{item_id: max_marks}``.

    Returns ``(clean_payload, problems)``.  A payload with a problem is still
    returned when it is usable (so partial credit can be measured); ``None``
    means it could not be interpreted at all.
    """
    problems: list[str] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None, ["payload is not an object with an items array"]

    clean_items = []
    seen: set[str] = set()
    for raw in payload["items"]:
        if not isinstance(raw, dict):
            problems.append("item is not an object")
            continue
        item_id = str(raw.get("id", "")).strip()
        if item_id not in expected:
            problems.append(f"unknown item id {item_id!r}")
            continue
        if item_id in seen:
            problems.append(f"duplicate item id {item_id!r}")
            continue
        seen.add(item_id)
        try:
            awarded = int(raw.get("awarded"))
        except (TypeError, ValueError):
            problems.append(f"{item_id}: awarded is not an integer")
            continue
        if awarded < 0 or awarded > expected[item_id]:
            problems.append(f"{item_id}: awarded {awarded} outside 0..{expected[item_id]}")
            awarded = max(0, min(expected[item_id], awarded))

        criteria = []
        for criterion in raw.get("criteria") or []:
            if not isinstance(criterion, dict):
                continue
            criteria.append({
                "code": str(criterion.get("code", ""))[:20],
                "awarded": bool(criterion.get("awarded")),
                "reason": str(criterion.get("reason", ""))[:300],
            })

        flags = [str(flag)[:80] for flag in (raw.get("flags") or [])][:6]
        clean_items.append({
            "id": item_id,
            "student_answer": str(raw.get("student_answer", ""))[:800],
            "awarded": awarded,
            "max_marks": expected[item_id],
            "criteria": criteria,
            "confidence": _confidence(raw.get("confidence")),
            "flags": flags,
            "reason": str(raw.get("reason", ""))[:600],
        })

    missing = [item_id for item_id in expected if item_id not in seen]
    if missing:
        problems.append(f"missing items: {', '.join(missing)}")
    if not clean_items:
        return None, problems
    return {"items": clean_items, "paper_total": sum(item["awarded"] for item in clean_items),
            "notes": str(payload.get("notes", ""))[:1000]}, problems


def _confidence(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return max(0.0, min(1.0, number))


def validate_extraction(payload: object, expected_ids: list[str]) -> tuple[dict | None, list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        return None, ["payload is not an object with a questions array"]
    problems: list[str] = []
    seen: set[str] = set()
    questions = []
    for raw in payload["questions"]:
        if not isinstance(raw, dict):
            problems.append("question is not an object")
            continue
        item_id = str(raw.get("id", "")).strip()
        if item_id not in expected_ids:
            problems.append(f"unknown id {item_id!r}")
            continue
        if item_id in seen:
            problems.append(f"duplicate id {item_id!r}")
            continue
        seen.add(item_id)
        questions.append({
            "id": item_id,
            "question_text": str(raw.get("question_text", ""))[:800],
            "student_working": str(raw.get("student_working", ""))[:2000],
            "student_answer": str(raw.get("student_answer", ""))[:800],
            "legibility": str(raw.get("legibility", ""))[:100],
            "notes": str(raw.get("notes", ""))[:400],
        })
    missing = [item_id for item_id in expected_ids if item_id not in seen]
    if missing:
        problems.append(f"missing ids: {', '.join(missing)}")
    return ({"questions": questions} if questions else None), problems


def validate_scheme(payload: object, expected_ids: list[str]) -> tuple[dict | None, list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        return None, ["payload is not an object with a questions array"]
    problems: list[str] = []
    questions = []
    for raw in payload["questions"]:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id", "")).strip()
        if item_id not in expected_ids:
            problems.append(f"unknown id {item_id!r}")
            continue
        criteria = []
        for criterion in raw.get("criteria") or []:
            if isinstance(criterion, dict):
                criteria.append({"code": str(criterion.get("code", ""))[:20],
                                 "text": str(criterion.get("text", ""))[:400]})
        questions.append({"id": item_id, "question_text": str(raw.get("question_text", ""))[:600],
                          "max_marks": raw.get("max_marks"),
                          "criteria": criteria,
                          "expected_answer": str(raw.get("expected_answer", ""))[:600]})
    missing = [item_id for item_id in expected_ids if item_id not in {q["id"] for q in questions}]
    if missing:
        problems.append(f"missing ids: {', '.join(missing)}")
    return ({"questions": questions} if questions else None), problems

"""Strict schemas for holdout intake records.

Rules that matter:

* intake records are exact: unknown keys are rejected, so a typo cannot silently become
  metadata and a reference award cannot be smuggled into the item registry;
* criterion codes are extensible, but the codes the scorer cannot pair are reported
  separately instead of rejected, because rejecting them would block legitimate papers;
* every validator returns a list of problems and never raises for bad data, so the CLI can
  report all problems at once.  ``load_*`` helpers raise for callers that need one object.

Nothing here writes files and nothing here talks to a provider.
"""

from __future__ import annotations

import re
from datetime import date

from . import compatibility, manifest, store

CODE_PATTERN = re.compile(r"^[A-Z]{1,2}[0-9][A-Za-z]{0,4}$")
MARKER_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,31}$")
KNOWN_SCORING_CODES = {"M1", "M2", "A1", "A2", "B1", "B2"}
CERTIFICATION_STATUSES = {"draft", "attested_pending_approval"}
SIGNATURE_ROLES = {"marker_a", "marker_b", "adjudicator", "data_custodian"}
EXTERNAL_FORM_LOCATIONS = {"school_custody", "external_archive"}

_SIGNATURE_KEYS = {"signer_id", "role", "kind", "signed_on", "declaration",
                   "form_sha256", "form_location", "identity_verified", "notes"}
_AUDIT_KEYS = {"item", "recorded_marks", "audit_marks", "agrees", "note"}
CUSTODIAN_ORIGINS = {"independent_series", "school_assessment", "external_archive"}
_CUSTODIAN_KEYS = {"custodian_id", "paper_id", "role", "kind", "signed_on",
                   "declaration", "source_origin", "anonymisation_method",
                   "source_documentation", "pixel_review", "metadata_review",
                   "handwriting_review", "paper_not_design_paper",
                   "understands_limits", "form_sha256", "form_location",
                   "identity_verified", "notes"}
_APPROVAL_KEYS = {"approver_id", "role", "approved_on", "declaration",
                  "revision_id", "evidence_sha256", "evidence_location",
                  "identity_verified", "notes"}

_REGISTRY_KEYS = {"paper_id", "items", "notes", "source"}
_ITEM_KEYS = {"id", "max_marks", "order", "scheme_page", "student_page",
              "scheme_ref", "criteria", "prompt", "notes"}
_CRITERION_KEYS = {"code", "text", "notes"}
_SHEET_KEYS = {"paper_id", "marker_id", "role", "kind", "signed_on", "declaration",
               "items", "source_sha256", "notes"}
_SHEET_ITEM_KEYS = {"id", "criteria", "ambiguous", "illegible", "evidence", "notes"}
_SHEET_CRITERION_KEYS = {"code", "awarded", "note", "key"}
_ADJUDICATION_KEYS = {"paper_id", "adjudicator", "kind", "signed_on", "audit_sample",
                      "disagreements", "exclusions", "third_marks", "notes"}
_DISAGREEMENT_KEYS = {"item", "criterion", "resolution", "rationale", "resolved_by"}
_EXCLUSION_KEYS = {"item", "reason", "marks", "evidence"}
_THIRD_MARK_KEYS = {"item", "criteria"}
_CERTIFICATION_KEYS = {"paper_id", "title", "kind", "status", "generated_at",
                       "protocol_version", "record_version", "reference_sha256",
                       "sources", "frozen", "markers", "adjudicator", "coverage",
                       "agreement", "disagreements", "exclusions", "pending",
                       "signatures", "verification", "notes"}
_REFERENCE_KEYS = {"paper_id", "title", "verification", "totals", "items", "exclusions",
                   "reference_source", "derivation", "notes"}
_REFERENCE_ITEM_KEYS = {"id", "prompt", "student_page", "scheme_page", "scheme_ref",
                        "max_marks", "criteria", "expected_mark", "status",
                        "confidence", "evidence"}


class SchemaError(ValueError):
    """A record failed schema validation."""


# ------------------------------------------------------------------------ primitives
def _reject_unknown_keys(obj: dict, allowed: set[str], where: str,
                         problems: list[str]) -> None:
    for key in obj:
        if key not in allowed:
            problems.append(f"{where}: unexpected key {key!r}")


def _text(value: object, where: str, problems: list[str], *, minimum: int = 1,
          maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        problems.append(f"{where}: text is shorter than {minimum} characters")
    if len(text) > maximum:
        problems.append(f"{where}: text is longer than {maximum} characters")
    return text


def _positive_int(value: object, where: str, problems: list[str], *,
                  maximum: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        problems.append(f"{where}: must be a positive integer")
        return None
    if maximum is not None and value > maximum:
        problems.append(f"{where}: must be at most {maximum}")
        return None
    return value


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _valid_date(value: object) -> bool:
    try:
        date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return True


def registry_items(registry: dict) -> list[dict]:
    items = registry.get("items") if isinstance(registry, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def criterion_keys(item: dict) -> list[str]:
    """Stable criterion identity: ``CODE#occurrence`` in printed order."""
    keys: list[str] = []
    counts: dict[str, int] = {}
    for criterion in item.get("criteria") or []:
        code = str(criterion.get("code", "")).strip()
        index = counts.get(code, 0)
        counts[code] = index + 1
        keys.append(f"{code}#{index}")
    return keys


def resolve_criterion_key(raw: object, item: dict) -> tuple[str | None, str | None]:
    """Resolve an adjudication label to a criterion key, or explain the ambiguity."""
    text = str(raw or "").strip()
    keys = criterion_keys(item)
    item_id = item.get("id")
    if not text:
        return None, f"criterion is empty for item {item_id!r}"
    if "#" in text:
        return (text, None) if text in keys else (
            None, f"unknown criterion {text!r} for item {item_id!r}")
    matching = [key for key in keys if key.split("#")[0] == text]
    if len(matching) == 1:
        return matching[0], None
    if not matching:
        return None, f"unknown criterion {text!r} for item {item_id!r}"
    return None, (f"criterion {text!r} is ambiguous for item {item_id!r}; "
                  f"use {matching[0]}")


def _validate_criterion_list(criteria: object, registry_item: dict, where: str,
                             problems: list[str]) -> None:
    """Compare a marker/third-marker criterion list with the printed registry list."""
    expected_codes = [str(c.get("code", "")) for c in registry_item.get("criteria") or []]
    if not isinstance(criteria, list):
        problems.append(f"{where}: criteria is not a list")
        return
    actual_codes = [str(c.get("code", "")).strip() if isinstance(c, dict) else ""
                    for c in criteria]
    if len(actual_codes) != len(expected_codes):
        problems.append(f"{where}: expected {len(expected_codes)} criteria, "
                        f"found {len(actual_codes)}")
        return
    expected_counts: dict[str, int] = {}
    actual_counts: dict[str, int] = {}
    for code in expected_codes:
        expected_counts[code] = expected_counts.get(code, 0) + 1
    for code in actual_codes:
        actual_counts[code] = actual_counts.get(code, 0) + 1
    for code, count in sorted(actual_counts.items()):
        if count > expected_counts.get(code, 0):
            problems.append(f"{where}: unknown or duplicated criterion {code!r}")
    for code, count in sorted(expected_counts.items()):
        if actual_counts.get(code, 0) < count:
            problems.append(f"{where}: missing criterion {code!r}")
    for index, (actual, expected) in enumerate(zip(actual_codes, expected_codes)):
        if actual != expected:
            problems.append(f"{where}: criterion {index + 1} is {actual!r}, "
                            f"expected {expected!r} (order matters)")


# --------------------------------------------------------------------- item registry
def validate_items_registry(data: object) -> list[str]:
    """Validate the custodian's independently transcribed printed item registry."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["item registry is not an object"]
    _reject_unknown_keys(data, _REGISTRY_KEYS, "registry", problems)
    try:
        store.validate_paper_id(data.get("paper_id"))
    except store.StoreError as error:
        problems.append(str(error))

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return problems + ["item registry has no items"]
    if len(items) < manifest.MIN_ITEMS_PER_PAPER:
        problems.append(f"at least {manifest.MIN_ITEMS_PER_PAPER} items are required "
                        f"(found {len(items)})")

    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for index, item in enumerate(items):
        where = f"items[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: item is not an object")
            continue
        _reject_unknown_keys(item, _ITEM_KEYS, where, problems)
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            problems.append(f"{where}: id is missing")
        elif item_id in seen_ids:
            problems.append(f"{where}: duplicate item id {item_id!r}")
        else:
            seen_ids.add(item_id)

        max_marks = _positive_int(item.get("max_marks"), f"{where}.max_marks", problems,
                                  maximum=10)
        order = _positive_int(item.get("order"), f"{where}.order", problems)
        if "student_page" in item:
            _positive_int(item.get("student_page"), f"{where}.student_page", problems)
        if "scheme_ref" in item:
            _text(item.get("scheme_ref"), f"{where}.scheme_ref", problems,
                  maximum=400)
        if order is not None:
            if order in seen_orders:
                problems.append(f"{where}: duplicate order {order}")
            seen_orders.add(order)
        _positive_int(item.get("scheme_page"), f"{where}.scheme_page", problems)
        if "prompt" in item:
            _text(item.get("prompt"), f"{where}.prompt", problems, maximum=1000)

        criteria = item.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            problems.append(f"{where}: criteria is missing")
            continue
        if max_marks is not None and len(criteria) != max_marks:
            problems.append(f"{where}: criteria count {len(criteria)} does not match "
                            f"max_marks {max_marks}")
        for criterion_index, criterion in enumerate(criteria):
            criterion_where = f"{where}.criteria[{criterion_index}]"
            if not isinstance(criterion, dict):
                problems.append(f"{criterion_where}: criterion is not an object")
                continue
            if "awarded" in criterion or "expected_mark" in criterion:
                problems.append(f"{criterion_where}: registry must not contain awards")
            _reject_unknown_keys(criterion, _CRITERION_KEYS, criterion_where, problems)
            code = str(criterion.get("code", "")).strip()
            if not CODE_PATTERN.match(code):
                problems.append(f"{criterion_where}: invalid criterion code {code!r}")
            _text(criterion.get("text"), f"{criterion_where}.text", problems,
                  maximum=1000)

    if seen_orders and seen_orders != set(range(1, len(items) + 1)):
        problems.append(f"item order must be contiguous 1..{len(items)}")
    return problems


def load_items_registry(path) -> dict:
    data = store.read_json(path)
    problems = validate_items_registry(data)
    if problems:
        raise SchemaError("; ".join(problems))
    return data


def scoring_compatibility(registry: dict) -> dict:
    """Delegate to the explicit compatibility layer so intake and scoring agree."""
    report = compatibility.report(registry)
    return {
        "scoring_ready": report["scoreable"],
        "unknown_codes": report["unsupported_codes"],
        "lossy_codes": report["lossy_codes"],
        "known_codes": [entry["code"] for entry in report["codes"]
                        if entry["supported"]],
        "report_sha256": report["report_sha256"],
        "note": ("Codes outside exact M1/M2/A1/A2/B1/B2 or an approved DEP alias "
                 "must be resolved before evaluation."),
    }


def _normalise_like_evaluator(code: object) -> str:
    text = str(code or "").strip().upper().replace("DEP", "")
    match = re.search(r"(M1|M2|A1|A2|B1|B2)", text)
    return match.group(1) if match else text


# ---------------------------------------------------------------------- marker sheet
def validate_marker_sheet(sheet: object, registry: dict, *, expected_role: str | None = None,
                          expected_marker_id: str | None = None) -> list[str]:
    problems: list[str] = []
    if not isinstance(sheet, dict):
        return ["marker sheet is not an object"]
    if not registry_items(registry):
        return ["marker sheet cannot be validated without a valid item registry"]
    _reject_unknown_keys(sheet, _SHEET_KEYS, "sheet", problems)

    paper_id = str(sheet.get("paper_id", "")).strip()
    if paper_id != str(registry.get("paper_id")):
        problems.append(f"sheet paper_id {paper_id!r} does not match the registry")
    role = str(sheet.get("role", "")).strip()
    if role not in {"marker_a", "marker_b"}:
        problems.append(f"sheet role {role!r} must be marker_a or marker_b")
    if expected_role and role != expected_role:
        problems.append(f"sheet role {role!r} does not match expected {expected_role!r}")
    marker_id = str(sheet.get("marker_id", "")).strip()
    if not MARKER_ID_PATTERN.match(marker_id):
        problems.append(f"marker_id {marker_id!r} is not a valid pseudonymous id")
    if expected_marker_id and marker_id != expected_marker_id:
        problems.append(f"marker_id {marker_id!r} does not match expected "
                        f"{expected_marker_id!r}")
    if "source_sha256" in sheet:
        digest = sheet.get("source_sha256")
        if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
            problems.append("source_sha256 must be a sha256 hex digest")
    if sheet.get("kind") != "human_teacher":
        problems.append("marker kind must be human_teacher; AI marking is not certification")
    if not _valid_date(sheet.get("signed_on")):
        problems.append("signed_on must be an ISO date (YYYY-MM-DD)")
    _text(sheet.get("declaration"), "declaration", problems, minimum=10, maximum=600)

    registry_by_id = {str(item.get("id")): item for item in registry_items(registry)}
    items = sheet.get("items")
    if not isinstance(items, list):
        return problems + ["sheet items is not a list"]
    seen: set[str] = set()
    for index, item in enumerate(items):
        where = f"sheet.items[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: item is not an object")
            continue
        item_id = str(item.get("id", "")).strip()
        if item_id in seen:
            problems.append(f"{where}: duplicate item id {item_id!r}")
            continue
        seen.add(item_id)
        registry_item = registry_by_id.get(item_id)
        if registry_item is None:
            problems.append(f"{where}: unknown item {item_id!r}")
            continue
        _reject_unknown_keys(item, _SHEET_ITEM_KEYS, where, problems)
        for flag in ("ambiguous", "illegible"):
            if flag in item and not _is_bool(item.get(flag)):
                problems.append(f"{where}.{flag}: must be a boolean")
        if "evidence" in item:
            _text(item.get("evidence"), f"{where}.evidence", problems, minimum=1,
                  maximum=2000)
        criteria = item.get("criteria")
        _validate_criterion_list(criteria, registry_item, where, problems)
        key_counts: dict[str, int] = {}
        for criterion_index, criterion in enumerate(criteria if isinstance(criteria, list)
                                                    else []):
            criterion_where = f"{where}.criteria[{criterion_index}]"
            if not isinstance(criterion, dict):
                problems.append(f"{criterion_where}: criterion is not an object")
                continue
            _reject_unknown_keys(criterion, _SHEET_CRITERION_KEYS, criterion_where,
                                 problems)
            if not _is_bool(criterion.get("awarded")):
                problems.append(f"{criterion_where}: awarded must be a boolean")
            if "key" in criterion:
                code = str(criterion.get("code", ""))
                occurrence = key_counts.get(code, 0)
                key_counts[code] = occurrence + 1
                expected_key = f"{code}#{occurrence}"
                if str(criterion.get("key")) != expected_key:
                    problems.append(f"{criterion_where}: key does not match its code and "
                                    f"position (expected {expected_key!r})")
            if "note" in criterion:
                _text(criterion.get("note"), f"{criterion_where}.note", problems,
                      minimum=0, maximum=600)

    missing = [item_id for item_id in registry_by_id if item_id not in seen]
    for item_id in sorted(missing):
        problems.append(f"sheet: missing item {item_id!r}")
    if len(seen) != len(items):
        problems.append("sheet: item ids are not unique")
    return problems


# ---------------------------------------------------------------------- adjudication
def validate_adjudication(record: object, registry: dict) -> list[str]:
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["adjudication is not an object"]
    if not registry_items(registry):
        return ["adjudication cannot be validated without a valid item registry"]
    _reject_unknown_keys(record, _ADJUDICATION_KEYS, "adjudication", problems)

    if str(record.get("paper_id", "")).strip() != str(registry.get("paper_id")):
        problems.append("adjudication paper_id does not match the registry")
    adjudicator = str(record.get("adjudicator", "")).strip()
    if not MARKER_ID_PATTERN.match(adjudicator):
        problems.append(f"adjudicator {adjudicator!r} is not a valid pseudonymous id")
    if record.get("kind") != "human_teacher":
        problems.append("adjudicator kind must be human_teacher")
    if not _valid_date(record.get("signed_on")):
        problems.append("adjudication signed_on must be an ISO date")

    registry_by_id = {str(item.get("id")): item for item in registry_items(registry)}
    required_sample = max(1, int(0.10 * len(registry_by_id)))
    sample = record.get("audit_sample")
    if not isinstance(sample, list):
        problems.append("audit_sample must be a list of item ids")
    else:
        sample_ids = [str(item) for item in sample]
        if len(set(sample_ids)) != len(sample_ids):
            problems.append("audit_sample contains duplicate item ids")
        for item_id in sample_ids:
            if item_id not in registry_by_id:
                problems.append(f"audit_sample: unknown item {item_id!r}")
        if len(sample_ids) < required_sample:
            problems.append(f"audit_sample must include at least {required_sample} items "
                            f"(10% of the paper)")

    exclusions = record.get("exclusions")
    excluded_ids: set[str] = set()
    if not isinstance(exclusions, list):
        problems.append("exclusions must be a list")
        exclusions = []
    for index, exclusion in enumerate(exclusions):
        where = f"exclusions[{index}]"
        if not isinstance(exclusion, dict):
            problems.append(f"{where}: exclusion is not an object")
            continue
        _reject_unknown_keys(exclusion, _EXCLUSION_KEYS, where, problems)
        item_id = str(exclusion.get("item", "")).strip()
        if item_id in excluded_ids:
            problems.append(f"{where}: duplicate exclusion for {item_id!r}")
        excluded_ids.add(item_id)
        registry_item = registry_by_id.get(item_id)
        if registry_item is None:
            problems.append(f"{where}: unknown item {item_id!r}")
        if exclusion.get("reason") not in manifest.ALLOWED_EXCLUSIONS:
            problems.append(f"{where}: unknown exclusion reason "
                            f"{exclusion.get('reason')!r}")
        marks = exclusion.get("marks")
        if isinstance(marks, bool) or not isinstance(marks, int) or marks < 0:
            problems.append(f"{where}: marks must be a non-negative integer")
        elif registry_item is not None and marks != registry_item.get("max_marks"):
            problems.append(f"{where}: exclusion marks {marks} do not match the printed "
                            f"maximum {registry_item.get('max_marks')}")
        _text(exclusion.get("evidence"), f"{where}.evidence", problems, minimum=10,
              maximum=2000)

    disagreements = record.get("disagreements")
    seen_pairs: set[tuple[str, str]] = set()
    third_items: set[str] = set()
    if not isinstance(disagreements, list):
        problems.append("disagreements must be a list")
        disagreements = []
    for index, disagreement in enumerate(disagreements):
        where = f"disagreements[{index}]"
        if not isinstance(disagreement, dict):
            problems.append(f"{where}: disagreement is not an object")
            continue
        _reject_unknown_keys(disagreement, _DISAGREEMENT_KEYS, where, problems)
        item_id = str(disagreement.get("item", "")).strip()
        registry_item = registry_by_id.get(item_id)
        if registry_item is None:
            problems.append(f"{where}: unknown item {item_id!r}")
            continue
        key, problem = resolve_criterion_key(disagreement.get("criterion"), registry_item)
        if problem:
            problems.append(f"{where}: {problem}")
            continue
        pair = (item_id, key)
        if pair in seen_pairs:
            problems.append(f"{where}: duplicate record for {item_id}/{key}")
        seen_pairs.add(pair)
        resolution = disagreement.get("resolution")
        if resolution not in manifest.ALLOWED_RESOLUTIONS:
            problems.append(f"{where}: resolution {resolution!r} is not allowed")
        _text(disagreement.get("rationale"), f"{where}.rationale", problems, minimum=10,
              maximum=2000)
        resolved_by = disagreement.get("resolved_by")
        if resolved_by is not None and str(resolved_by) != adjudicator:
            problems.append(f"{where}: resolved_by must be the adjudicator "
                            f"{adjudicator!r}")
        if resolution == "third":
            third_items.add(item_id)

    third_marks = record.get("third_marks")
    seen_third: set[str] = set()
    if third_marks is None:
        third_marks = []
    if not isinstance(third_marks, list):
        problems.append("third_marks must be a list")
        third_marks = []
    for index, entry in enumerate(third_marks):
        where = f"third_marks[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: third marker record is not an object")
            continue
        _reject_unknown_keys(entry, _THIRD_MARK_KEYS, where, problems)
        item_id = str(entry.get("item", "")).strip()
        if item_id in seen_third:
            problems.append(f"{where}: duplicate third-marker record for {item_id!r}")
        seen_third.add(item_id)
        registry_item = registry_by_id.get(item_id)
        if registry_item is None:
            problems.append(f"{where}: unknown item {item_id!r}")
            continue
        if item_id not in third_items:
            problems.append(f"{where}: third-marker marks for {item_id!r} are not "
                            "referenced by any 'third' resolution")
        _validate_criterion_list(entry.get("criteria"), registry_item, where, problems)
        for criterion_index, criterion in enumerate(
                entry.get("criteria") if isinstance(entry.get("criteria"), list) else []):
            if not isinstance(criterion, dict):
                continue
            if not _is_bool(criterion.get("awarded")):
                problems.append(f"{where}.criteria[{criterion_index}]: awarded must be "
                                "a boolean")

    return problems


# --------------------------------------------------------------------- certification
def validate_certification_record(certification: object, registry: dict | None = None) -> list[str]:
    """Validate a generated certification block against the protocol rules."""
    problems: list[str] = []
    if not isinstance(certification, dict):
        return ["certification is not an object"]
    _reject_unknown_keys(certification, _CERTIFICATION_KEYS, "certification", problems)
    if not str(certification.get("paper_id", "")).strip():
        problems.append("certification paper_id is missing")
    reference_sha = certification.get("reference_sha256")
    if reference_sha is not None and not (
            isinstance(reference_sha, str) and re.fullmatch(r"[0-9a-f]{64}", reference_sha)):
        problems.append("certification reference_sha256 must be a sha256 hex digest")
    if certification.get("status") == "certified":
        problems.append("status 'certified' must be set by human registration, not by "
                        "the certification generator")
    elif certification.get("status") is not None and \
            certification.get("status") not in CERTIFICATION_STATUSES:
        problems.append(f"unknown certification status {certification.get('status')!r}")
    signatures = certification.get("signatures")
    if signatures is not None:
        if not isinstance(signatures, dict):
            problems.append("signatures must be an object keyed by role")
        else:
            for role, evidence in signatures.items():
                if role not in SIGNATURE_ROLES:
                    problems.append(f"signatures: unknown role {role!r}")
                problems.extend(validate_signature_evidence(evidence))
    # The semantic rules live in one place already; reuse them rather than fork them.
    problems.extend(manifest.validate_certification_block(certification))

    if registry is not None and registry_items(registry):
        coverage = certification.get("coverage") or {}
        items = registry_items(registry)
        if coverage.get("items_total") != len(items):
            problems.append("certification items_total does not match the item registry")
        expected_criteria = sum(int(item.get("max_marks") or 0) for item in items)
        if coverage.get("criteria_total") != expected_criteria:
            problems.append("certification criteria_total does not match the printed "
                            "maximums")
    return problems


# ------------------------------------------------------------------------- reference
def validate_reference_record(reference: object) -> list[str]:
    """Validate a derived reference, including the fields the scorer reads."""
    problems: list[str] = []
    if not isinstance(reference, dict):
        return ["reference is not an object"]
    _reject_unknown_keys(reference, _REFERENCE_KEYS, "reference", problems)
    problems.extend(manifest.validate_reference_data(reference))

    verification = reference.get("verification")
    if not isinstance(verification, dict) or not str(verification.get("status", "")).strip():
        problems.append("reference verification.status is missing; the scorer reads it")
    totals = reference.get("totals")
    if not isinstance(totals, dict):
        problems.append("reference totals are missing")
    elif isinstance(totals.get("candidate_marks_awarded"), bool) or not isinstance(
            totals.get("candidate_marks_awarded"), int):
        problems.append("reference totals.candidate_marks_awarded must be an integer")

    items = reference.get("items")
    if not isinstance(items, list):
        return problems + ["reference items is not a list"]
    for exclusion in reference.get("exclusions") or []:
        if not isinstance(exclusion, dict):
            problems.append("reference exclusion is not an object")
            continue
        if str(exclusion.get("id", "")).strip() in {str(item.get("id"))
                                                     for item in items if isinstance(item, dict)}:
            problems.append(f"excluded item {exclusion.get('id')!r} also appears in "
                            "the scored items")
        if not str(exclusion.get("status", "")).startswith("excluded"):
            problems.append(f"exclusion {exclusion.get('id')!r} has no excluded status")
    seen: set[str] = set()
    for index, item in enumerate(items):
        where = f"items[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: item is not an object")
            continue
        _reject_unknown_keys(item, _REFERENCE_ITEM_KEYS, where, problems)
        item_id = str(item.get("id", "")).strip()
        if item_id in seen:
            problems.append(f"{where}: duplicate item id {item_id!r}")
        seen.add(item_id)
        if item.get("status") == "scored":
            _text(item.get("evidence"), f"{where}.evidence", problems, minimum=1,
                  maximum=2000)
    return problems


# --------------------------------------------------------------- human attestations
def validate_signature_evidence(evidence: object, *, expected_signer_id: str | None = None,
                                expected_role: str | None = None) -> list[str]:
    """Validate one detached-signature record.

    The hash proves the signed form has not changed.  It says nothing about who signed it:
    ``identity_verified`` must stay false until a real identity check exists.
    """
    problems: list[str] = []
    if not isinstance(evidence, dict):
        return ["signature evidence is not an object"]
    _reject_unknown_keys(evidence, _SIGNATURE_KEYS, "signature", problems)
    role = str(evidence.get("role", "")).strip()
    if role not in SIGNATURE_ROLES:
        problems.append(f"signature role {role!r} is not a certification role")
    if expected_role and role != expected_role:
        problems.append(f"signature role {role!r} does not match expected {expected_role!r}")
    signer = str(evidence.get("signer_id", "")).strip()
    if not MARKER_ID_PATTERN.match(signer):
        problems.append(f"signer_id {signer!r} is not a pseudonymous id")
    if expected_signer_id and signer != expected_signer_id:
        problems.append(f"signer_id {signer!r} does not match {expected_signer_id!r}")
    if evidence.get("kind") != "human_teacher":
        problems.append("signature kind must be human_teacher")
    if not _valid_date(evidence.get("signed_on")):
        problems.append("signature signed_on must be an ISO date")
    declaration = _text(evidence.get("declaration"), "signature.declaration", problems,
                        minimum=20, maximum=1000)
    digest = evidence.get("form_sha256")
    if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
        problems.append("form_sha256 must be a lowercase sha256 hex digest")
    elif set(digest) == {"0"}:
        problems.append("form_sha256 must not be a placeholder")
    if evidence.get("form_location") not in EXTERNAL_FORM_LOCATIONS:
        problems.append("form_location must name external custody "
                        f"({', '.join(sorted(EXTERNAL_FORM_LOCATIONS))})")
    if evidence.get("identity_verified") is not False:
        problems.append("identity_verified must be false: a detached hash proves "
                        "integrity, not identity")
    for label in find_identifying_information(declaration):
        problems.append(f"signature.declaration contains {label}")
    if evidence.get("notes"):
        for label in find_identifying_information(evidence.get("notes")):
            problems.append(f"signature.notes contains {label}")
    return problems


def validate_audit_evidence(records: object, adjudication: dict,
                            registry: dict) -> list[str]:
    """One re-mark record per sampled item; any disagreement blocks certification."""
    problems: list[str] = []
    if not isinstance(records, list):
        return ["audit evidence must be a list"]
    registry_by_id = {str(item.get("id")): item for item in registry_items(registry)}
    sample = [str(item) for item in adjudication.get("audit_sample") or []]
    seen: set[str] = set()
    for index, record in enumerate(records):
        where = f"audit[{index}]"
        if not isinstance(record, dict):
            problems.append(f"{where}: audit record is not an object")
            continue
        _reject_unknown_keys(record, _AUDIT_KEYS, where, problems)
        item_id = str(record.get("item", "")).strip()
        if item_id in seen:
            problems.append(f"{where}: duplicate audit record for {item_id!r}")
        seen.add(item_id)
        item = registry_by_id.get(item_id)
        if item is None:
            problems.append(f"{where}: unknown item {item_id!r}")
            continue
        maximum = int(item.get("max_marks") or 0)
        for field in ("recorded_marks", "audit_marks"):
            value = record.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
                problems.append(f"{where}.{field}: must be an integer between 0 and {maximum}")
        if not _is_bool(record.get("agrees")):
            problems.append(f"{where}.agrees: must be a boolean")
        elif record.get("agrees") != (record.get("recorded_marks") == record.get("audit_marks")):
            problems.append(f"{where}: agrees disagrees with the recorded totals")
        if record.get("agrees") is False:
            problems.append(f"{where}: audit re-mark disagrees for {item_id}; the sheet "
                            "must be fully re-checked before certification")
        if record.get("note"):
            for label in find_identifying_information(record.get("note")):
                problems.append(f"{where}.note contains {label}")
    for item_id in sorted(set(sample) - seen):
        problems.append(f"audit: missing re-mark evidence for sampled item {item_id!r}")
    for item_id in sorted(seen - set(sample)):
        problems.append(f"audit: record for {item_id!r} is not in the audit sample")
    return problems


# --------------------------------------------------------------------- privacy scan
_PII_PATTERNS = (
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("a phone number", re.compile(r"(?<![0-9A-Fa-f])(?:\+?\d[\d ()-]{7,}\d)(?![0-9A-Fa-f])")),
    ("a candidate or student identifier",
     re.compile(r"\b(?:candidate|student|pupil)\b[^.\n]{0,24}"
                r"\b(?:name|number|no|id)\b", re.IGNORECASE)),
    ("a named person", re.compile(r"\b(?:name|surname)\s*[:=]", re.IGNORECASE)),
    ("a school identifier", re.compile(r"\bschool\s*[:=]", re.IGNORECASE)),
)


def find_identifying_information(text: object) -> list[str]:
    """Return the kinds of identifying information a human-written string contains."""
    value = str(text or "").strip()
    if not value or re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return []
    return [label for label, pattern in _PII_PATTERNS if pattern.search(value)]


def validate_custodian_attestation(evidence: object, *,
                                   paper_id: str | None = None) -> list[str]:
    """Validate the custodian's origin, anonymisation and external-evidence claims."""
    problems: list[str] = []
    if not isinstance(evidence, dict):
        return ["custodian attestation is not an object"]
    _reject_unknown_keys(evidence, _CUSTODIAN_KEYS, "custodian", problems)
    if evidence.get("role") != "data_custodian":
        problems.append("custodian role must be data_custodian")
    if evidence.get("kind") != "human_custodian":
        problems.append("custodian kind must be human_custodian")
    if not MARKER_ID_PATTERN.match(str(evidence.get("custodian_id", "")).strip()):
        problems.append("custodian_id must be a pseudonymous identifier")
    if paper_id and str(evidence.get("paper_id")) != str(paper_id):
        problems.append("custodian paper_id does not match the paper")
    if not _valid_date(evidence.get("signed_on")):
        problems.append("custodian signed_on must be an ISO date")
    declaration = _text(evidence.get("declaration"), "custodian.declaration", problems,
                        minimum=40, maximum=2000)
    if evidence.get("source_origin") not in CUSTODIAN_ORIGINS:
        problems.append("custodian source_origin must be one of "
                        f"{', '.join(sorted(CUSTODIAN_ORIGINS))}")
    method = _text(evidence.get("anonymisation_method"),
                   "custodian.anonymisation_method", problems, minimum=10,
                   maximum=1000)
    documentation = _text(evidence.get("source_documentation"),
                          "custodian.source_documentation", problems, minimum=10,
                          maximum=1000)
    for field in ("pixel_review", "metadata_review", "handwriting_review",
                  "paper_not_design_paper", "understands_limits"):
        if evidence.get(field) is not True:
            problems.append(f"custodian.{field} must be true")
    digest = evidence.get("form_sha256")
    if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
        problems.append("custodian form_sha256 must be a lowercase sha256 hex digest")
    elif set(digest) == {"0"}:
        problems.append("custodian form_sha256 must not be a placeholder")
    if evidence.get("form_location") not in EXTERNAL_FORM_LOCATIONS:
        problems.append("custodian form_location must name external custody")
    if evidence.get("identity_verified") is not False:
        problems.append("custodian identity_verified must be false: a hash proves "
                        "integrity, not identity")
    for label in find_identifying_information(declaration):
        problems.append(f"custodian.declaration contains {label}")
    for value, where in ((method, "custodian.anonymisation_method"),
                         (documentation, "custodian.source_documentation"),
                         (evidence.get("notes"), "custodian.notes")):
        for label in find_identifying_information(value):
            problems.append(f"{where} contains {label}")
    return problems


def validate_approval_evidence(approval: object, *, revision_id: str) -> list[str]:
    """Validate the explicit human approval that promotion requires."""
    problems: list[str] = []
    if not isinstance(approval, dict):
        return ["promotion requires explicit approval evidence"]
    _reject_unknown_keys(approval, _APPROVAL_KEYS, "approval", problems)
    if approval.get("role") != "holdout_owner":
        problems.append("approval role must be holdout_owner")
    if not MARKER_ID_PATTERN.match(str(approval.get("approver_id", "")).strip()):
        problems.append("approver_id must be a pseudonymous identifier")
    if not _valid_date(approval.get("approved_on")):
        problems.append("approval approved_on must be an ISO date")
    declaration = _text(approval.get("declaration"), "approval.declaration", problems,
                        minimum=40, maximum=2000)
    if str(approval.get("revision_id")) != str(revision_id):
        problems.append("approval revision_id does not match the candidate revision")
    digest = approval.get("evidence_sha256")
    if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
        problems.append("approval evidence_sha256 must be a lowercase sha256 digest")
    elif set(digest) == {"0"}:
        problems.append("approval evidence_sha256 must not be a placeholder")
    if approval.get("evidence_location") not in EXTERNAL_FORM_LOCATIONS:
        problems.append("approval evidence_location must name external custody")
    if approval.get("identity_verified") is not False:
        problems.append("approval identity_verified must be false")
    for label in find_identifying_information(declaration):
        problems.append(f"approval.declaration contains {label}")
    return problems


def scan_payload_for_pii(payload: object, path: str = "") -> list[str]:
    """Walk a JSON-like payload and report identifying information by field path."""
    findings: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            findings.extend(scan_payload_for_pii(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            findings.extend(scan_payload_for_pii(value, f"{path}[{index}]"))
    elif isinstance(payload, str):
        for label in find_identifying_information(payload):
            findings.append(f"{path or '<root>'}: contains {label}")
    return findings

"""Schema tests: exact records, extensible codes, allocation checks."""

from __future__ import annotations

from copy import deepcopy

import pytest

from benchmark.holdout import schemas


# ------------------------------------------------------------------ item registry
def test_valid_registry_passes(registry):
    assert schemas.validate_items_registry(registry) == []


def test_twenty_four_item_paper_is_rejected(registry_factory):
    problems = schemas.validate_items_registry(registry_factory(24))
    assert any("at least 25 items" in problem and "found 24" in problem
               for problem in problems)


def test_registry_rejects_duplicate_item_ids(registry):
    broken = deepcopy(registry)
    broken["items"][1]["id"] = broken["items"][0]["id"]
    problems = schemas.validate_items_registry(broken)
    assert any("duplicate item id 'q1'" in problem for problem in problems)


def test_registry_rejects_non_contiguous_order(registry):
    broken = deepcopy(registry)
    broken["items"][0]["order"] = 99
    problems = schemas.validate_items_registry(broken)
    assert any("contiguous 1..25" in problem for problem in problems)


def test_registry_rejects_criteria_max_marks_mismatch(registry):
    broken = deepcopy(registry)
    broken["items"][0]["criteria"].pop()
    problems = schemas.validate_items_registry(broken)
    assert any("does not match max_marks 2" in problem for problem in problems)


def test_registry_rejects_awards(registry):
    broken = deepcopy(registry)
    broken["items"][0]["criteria"][0]["awarded"] = True
    problems = schemas.validate_items_registry(broken)
    assert any("must not contain awards" in problem for problem in problems)


def test_registry_rejects_unknown_keys(registry):
    broken = deepcopy(registry)
    broken["unexpected"] = 1
    problems = schemas.validate_items_registry(broken)
    assert any("unexpected key 'unexpected'" in problem for problem in problems)


def test_registry_rejects_invalid_code_and_empty_text(registry):
    broken = deepcopy(registry)
    broken["items"][0]["criteria"][0]["code"] = "m1"
    broken["items"][0]["criteria"][1]["text"] = ""
    problems = schemas.validate_items_registry(broken)
    assert any("invalid criterion code 'm1'" in problem for problem in problems)
    assert any("shorter than 1" in problem for problem in problems)


def test_registry_rejects_reserved_paper_id(registry):
    broken = deepcopy(registry)
    broken["paper_id"] = "paper-01"
    problems = schemas.validate_items_registry(broken)
    assert any("reserved for the design paper" in problem for problem in problems)


def test_extensible_codes_are_accepted_and_flagged(registry_factory):
    repeated = registry_factory(25, codes=("M1", "M1", "A1"))
    assert schemas.validate_items_registry(repeated) == []
    compatibility = schemas.scoring_compatibility(repeated)
    assert compatibility["scoring_ready"] is True

    unknown = registry_factory(25, codes=("C1", "A1"))
    assert schemas.validate_items_registry(unknown) == []
    compatibility = schemas.scoring_compatibility(unknown)
    assert compatibility["scoring_ready"] is False
    assert compatibility["unknown_codes"] == ["C1"]

    deprecated = registry_factory(25, codes=("M1dep", "A1"))
    assert schemas.validate_items_registry(deprecated) == []
    assert schemas.scoring_compatibility(deprecated)["scoring_ready"] is True


# -------------------------------------------------------------------- marker sheet
def test_valid_marker_sheet_passes(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    assert schemas.validate_marker_sheet(sheet, registry) == []


def test_marker_sheet_requires_every_item(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["items"].pop()
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("missing item 'q25'" in problem for problem in problems)


def test_marker_sheet_rejects_unknown_item(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["items"].append({"id": "q99", "criteria": [
        {"code": "M1", "awarded": True}, {"code": "A1", "awarded": True}]})
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("unknown item 'q99'" in problem for problem in problems)


def test_marker_sheet_rejects_criterion_count(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["items"][0]["criteria"].pop()
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("expected 2 criteria, found 1" in problem for problem in problems)


def test_marker_sheet_rejects_unknown_code(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["items"][0]["criteria"][0]["code"] = "Z9"
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("unknown or duplicated criterion 'Z9'" in problem for problem in problems)


def test_marker_sheet_rejects_reordered_criteria(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    criteria = sheet["items"][0]["criteria"]
    criteria[0]["code"], criteria[1]["code"] = criteria[1]["code"], criteria[0]["code"]
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("criterion 1 is 'A1', expected 'M1'" in problem for problem in problems)


def test_marker_sheet_rejects_non_boolean_award(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["items"][0]["criteria"][0]["awarded"] = 1
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("awarded must be a boolean" in problem for problem in problems)


def test_marker_sheet_rejects_ai_marker(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["kind"] = "ai_marker"
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("human_teacher" in problem for problem in problems)


def test_marker_sheet_rejects_wrong_role(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_b", "MARKER_B_01")
    problems = schemas.validate_marker_sheet(sheet, registry, expected_role="marker_a")
    assert any("does not match expected 'marker_a'" in problem for problem in problems)


def test_marker_sheet_rejects_bad_date_and_missing_declaration(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["signed_on"] = "12/11/2026"
    sheet["declaration"] = ""
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("ISO date" in problem for problem in problems)
    assert any("shorter than 10" in problem for problem in problems)


def test_marker_sheet_rejects_unexpected_key(registry, sheet_factory):
    sheet = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet["extra"] = 1
    problems = schemas.validate_marker_sheet(sheet, registry)
    assert any("unexpected key 'extra'" in problem for problem in problems)


# --------------------------------------------------------------------- adjudication
def test_valid_adjudication_passes(registry, adjudication_factory):
    record = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "a"}])
    assert schemas.validate_adjudication(record, registry) == []


def test_adjudication_rejects_ambiguous_short_code(registry_factory, adjudication_factory):
    registry = registry_factory(25, codes=("M1", "M1", "A1"))
    record = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1", "resolution": "a"}])
    assert any("ambiguous" in problem
               for problem in schemas.validate_adjudication(record, registry))


def test_adjudication_rejects_duplicate_pair(registry, adjudication_factory):
    record = adjudication_factory(registry, [
        {"item": "q1", "criterion": "M1#0", "resolution": "a"},
        {"item": "q1", "criterion": "M1#0", "resolution": "b"},
    ])
    assert any("duplicate record for q1/M1#0" in problem
               for problem in schemas.validate_adjudication(record, registry))


def test_adjudication_rejects_unknown_item(registry, adjudication_factory):
    record = adjudication_factory(
        registry, [{"item": "q99", "criterion": "M1#0", "resolution": "a"}])
    assert any("unknown item 'q99'" in problem
               for problem in schemas.validate_adjudication(record, registry))


def test_adjudication_rejects_unknown_resolution(registry, adjudication_factory):
    record = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "coin toss"}])
    assert any("resolution 'coin toss' is not allowed" in problem
               for problem in schemas.validate_adjudication(record, registry))


def test_adjudication_requires_rationale(registry, adjudication_factory):
    record = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "a",
                    "rationale": "ok"}])
    assert any("rationale" in problem
               for problem in schemas.validate_adjudication(record, registry))


def test_adjudication_rejects_wrong_resolver(registry, adjudication_factory):
    record = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "a",
                    "resolved_by": "MARKER_A_01"}])
    assert any("resolved_by must be the adjudicator" in problem
               for problem in schemas.validate_adjudication(record, registry))


def test_adjudication_exclusion_marks_must_match_registry(registry, adjudication_factory):
    record = adjudication_factory(registry, exclusions=[{
        "item": "q3", "reason": "excluded_source_mismatch", "marks": 1,
        "evidence": "the page prints a different question number"}])
    problems = schemas.validate_adjudication(record, registry)
    assert any("do not match the printed maximum 2" in problem for problem in problems)


def test_adjudication_audit_sample_must_cover_ten_percent(registry, adjudication_factory):
    record = adjudication_factory(registry, audit_sample=["q1"])
    problems = schemas.validate_adjudication(record, registry)
    assert any("at least 2 items" in problem for problem in problems)


def test_adjudication_third_marks_must_match_registry(registry_factory,
                                                      adjudication_factory):
    registry = registry_factory(25, codes=("M1", "M1", "A1"))
    record = adjudication_factory(registry, third_marks=[{
        "item": "q1", "criteria": [{"code": "M1", "awarded": True}]}])
    problems = schemas.validate_adjudication(record, registry)
    assert any("expected 3 criteria, found 1" in problem for problem in problems)


def test_adjudication_third_marks_must_be_referenced(registry, adjudication_factory):
    record = adjudication_factory(registry, third_marks=[{
        "item": "q2", "criteria": [{"code": "M1", "awarded": True},
                                   {"code": "A1", "awarded": True}]}])
    problems = schemas.validate_adjudication(record, registry)
    assert any("not referenced by any 'third' resolution" in problem
               for problem in problems)


# -------------------------------------------------------------------- certification
def test_certification_record_passes(registry, certification_factory):
    assert schemas.validate_certification_record(
        certification_factory(registry), registry) == []


def test_certification_rejects_pending(registry, certification_factory):
    certification = certification_factory(registry)
    certification["pending"] = ["q7"]
    problems = schemas.validate_certification_record(certification, registry)
    assert any("pending" in problem for problem in problems)


def test_certification_rejects_low_kappa(registry, certification_factory):
    certification = certification_factory(registry)
    certification["agreement"]["criterion_kappa"] = 0.4
    problems = schemas.validate_certification_record(certification, registry)
    assert any("kappa below 0.6" in problem for problem in problems)


def test_certification_rejects_missing_marker(registry, certification_factory):
    certification = certification_factory(registry)
    certification["markers"].pop()
    problems = schemas.validate_certification_record(certification, registry)
    assert any("fewer than two independent markers" in problem for problem in problems)


def test_certification_rejects_unknown_key(registry, certification_factory):
    certification = certification_factory(registry)
    certification["unexpected"] = True
    problems = schemas.validate_certification_record(certification, registry)
    assert any("unexpected key 'unexpected'" in problem for problem in problems)


def test_certification_coverage_must_match_registry(registry, certification_factory):
    certification = certification_factory(registry)
    certification["coverage"]["items_total"] = 24
    problems = schemas.validate_certification_record(certification, registry)
    assert any("does not match the item registry" in problem for problem in problems)


# ------------------------------------------------------------------------ reference
def test_reference_record_passes(registry, reference_factory):
    assert schemas.validate_reference_record(reference_factory(registry)) == []


def test_reference_edited_totals_rejected(registry, reference_factory):
    reference = reference_factory(registry)
    reference["totals"]["marks_available_scored"] += 1
    problems = schemas.validate_reference_record(reference)
    assert any("totals disagree" in problem for problem in problems)


def test_reference_requires_verification_status(registry, reference_factory):
    reference = reference_factory(registry)
    reference.pop("verification")
    problems = schemas.validate_reference_record(reference)
    assert any("verification.status" in problem for problem in problems)


def test_reference_item_requires_evidence(registry, reference_factory):
    reference = reference_factory(registry)
    reference["items"][0]["evidence"] = ""
    problems = schemas.validate_reference_record(reference)
    assert any("evidence" in problem for problem in problems)


def test_reference_rejects_unknown_item_key(registry, reference_factory):
    reference = reference_factory(registry)
    reference["items"][0]["awarded_everything"] = True
    problems = schemas.validate_reference_record(reference)
    assert any("unexpected key 'awarded_everything'" in problem for problem in problems)

"""Reference derivation tests: determinism, provenance, exclusions, adversarial inputs."""

from __future__ import annotations

import json

import pytest

from benchmark.holdout import reference, schemas


def _derive(registry, sheet_a, sheet_b, adjudication, title="Synthetic holdout"):
    return reference.derive_reference(
        registry=registry, sheet_a=sheet_a, sheet_b=sheet_b,
        adjudication=adjudication, title=title)


def test_derives_evaluator_compatible_reference(registry, sheet_factory,
                                                adjudication_factory):
    sheet_a = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01")
    result = _derive(registry, sheet_a, sheet_b, adjudication_factory(registry, []))

    assert result["verification"]["status"] == reference.REFERENCE_STATUS
    assert result["totals"] == {
        "items_total": 25, "items_scored": 25, "items_excluded": 0,
        "marks_available_scored": 50, "candidate_marks_awarded": 50,
        "candidate_percentage": 100.0, "printed_marks_all_items": 50,
        "excluded_marks": 0,
    }
    assert all(len(item["criteria"]) == item["max_marks"]
               for item in result["items"])
    assert all(item["expected_mark"] == item["max_marks"] for item in result["items"])
    assert all(criterion["award_source"] == "agreement"
               for item in result["items"] for criterion in item["criteria"])
    assert "evidence" in result["items"][0]
    assert schemas.validate_reference_record(result) == []


def test_identical_inputs_produce_identical_bytes(registry, sheet_factory,
                                                  adjudication_factory):
    sheet_a = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01",
                            flips={("q1", "M1#0")})
    adjudication = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "a"}])

    first = _derive(registry, sheet_a, sheet_b, adjudication)
    second = _derive(registry, json.loads(json.dumps(sheet_a)),
                     json.loads(json.dumps(sheet_b)), json.loads(json.dumps(adjudication)))

    assert reference.reference_bytes(first) == reference.reference_bytes(second)
    assert reference.reference_sha256(first) == reference.reference_sha256(second)


def test_missing_marker_award_is_rejected(registry, sheet_factory,
                                          adjudication_factory):
    sheet_a = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet_a["items"][0]["criteria"].pop()
    with pytest.raises(reference.ReferenceError, match="expected 2 criteria, found 1"):
        _derive(registry, sheet_a,
                sheet_factory(registry, "marker_b", "MARKER_B_01"),
                adjudication_factory(registry, []))


def test_duplicate_criterion_award_is_rejected(registry, sheet_factory,
                                               adjudication_factory):
    sheet_a = sheet_factory(registry, "marker_a", "MARKER_A_01")
    sheet_a["items"][0]["criteria"].append({"code": "M1", "awarded": True})
    with pytest.raises(reference.ReferenceError, match="expected 2 criteria, found 3"):
        _derive(registry, sheet_a,
                sheet_factory(registry, "marker_b", "MARKER_B_01"),
                adjudication_factory(registry, []))


def test_unresolved_disagreement_is_rejected(registry, sheet_factory,
                                             adjudication_factory):
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01",
                            flips={("q4", "A1#0")})
    with pytest.raises(reference.ReferenceError,
                       match="missing adjudication for q4/A1#0"):
        _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                sheet_b, adjudication_factory(registry, []))


def test_third_resolution_without_marks_is_rejected(registry, sheet_factory,
                                                    adjudication_factory):
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01",
                            flips={("q2", "A1#0")})
    adjudication = adjudication_factory(
        registry, [{"item": "q2", "criterion": "A1#0", "resolution": "third"}])
    with pytest.raises(reference.ReferenceError,
                       match="requires third-marker marks"):
        _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                sheet_b, adjudication)


def test_invalid_third_marker_award_is_rejected(registry, sheet_factory,
                                                adjudication_factory):
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01",
                            flips={("q2", "A1#0")})
    adjudication = adjudication_factory(
        registry,
        [{"item": "q2", "criterion": "A1#0", "resolution": "third"}],
        third_marks=[{"item": "q2", "criteria": [
            {"code": "M1", "awarded": True}, {"code": "A1", "awarded": "yes"}]}])
    with pytest.raises(reference.ReferenceError, match="boolean"):
        _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                sheet_b, adjudication)


def test_award_exceeding_maximum_is_rejected(registry, reference_factory):
    damaged = reference_factory(registry)
    damaged["items"][0]["max_marks"] = 1
    problems = schemas.validate_reference_record(damaged)
    assert any("exceeds max_marks" in problem for problem in problems)


def test_incorrect_exclusion_is_rejected(registry, sheet_factory,
                                         adjudication_factory):
    adjudication = adjudication_factory(
        registry, exclusions=[{"item": "q3", "reason": "source_mismatch",
                               "marks": 1,
                               "evidence": "the printed question number differs"}])
    with pytest.raises(reference.ReferenceError,
                       match="do not match the printed maximum"):
        _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                sheet_factory(registry, "marker_b", "MARKER_B_01"), adjudication)


def test_unknown_exclusion_reason_is_rejected(registry, sheet_factory,
                                              adjudication_factory):
    adjudication = adjudication_factory(
        registry, exclusions=[{"item": "q3", "reason": "because_i_said_so",
                               "marks": 2,
                               "evidence": "no printed question on the page"}])
    with pytest.raises(reference.ReferenceError, match="unknown exclusion reason"):
        _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                sheet_factory(registry, "marker_b", "MARKER_B_01"), adjudication)


def test_incorrect_reference_totals_are_rejected(registry, reference_factory):
    damaged = reference_factory(registry)
    damaged["totals"]["candidate_marks_awarded"] -= 1
    damaged["totals"]["marks_available_scored"] += 1
    problems = schemas.validate_reference_record(damaged)
    assert any("totals disagree" in problem for problem in problems)


def test_exclusion_leaves_the_denominator(registry, sheet_factory,
                                          adjudication_factory):
    adjudication = adjudication_factory(
        registry, exclusions=[{"item": "q3", "reason": "source_mismatch",
                               "marks": 2,
                               "evidence": "the printed question number differs"}])
    result = _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                     sheet_factory(registry, "marker_b", "MARKER_B_01"), adjudication)
    assert result["totals"]["items_total"] == 25
    assert result["totals"]["items_scored"] == 24
    assert result["totals"]["items_excluded"] == 1
    assert result["totals"]["marks_available_scored"] == 48
    assert result["totals"]["excluded_marks"] == 2
    assert result["totals"]["printed_marks_all_items"] == 50
    assert "q3" not in {item["id"] for item in result["items"]}
    assert result["exclusions"][0]["status"] == "excluded_source_mismatch"


def test_adjudicated_award_keeps_provenance(registry, sheet_factory,
                                            adjudication_factory):
    sheet_b = sheet_factory(registry, "marker_b", "MARKER_B_01",
                            flips={("q1", "M1#0")})
    adjudication = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "a"}])
    result = _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                     sheet_b, adjudication)
    item = next(entry for entry in result["items"] if entry["id"] == "q1")
    assert item["criteria"][0]["awarded"] is True
    assert item["criteria"][0]["award_source"] == "marker_a"
    assert item["criteria"][1]["award_source"] == "agreement"


def test_student_identifiers_are_rejected(registry, sheet_factory,
                                          adjudication_factory):
    adjudication = adjudication_factory(
        registry, exclusions=[{"item": "q3", "reason": "source_mismatch", "marks": 2,
                               "evidence": "Candidate number: 123456 on the page"}])
    with pytest.raises(reference.ReferenceError,
                       match="candidate or student identifier"):
        _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                sheet_factory(registry, "marker_b", "MARKER_B_01"), adjudication)


def test_reference_contains_no_free_text_identity(registry, sheet_factory,
                                                  adjudication_factory):
    result = _derive(registry, sheet_factory(registry, "marker_a", "MARKER_A_01"),
                     sheet_factory(registry, "marker_b", "MARKER_B_01"),
                     adjudication_factory(registry, []))
    payload = json.dumps(result)
    for forbidden in ("@", "Candidate number", "Student name", "school:"):
        assert forbidden not in payload

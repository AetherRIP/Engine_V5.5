"""Agreement tests: kappa, disagreement detection, adjudication coverage."""

from __future__ import annotations

import pytest

from benchmark.holdout import agreement, sheets


def _pairs(counts):
    pairs = []
    for (a, b), count in counts.items():
        pairs.extend([(a, b)] * count)
    return pairs


def test_kappa_known_example():
    pairs = _pairs({(True, True): 20, (True, False): 5,
                    (False, True): 10, (False, False): 15})
    assert agreement.cohen_kappa(pairs) == pytest.approx(0.4)


def test_kappa_negative_example():
    pairs = _pairs({(True, True): 10, (True, False): 15,
                    (False, True): 15, (False, False): 10})
    assert agreement.cohen_kappa(pairs) == pytest.approx(-0.2)


def test_kappa_perfect_and_degenerate():
    assert agreement.cohen_kappa([(True, True)] * 5) == pytest.approx(1.0)
    assert agreement.cohen_kappa([(False, False)] * 5) == pytest.approx(1.0)


def test_kappa_empty_raises():
    with pytest.raises(agreement.AgreementError):
        agreement.cohen_kappa([])


def test_summary_counts(registry, sheet_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0"), ("q2", "A1#0")})
    records = sheets.pair_items(first, second, registry)
    summary = agreement.agreement_summary(records)
    assert summary["criterion_pairs"] == 50
    assert summary["disagreements"] == 2
    assert summary["item_exact_agreement"] == pytest.approx(23 / 25)
    assert summary["mean_absolute_item_difference"] == pytest.approx(0.08)
    # Almost every criterion is awarded here, so kappa is dominated by the skewed
    # marginals; the numeric examples above cover the statistic itself.
    pairs = [(criterion["marker_a"], criterion["marker_b"])
             for record in records for criterion in record["criteria"]]
    assert summary["criterion_kappa"] == pytest.approx(
        agreement.cohen_kappa(pairs), abs=1e-4)


def test_disagreements_use_criterion_occurrence(registry_factory, sheet_factory):
    registry = registry_factory(25, codes=("M1", "M1", "A1"))
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#1")})
    disagreements = agreement.criterion_disagreements(
        sheets.pair_items(first, second, registry))
    assert [(entry["item"], entry["criterion"]) for entry in disagreements] == [
        ("q1", "M1#1")]


def test_coverage_rejects_omitted_disagreement(registry, sheet_factory,
                                               adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(registry, [])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("missing adjudication for q1/M1#0" in problem for problem in problems)


def test_coverage_rejects_unrelated_record(registry, sheet_factory,
                                           adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01")
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "a"}])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("no disagreement for q1/M1#0" in problem for problem in problems)


def test_coverage_rejects_third_without_marks(registry, sheet_factory,
                                              adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "third"}])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("requires third-marker marks" in problem for problem in problems)


def test_coverage_accepts_third_with_marks(registry, sheet_factory,
                                           adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry,
        [{"item": "q1", "criterion": "M1#0", "resolution": "third"}],
        third_marks=[{"item": "q1", "criteria": [
            {"code": "M1", "awarded": True}, {"code": "A1", "awarded": True}]}])
    assert agreement.validate_adjudication_coverage(adjudication, records,
                                                    registry) == []


def test_coverage_rejects_excluded_without_record(registry, sheet_factory,
                                                  adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry, [{"item": "q1", "criterion": "M1#0", "resolution": "excluded"}])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("requires an exclusion record" in problem for problem in problems)


def test_coverage_rejects_award_on_excluded_item(registry, sheet_factory,
                                                 adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry,
        [{"item": "q1", "criterion": "M1#0", "resolution": "a"}],
        exclusions=[{"item": "q1", "reason": "excluded_source_mismatch", "marks": 2,
                     "evidence": "the printed question number does not match"}])
    problems = agreement.validate_adjudication_coverage(adjudication, records, registry)
    assert any("that is not 'excluded'" in problem for problem in problems)


def test_resolve_awards_uses_third_marker(registry, sheet_factory,
                                          adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry,
        [{"item": "q1", "criterion": "M1#0", "resolution": "third"}],
        third_marks=[{"item": "q1", "criteria": [
            {"code": "M1", "awarded": True}, {"code": "A1", "awarded": True}]}])
    awards = agreement.resolve_awards(records, adjudication, registry)
    criterion = awards["q1"]["criteria"][0]
    assert criterion["awarded"] is True
    assert criterion["source"] == "third"


def test_resolve_awards_defaults_to_agreement(registry, sheet_factory,
                                              adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01")
    records = sheets.pair_items(first, second, registry)
    awards = agreement.resolve_awards(
        records, adjudication_factory(registry, []), registry)
    assert {criterion["source"] for criterion in awards["q1"]["criteria"]} == {
        "agreement"}


def test_resolve_awards_never_silently_defaults(registry, sheet_factory,
                                                adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01",
                           flips={("q1", "M1#0")})
    records = sheets.pair_items(first, second, registry)
    with pytest.raises(agreement.AgreementError, match="unresolved disagreement"):
        agreement.resolve_awards(records, adjudication_factory(registry, []), registry)


def test_resolve_awards_excludes_item(registry, sheet_factory, adjudication_factory):
    first = sheet_factory(registry, "marker_a", "MARKER_A_01")
    second = sheet_factory(registry, "marker_b", "MARKER_B_01")
    records = sheets.pair_items(first, second, registry)
    adjudication = adjudication_factory(
        registry, exclusions=[{"item": "q3", "reason": "not_printed",
                               "marks": 2,
                               "evidence": "question is absent from the printed page"}])
    awards = agreement.resolve_awards(records, adjudication, registry)
    assert awards["q3"] == {"status": "excluded_not_printed", "criteria": []}


def test_audit_sample_status(registry, adjudication_factory):
    record = adjudication_factory(registry, audit_sample=["q1", "q2"])
    status = agreement.audit_sample_status(record, registry)
    assert status == {"items": 25, "required": 2, "provided": 2, "valid": True}
    short = agreement.audit_sample_status(
        adjudication_factory(registry, audit_sample=["q1"]), registry)
    assert short["valid"] is False

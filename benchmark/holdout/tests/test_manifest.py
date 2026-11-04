"""Offline tests for the holdout manifest and certification validator.

These tests are the guard against inventing certification: a paper only validates when two
independent human teacher signatures, an adjudicator, a resolved disagreement list and a
consistent reference are all present.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from benchmark.holdout import manifest as m


def _hash(text: str = "x") -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _reference(items: int = 25) -> dict:
    rows = []
    for index in range(items):
        rows.append({
            "id": f"q{index + 1}",
            "max_marks": 2,
            "status": "scored",
            "criteria": [
                {"code": "M1", "text": "method", "awarded": True},
                {"code": "A1", "text": "answer", "awarded": index % 3 == 0},
            ],
            "expected_mark": 1 + (1 if index % 3 == 0 else 0),
            "evidence": "visible working",
        })
    return {"items": rows,
            "totals": {"marks_available_scored": 2 * items}}


def _paper(tmp_path, items: int = 25) -> dict:
    reference = _reference(items)
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    return {
        "paper_id": "holdout-01",
        "status": "certified",
        "topic": "algebraic manipulation",
        "difficulty": "higher",
        "marks_available": 2 * items,
        "pages": {
            "student": [{"path": "student_p01.png", "sha256": _hash("student")}],
            "scheme": [{"path": "scheme_p01.png", "sha256": _hash("scheme")}],
        },
        "reference": {"path": "reference.json", "sha256": m.sha256_file(reference_path)},
        "certification": {
            "path": "certification.json",
            "markers": [
                {"id": "MARKER_A_01", "kind": "human_teacher", "role": "marker_a",
                 "declaration": "marked independently", "signed_on": "2026-11-03",
                 "items_marked": items},
                {"id": "MARKER_B_01", "kind": "human_teacher", "role": "marker_b",
                 "declaration": "marked independently", "signed_on": "2026-11-03",
                 "items_marked": items},
            ],
            "adjudicator": {"id": "ADJ_01", "kind": "human_teacher",
                            "signed_on": "2026-11-03"},
            "coverage": {"items_total": items, "items_marked_by_both": items,
                         "criteria_total": 2 * items},
            "agreement": {"criterion_kappa": 0.91, "item_exact_agreement": 0.96,
                          "mean_absolute_item_difference": 0.04,
                          "audit_sample": max(1, int(0.1 * items))},
            "disagreements": [
                {"item": "q2", "criterion": "A1", "marker_a": True, "marker_b": False,
                 "resolution": "b", "resolved_by": "ADJ_01",
                 "rationale": "answer differs from the printed answer"},
            ],
            "exclusions": [],
            "pending": [],
        },
    }


def _manifest(paper: dict | None = None, status: str = "underpowered_descriptive") -> dict:
    payload = {
        "status": status,
        "papers": [paper] if paper else [],
        "preregistered_metrics": ["criterion_f1"],
        "acceptance_criteria": {"primary": "delta <= -1.0"},
        "statistical_plan": {"unit": "paper"},
        "certification_requirements": {"markers": 2},
        "frozen_config": {"files": {}},
    }
    return payload


def test_empty_manifest_is_valid_only_when_blocked():
    assert m.validate_manifest(_manifest(status="blocked_no_certified_papers"))["valid"]
    result = m.validate_manifest(_manifest(status="ready"))
    assert not result["valid"]
    assert any("blocked" in problem for problem in result["problems"])


def test_complete_certified_paper_validates(tmp_path):
    paper = _paper(tmp_path)
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert problems == []
    result = m.validate_manifest(_manifest(paper), base_dir=tmp_path)
    assert result["valid"], result["problems"]
    assert result["certified_papers"] == 1
    assert result["decision_permitted"] is False


def test_single_marker_is_rejected(tmp_path):
    paper = _paper(tmp_path)
    paper["certification"]["markers"] = paper["certification"]["markers"][:1]
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("two independent markers" in problem for problem in problems)


def test_ai_marker_is_rejected(tmp_path):
    paper = _paper(tmp_path)
    paper["certification"]["markers"][0]["kind"] = "ai_model"
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("human teacher" in problem for problem in problems)


def test_adjudicator_cannot_be_a_marker(tmp_path):
    paper = _paper(tmp_path)
    paper["certification"]["adjudicator"]["id"] = "MARKER_A_01"
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("also a marker" in problem for problem in problems)


def test_pending_certification_is_rejected(tmp_path):
    paper = _paper(tmp_path)
    paper["certification"]["pending"] = ["q7"]
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("pending" in problem for problem in problems)


def test_unresolved_disagreement_is_rejected(tmp_path):
    paper = _paper(tmp_path)
    paper["certification"]["disagreements"][0]["resolution"] = "pending"
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("unresolved" in problem for problem in problems)


def test_reserved_paper_id_and_hash_collision_are_rejected(tmp_path):
    paper = _paper(tmp_path)
    paper["paper_id"] = "paper-01"
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("reserved" in problem for problem in problems)

    paper = _paper(tmp_path)
    reserved_page = "deadbeef" * 8
    paper["pages"]["student"][0]["sha256"] = reserved_page
    problems = m.validate_paper(paper, reserved_hashes={reserved_page}, base_dir=tmp_path)
    assert any("paper-01 page hash" in problem for problem in problems)


def test_low_kappa_is_rejected(tmp_path):
    paper = _paper(tmp_path)
    paper["certification"]["agreement"]["criterion_kappa"] = 0.41
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("kappa" in problem for problem in problems)


def test_inconsistent_reference_totals_are_rejected(tmp_path):
    paper = _paper(tmp_path)
    reference_path = tmp_path / "reference.json"
    data = json.loads(reference_path.read_text())
    data["items"][0]["expected_mark"] = 0  # disagrees with the criteria
    reference_path.write_text(json.dumps(data), encoding="utf-8")
    paper["reference"]["sha256"] = m.sha256_file(reference_path)
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("expected_mark disagrees" in problem for problem in problems)


def test_reference_hash_mismatch_is_rejected(tmp_path):
    paper = _paper(tmp_path)
    (tmp_path / "reference.json").write_text(json.dumps(_reference()), encoding="utf-8")
    paper["reference"]["sha256"] = _hash("something else")
    problems = m.validate_paper(paper, reserved_hashes=set(), base_dir=tmp_path)
    assert any("hash does not match" in problem for problem in problems)


def test_frozen_code_digest_mismatch_is_rejected(tmp_path):
    code_root = tmp_path / "code"
    code_root.mkdir()
    frozen = code_root / "signals.py"
    frozen.write_text("frozen version", encoding="utf-8")
    payload = _manifest(status="blocked_no_certified_papers")
    payload["frozen_config"]["files"] = {"signals.py": m.sha256_file(frozen)}
    assert m.validate_manifest(payload, code_root=code_root, check_code=True)["valid"]

    frozen.write_text("tampered", encoding="utf-8")
    result = m.validate_manifest(payload, code_root=code_root, check_code=True)
    assert not result["valid"]
    assert any("changed since pre-registration" in problem for problem in result["problems"])


def test_duplicate_papers_are_rejected(tmp_path):
    paper = _paper(tmp_path)
    payload = _manifest(paper)
    payload["papers"].append(copy.deepcopy(paper))
    result = m.validate_manifest(payload, base_dir=tmp_path)
    assert any("duplicate paper_id" in problem for problem in result["problems"])


def test_status_must_reflect_certified_count(tmp_path):
    paper = _paper(tmp_path)
    payload = _manifest(paper, status="blocked_no_certified_papers")
    result = m.validate_manifest(payload, base_dir=tmp_path)
    assert any("status" in problem for problem in result["problems"])


def test_repository_manifest_is_blocked_and_self_consistent():
    payload = m.load()
    result = m.validate_manifest(payload, check_code=True)
    assert result["valid"], result["problems"]
    assert result["certified_papers"] == 0
    assert result["status"] == "blocked_no_certified_papers"
    assert result["decision_permitted"] is False

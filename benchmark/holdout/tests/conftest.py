"""Synthetic fixtures for holdout intake tests.

Everything here is invented: 25-item papers, fictitious marker ids and made-up awards.
No student data, no scanned pages and no provider calls are involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.holdout import (agreement, certification, manifest, reference, sheets,
                               store)

ITEM_COUNT = 25


def build_registry(count: int = ITEM_COUNT, *, codes=("M1", "A1"),
                   paper_id: str = "holdout-01") -> dict:
    items = []
    for index in range(count):
        item_codes = list(codes)
        items.append({
            "id": f"q{index + 1}",
            "order": index + 1,
            "scheme_page": 1,
            "max_marks": len(item_codes),
            "prompt": f"Question {index + 1}",
            "criteria": [
                {"code": code, "text": f"printed criterion {code} {index + 1}"}
                for code in item_codes
            ],
        })
    return {"paper_id": paper_id, "items": items}


def build_sheet(registry: dict, role: str, marker_id: str, *, flips=()) -> dict:
    flipped = set(flips)
    items = []
    for item in registry["items"]:
        criteria = []
        counts: dict[str, int] = {}
        for criterion in item["criteria"]:
            code = criterion["code"]
            index = counts.get(code, 0)
            counts[code] = index + 1
            key = f"{code}#{index}"
            awarded = (item["id"], key) not in flipped and key not in flipped
            criteria.append({
                "code": code,
                "awarded": awarded,
                "note": "awarded" if awarded else "not awarded",
            })
        items.append({
            "id": item["id"],
            "criteria": criteria,
            "ambiguous": False,
            "illegible": False,
            "evidence": "visible working",
        })
    return {
        "paper_id": registry["paper_id"],
        "marker_id": marker_id,
        "role": role,
        "kind": "human_teacher",
        "signed_on": "2026-11-12",
        "declaration": "I marked every item independently from the anonymised pages.",
        "items": items,
    }


def build_adjudication(registry: dict, disagreements=(), *, exclusions=(),
                       third_marks=(), adjudicator: str = "ADJ_01",
                       audit_sample=None) -> dict:
    resolved = []
    for record in disagreements:
        entry = dict(record)
        entry.setdefault("rationale", "reviewed both markers' notes and the printed scheme")
        entry.setdefault("resolved_by", adjudicator)
        resolved.append(entry)
    if audit_sample is None:
        required = max(1, int(0.10 * len(registry["items"])))
        audit_sample = [item["id"] for item in registry["items"][:required]]
    return {
        "paper_id": registry["paper_id"],
        "adjudicator": adjudicator,
        "kind": "human_teacher",
        "signed_on": "2026-11-12",
        "audit_sample": audit_sample,
        "disagreements": resolved,
        "exclusions": list(exclusions),
        "third_marks": list(third_marks),
    }


def build_certification(registry: dict) -> dict:
    items = registry["items"]
    criteria = sum(int(item["max_marks"]) for item in items)
    return {
        "paper_id": registry["paper_id"],
        "reference_sha256": "a" * 64,
        "markers": [
            {"id": "MARKER_A_01", "kind": "human_teacher", "role": "marker_a",
             "declaration": "marked independently", "signed_on": "2026-11-12",
             "items_marked": len(items), "signature_scan_sha256": "b" * 64},
            {"id": "MARKER_B_01", "kind": "human_teacher", "role": "marker_b",
             "declaration": "marked independently", "signed_on": "2026-11-12",
             "items_marked": len(items), "signature_scan_sha256": "c" * 64},
        ],
        "adjudicator": {"id": "ADJ_01", "kind": "human_teacher",
                        "signed_on": "2026-11-12", "signature_scan_sha256": "d" * 64},
        "coverage": {"items_total": len(items), "items_marked_by_both": len(items),
                     "criteria_total": criteria},
        "agreement": {"criterion_kappa": 0.9, "item_exact_agreement": 0.98,
                      "mean_absolute_item_difference": 0.02,
                      "audit_sample": max(1, int(0.10 * len(items)))},
        "disagreements": [],
        "exclusions": [],
        "pending": [],
    }


def build_reference(registry: dict) -> dict:
    items = []
    for item in registry["items"]:
        items.append({
            "id": item["id"],
            "prompt": item.get("prompt", ""),
            "student_page": 1,
            "scheme_page": item["scheme_page"],
            "scheme_ref": "synthetic scheme line",
            "max_marks": item["max_marks"],
            "criteria": [dict(criterion, awarded=True) for criterion in item["criteria"]],
            "expected_mark": item["max_marks"],
            "status": "scored",
            "confidence": "high",
            "evidence": "synthetic adjudicated evidence",
        })
    total = sum(item["max_marks"] for item in items)
    awarded = sum(item["expected_mark"] for item in items)
    return {
        "paper_id": registry["paper_id"],
        "title": "Synthetic holdout",
        "verification": {"status": "teacher_certified",
                         "verified_by": ["MARKER_A_01", "MARKER_B_01"],
                         "verified_on": "2026-11-12"},
        "totals": {"items_total": len(items), "items_scored": len(items),
                   "items_excluded": 0, "marks_available_scored": total,
                   "candidate_marks_awarded": awarded,
                   "candidate_percentage": round(100 * awarded / total, 2)},
        "items": items,
        "exclusions": [],
    }


@pytest.fixture
def registry_factory():
    return build_registry


@pytest.fixture
def registry():
    return build_registry()


@pytest.fixture
def sheet_factory():
    return build_sheet


@pytest.fixture
def adjudication_factory():
    return build_adjudication


@pytest.fixture
def certification_factory():
    return build_certification


@pytest.fixture
def reference_factory():
    return build_reference


@pytest.fixture
def workspace(tmp_path):
    return store.ensure_workspace("holdout-01", papers_dir=tmp_path / "papers")


@pytest.fixture
def write_json(tmp_path):
    def _write(payload: dict, name: str = "sheet.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
    return _write


def build_audit(registry: dict, adjudication: dict, awards: dict) -> list[dict]:
    records = []
    for item_id in adjudication.get("audit_sample") or []:
        item = next((entry for entry in registry["items"] if entry["id"] == item_id),
                    None)
        if item is None:
            continue
        total = (sum(1 for criterion in awards[item_id]["criteria"]
                     if criterion["awarded"]) if item_id in awards else 0)
        records.append({"item": item_id, "recorded_marks": total,
                        "audit_marks": total, "agrees": True,
                        "note": "the re-mark matched the sheet"})
    return records


def prepare_scenario(root, registry: dict, sheet_a: dict, sheet_b: dict,
                     adjudication: dict, *, title: str = "Synthetic holdout") -> dict:
    """Write a complete paper workspace and return the certification arguments."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store.write_json_atomic(root / "items.json", registry)
    prepared_a, prepared_b = sheets.prepare_pair(sheet_a, sheet_b, registry)
    for role, raw, prepared in (("marker_a", sheet_a, prepared_a),
                                ("marker_b", sheet_b, prepared_b)):
        store.write_json_atomic(root / "markers" / f"{role}.raw.json", raw)
        store.write_json_atomic(root / "markers" / f"{role}.json", prepared)
    store.write_json_atomic(root / "adjudication.json", adjudication)
    reference_data = reference.derive_reference(
        registry=registry, sheet_a=sheet_a, sheet_b=sheet_b,
        adjudication=adjudication, title=title)
    reference.write_reference(root / "reference.json", reference_data)
    for role, payload in (("student", b"student-page"), ("scheme", b"scheme-page")):
        (root / "pages" / role).mkdir(parents=True, exist_ok=True)
        (root / "pages" / role / "p01.png").write_bytes(payload)
    awards = agreement.resolve_awards(
        sheets.pair_items(prepared_a, prepared_b, registry), adjudication, registry)
    audit = build_audit(registry, adjudication, awards)
    return {
        "root": root,
        "registry": registry,
        "sheet_a": sheet_a,
        "sheet_b": sheet_b,
        "adjudication": adjudication,
        "reference": reference_data,
        "audit": audit,
        "build_kwargs": {
            "registry_path": "items.json",
            "sheet_paths": {role: {"raw": f"markers/{role}.raw.json",
                                   "normalised": f"markers/{role}.json"}
                            for role in ("marker_a", "marker_b")},
            "adjudication_path": "adjudication.json",
            "reference_path": "reference.json",
            "page_paths": {"student": ["pages/student/p01.png"],
                           "scheme": ["pages/scheme/p01.png"]},
            "audit_evidence": audit,
            "frozen_config": manifest.load()["frozen_config"],
            "title": title,
        },
    }


@pytest.fixture
def scenario_factory(tmp_path):
    def _build(registry, sheet_a, sheet_b, adjudication, *, name="paper", title=None):
        return prepare_scenario(tmp_path / name, registry, sheet_a, sheet_b,
                                adjudication,
                                title=title or "Synthetic holdout")
    return _build


@pytest.fixture
def scenario(tmp_path, registry, sheet_factory, adjudication_factory):
    return prepare_scenario(
        tmp_path / "paper", registry,
        sheet_factory(registry, "marker_a", "MARKER_A_01"),
        sheet_factory(registry, "marker_b", "MARKER_B_01"),
        adjudication_factory(registry, []))


def build_custodian(paper_id: str, **overrides) -> dict:
    evidence = {
        "custodian_id": "CUSTODIAN_01",
        "paper_id": paper_id,
        "role": "data_custodian",
        "kind": "human_custodian",
        "signed_on": "2026-11-12",
        "declaration": ("I confirm this paper was independently sourced, anonymised "
                        "before entering the repository, and reviewed for identifying "
                        "information."),
        "source_origin": "independent_series",
        "anonymisation_method": "manual redaction followed by metadata stripping",
        "source_documentation": "custody log retained by the school",
        "pixel_review": True,
        "metadata_review": True,
        "handwriting_review": True,
        "paper_not_design_paper": True,
        "understands_limits": True,
        "form_sha256": store.sha256_bytes(b"signed-custodian-form"),
        "form_location": "school_custody",
        "identity_verified": False,
    }
    evidence.update(overrides)
    return evidence


def write_custodian(workspace, paper_id: str) -> dict:
    evidence = build_custodian(paper_id)
    store.write_json_atomic(Path(workspace) / "attestations" / "custodian.json",
                            evidence)
    return evidence


def certify_scenario(scenario: dict, signature_factory) -> dict:
    draft = certification.build_draft(scenario["root"], **scenario["build_kwargs"])
    for role in certification.REQUIRED_SIGNERS:
        draft = certification.apply_signature(draft, signature_factory(draft, role))
    store.write_json_atomic(Path(scenario["root"]) / "certification.json", draft)
    return draft


def build_approval(revision_id: str, **overrides) -> dict:
    approval = {
        "approver_id": "APPROVER_01",
        "role": "holdout_owner",
        "approved_on": "2026-11-13",
        "declaration": ("I approve promotion of this exact registered revision after "
                        "reviewing the certification and custodian evidence."),
        "revision_id": revision_id,
        "evidence_sha256": store.sha256_bytes(b"signed-approval-form"),
        "evidence_location": "school_custody",
        "identity_verified": False,
    }
    approval.update(overrides)
    return approval


@pytest.fixture
def custodian_factory():
    return build_custodian


@pytest.fixture
def approval_factory():
    return build_approval


@pytest.fixture
def certified_paper(signature_factory):
    def _build(workspace, registry, sheet_a, sheet_b, adjudication,
               *, title="Synthetic holdout"):
        scenario = prepare_scenario(workspace, registry, sheet_a, sheet_b, adjudication,
                                    title=title)
        certify_scenario(scenario, signature_factory)
        write_custodian(workspace, registry["paper_id"])
        return scenario
    return _build


@pytest.fixture
def signature_factory():
    def _build(draft: dict, role: str, **overrides) -> dict:
        ids = {marker["role"]: marker["id"] for marker in draft["markers"]}
        ids["adjudicator"] = draft["adjudicator"]["id"]
        evidence = {
            "signer_id": ids[role],
            "role": role,
            "kind": "human_teacher",
            "signed_on": "2026-11-12",
            "declaration": ("I confirm this marking was completed independently and "
                            "honestly from the anonymised pages."),
            "form_sha256": store.sha256_bytes(f"signed-form-{role}".encode()),
            "form_location": "school_custody",
            "identity_verified": False,
        }
        evidence.update(overrides)
        return evidence
    return _build

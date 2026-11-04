"""Holdout manifest and certification validator.

The point of this module is to make "certified" a checkable fact rather than a comment.  A
paper only counts as certified when two independent human teachers have signed, an
adjudicator has resolved every disagreement, every exclusion has a reason, and the page
hashes do not collide with the paper the hybrid was designed on.

Run as a check:

    python -m benchmark.holdout.manifest
    python -m benchmark.holdout.manifest --check-code

Exit status is 1 when any problem is found, so it can gate a holdout scoring run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent / "holdout_manifest.json"
HOLDOUT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = HOLDOUT_DIR.parent / "anonymized_samples"
RESERVED_PAPER_IDS = {"paper-01"}
ALLOWED_EXCLUSIONS = {
    "source_mismatch",
    "not_printed",
    "scheme_missing",
    "unresolved_disagreement",
}
ALLOWED_RESOLUTIONS = {"a", "b", "third", "excluded"}
PAPER_ID_PATTERN = re.compile(r"^holdout-\d{2,}$")
MIN_PAPERS_FOR_DECISION = 8
RECOMMENDED_PAPERS = 10
MIN_ITEMS_PER_PAPER = 25
MIN_KAPPA = 0.60


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path | None = None) -> dict:
    target = path or MANIFEST_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def reserved_page_hashes(samples_dir: Path | None = None) -> set[str]:
    """Every page hash of the paper the hybrid was designed on."""
    directory = samples_dir or SAMPLES_DIR
    if not directory.is_dir():
        return set()
    return {sha256_file(path) for path in sorted(directory.glob("*.png"))}


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def validate_reference_data(data: dict) -> list[str]:
    """Check a certified reference is internally consistent."""
    problems: list[str] = []
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return ["reference has no items"]
    ids = [str(item.get("id")) for item in items]
    if len(ids) != len(set(ids)):
        problems.append("reference has duplicate item ids")
    total_max = 0
    for item in items:
        item_id = item.get("id")
        status = str(item.get("status"))
        max_marks = item.get("max_marks")
        if not isinstance(max_marks, int) or max_marks < 0:
            problems.append(f"{item_id}: max_marks is not a non-negative integer")
            continue
        total_max += max_marks
        if status == "scored":
            criteria = [c for c in item.get("criteria") or [] if isinstance(c, dict)]
            if len(criteria) != max_marks:
                problems.append(f"{item_id}: {len(criteria)} criteria for {max_marks} marks")
            awarded = sum(1 for criterion in criteria if criterion.get("awarded") is True)
            if item.get("expected_mark") != awarded:
                problems.append(f"{item_id}: expected_mark disagrees with criteria")
            if awarded > max_marks:
                problems.append(f"{item_id}: award exceeds max_marks")
        elif status.startswith("excluded"):
            if not str(item.get("evidence", "")).strip():
                problems.append(f"{item_id}: exclusion has no evidence")
        else:
            problems.append(f"{item_id}: unknown status {status!r}")
    totals = data.get("totals") or {}
    if totals.get("marks_available_scored") not in (None, total_max):
        problems.append("reference totals disagree with item maximums")
    return problems


def _validate_certification(paper: dict) -> list[str]:
    problems: list[str] = []
    certification = paper.get("certification") or {}
    markers = [m for m in certification.get("markers") or [] if isinstance(m, dict)]
    if len(markers) < 2:
        problems.append("fewer than two independent markers")
    marker_ids = {m.get("id") for m in markers}
    if len(marker_ids) != len(markers):
        problems.append("marker ids are not distinct")
    roles = {m.get("role") for m in markers}
    if roles != {"marker_a", "marker_b"} and len(markers) >= 2:
        problems.append("markers must cover marker_a and marker_b")
    for marker in markers:
        label = marker.get("id")
        if marker.get("kind") != "human_teacher":
            problems.append(f"{label}: marker is not a human teacher")
        if not str(marker.get("declaration", "")).strip():
            problems.append(f"{label}: missing declaration")
        if not str(marker.get("signed_on", "")).strip():
            problems.append(f"{label}: missing signature date")

    adjudicator = certification.get("adjudicator") or {}
    if adjudicator.get("kind") != "human_teacher":
        problems.append("adjudicator is not a human teacher")
    if adjudicator.get("id") in marker_ids:
        problems.append("adjudicator is also a marker")

    coverage = certification.get("coverage") or {}
    items_total = coverage.get("items_total")
    if not isinstance(items_total, int) or items_total < MIN_ITEMS_PER_PAPER:
        problems.append(f"paper has fewer than {MIN_ITEMS_PER_PAPER} scoreable items")
    if coverage.get("items_marked_by_both") != items_total:
        problems.append("not every item was marked by both markers")

    agreement = certification.get("agreement") or {}
    kappa = agreement.get("criterion_kappa")
    if not isinstance(kappa, (int, float)) or kappa < MIN_KAPPA:
        problems.append(f"criterion kappa below {MIN_KAPPA}")
    sample = agreement.get("audit_sample")
    if not isinstance(sample, int) or (isinstance(items_total, int)
                                       and sample < max(1, int(0.1 * items_total))):
        problems.append("audit sample is smaller than 10% of items")

    if certification.get("pending"):
        problems.append("certification still has pending items")

    exclusions = {str(entry.get("item")): entry
                  for entry in certification.get("exclusions") or []
                  if isinstance(entry, dict)}
    for entry in exclusions.values():
        if entry.get("reason") not in ALLOWED_EXCLUSIONS:
            problems.append(f"exclusion {entry.get('item')} has an unknown reason")
        if not isinstance(entry.get("marks"), int):
            problems.append(f"exclusion {entry.get('item')} does not record its marks")

    for record in certification.get("disagreements") or []:
        if not isinstance(record, dict):
            problems.append("disagreement record is not an object")
            continue
        item_id = str(record.get("item"))
        if record.get("resolution") not in ALLOWED_RESOLUTIONS:
            problems.append(f"disagreement on {item_id} is unresolved")
            continue
        if not str(record.get("rationale", "")).strip():
            problems.append(f"disagreement on {item_id} has no rationale")
        if record.get("resolved_by") != adjudicator.get("id"):
            problems.append(f"disagreement on {item_id} not resolved by the adjudicator")
        if record.get("resolution") == "excluded":
            if item_id not in exclusions:
                problems.append(f"disagreement on {item_id} excluded without an exclusion record")
    return problems


def validate_certification_block(certification: dict) -> list[str]:
    """Public entry point for the certification rules.

    Keeps one implementation of the protocol rules so generation, validation and the
    manifest cannot drift apart.  Existing callers keep using ``_validate_certification``.
    """
    return _validate_certification({"certification": certification})


def validate_paper(paper: dict, *, reserved_ids: set[str] | None = None,
                   reserved_hashes: set[str] | None = None,
                   base_dir: Path | None = None) -> list[str]:
    """Return every problem that stops this paper from being used as holdout evidence."""
    problems: list[str] = []
    reserved_ids = RESERVED_PAPER_IDS if reserved_ids is None else reserved_ids
    reserved_hashes = reserved_page_hashes() if reserved_hashes is None else reserved_hashes

    paper_id = str(paper.get("paper_id", ""))
    if not PAPER_ID_PATTERN.match(paper_id):
        problems.append(f"paper_id {paper_id!r} is not of the form holdout-NN")
    if paper_id in reserved_ids:
        problems.append(f"paper_id {paper_id!r} is reserved for the design paper")
    if paper.get("status") != "certified":
        problems.append(f"paper status is {paper.get('status')!r}, not certified")

    for field in ("topic", "difficulty", "marks_available"):
        if not paper.get(field):
            problems.append(f"missing {field}")

    pages = paper.get("pages") or {}
    for role in ("student", "scheme"):
        entries = pages.get(role) or []
        if not entries:
            problems.append(f"no {role} pages recorded")
        for entry in entries:
            digest = entry.get("sha256")
            if not _is_hash(digest):
                problems.append(f"{role} page has an invalid sha256")
            elif digest in reserved_hashes:
                problems.append(f"{role} page duplicates a paper-01 page hash")

    reference = paper.get("reference") or {}
    if not _is_hash(reference.get("sha256")):
        problems.append("reference sha256 missing")
    certification = paper.get("certification") or {}
    if not str(certification.get("path", "")).strip():
        problems.append("certification artifact path missing")
    problems.extend(_validate_certification(paper))

    if base_dir is not None:
        reference_path = base_dir / str(reference.get("path", ""))
        if not reference_path.is_file():
            problems.append("reference file is missing")
        else:
            try:
                data = json.loads(reference_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                problems.append("reference file is not valid JSON")
            else:
                problems.extend(validate_reference_data(data))
                if _is_hash(reference.get("sha256")) and sha256_file(reference_path) != reference["sha256"]:
                    problems.append("reference file hash does not match the manifest")
    return problems


def validate_manifest(manifest: dict, *, base_dir: Path | None = None,
                      code_root: Path | None = None,
                      check_code: bool = False) -> dict:
    """Validate the whole manifest and summarise what it permits."""
    problems: list[str] = []
    papers = manifest.get("papers")
    if not isinstance(papers, list):
        problems.append("papers is not a list")
        papers = []

    seen: set[str] = set()
    certified = 0
    for paper in papers:
        paper_id = str((paper or {}).get("paper_id"))
        if paper_id in seen:
            problems.append(f"duplicate paper_id {paper_id!r}")
        seen.add(paper_id)
        paper_problems = validate_paper(paper or {}, base_dir=base_dir)
        if (paper or {}).get("status") == "certified" and not paper_problems:
            certified += 1
        problems.extend(f"{paper_id}: {problem}" for problem in paper_problems)

    for key in ("preregistered_metrics", "acceptance_criteria", "statistical_plan",
                "certification_requirements", "frozen_config"):
        if not manifest.get(key):
            problems.append(f"manifest is missing {key}")

    status = manifest.get("status")
    if certified == 0 and status != "blocked_no_certified_papers":
        problems.append("no certified paper but status does not say blocked")
    if certified > 0 and status == "blocked_no_certified_papers":
        problems.append("certified papers exist but status still says blocked")
    if 0 < certified < MIN_PAPERS_FOR_DECISION and status not in {
            "underpowered_descriptive", "blocked_no_certified_papers"}:
        problems.append("fewer than 8 certified papers; status must be descriptive")

    if check_code:
        frozen = manifest.get("frozen_config") or {}
        files = frozen.get("files") or {}
        if not files:
            problems.append("frozen_config has no file digests")
        root = code_root or HOLDOUT_DIR.parent
        for relative, expected in files.items():
            path = root / relative
            if not path.is_file():
                problems.append(f"frozen file missing: {relative}")
            elif sha256_file(path) != expected:
                problems.append(f"frozen file changed since pre-registration: {relative}")

    return {
        "valid": not problems,
        "papers": len(papers),
        "certified_papers": certified,
        "status": status,
        "decision_permitted": certified >= MIN_PAPERS_FOR_DECISION,
        "problem_count": len(problems),
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the holdout manifest")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--check-code", action="store_true",
                        help="also verify the frozen Strategy H code digests")
    args = parser.parse_args(argv)
    manifest = load(Path(args.manifest))
    result = validate_manifest(manifest, check_code=args.check_code)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

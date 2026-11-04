"""Build anonymised benchmark copies of the selected V5 pages.

Only the anonymised copies are written into this project.  The originals stay
in V5 and are never copied; the manifest records their paths and SHA-256 hashes
so the selection can be audited without moving student material around.

Redactions are rectangles of white paint over (a) the teacher's name printed in
the page footer and (b) the scanner vendor watermark.  Question content, marks
and page numbers are untouched.  Coordinates are given for the source images'
native pixel size and scaled if a page ever arrives at another resolution.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import config

#: (left, top, right, bottom) in native pixels of the 1240x1755 student scans.
STUDENT_REDACTIONS = (
    ("teacher_name_footer", (30, 1460, 600, 1570)),
    ("scanner_vendor_watermark", (930, 1570, 1240, 1755)),
)

#: (left, top, right, bottom) in native pixels of the 1540x1190 scheme renders.
SCHEME_REDACTIONS = (
    ("teacher_name_footer", (60, 1000, 600, 1090)),
)

STUDENT_QUESTIONS = {
    1: ["1", "2", "3", "4", "5", "6"],
    2: ["7", "8", "9", "10", "11", "12"],
    3: ["13", "14", "15", "16", "17", "18"],
    4: ["19", "20", "21", "22", "23", "24", "25"],
    5: ["26", "27", "28", "29", "30", "31"],
    6: ["32", "33", "34", "35", "36"],
    7: ["37"],
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redact(source: Path, target: Path, boxes) -> dict:
    image = Image.open(source).convert("RGB")
    width, height = image.size
    applied = []
    for name, box in boxes:
        # Scale from the reference sizes the boxes were measured on.
        ref_w, ref_h = (1240, 1755) if name and source.parent.name == ".tmp_paper" else (1540, 1190)
        sx, sy = width / ref_w, height / ref_h
        scaled = tuple(int(round(v * (sx if i % 2 == 0 else sy))) for i, v in enumerate(box))
        left, top, right, bottom = scaled
        image.paste((255, 255, 255), (max(0, left), max(0, top), min(width, right), min(height, bottom)))
        applied.append({"name": name, "box": list(scaled), "fill": "white"})
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)
    return {
        "width": width,
        "height": height,
        "redactions": applied,
        "sha256": _sha256(target),
    }


def build_anonymised_copies() -> dict:
    config.ensure_dirs()
    if not config.V5_STUDENT_DIR.is_dir() or not config.V5_SCHEME_DIR.is_dir():
        raise FileNotFoundError("V5 source image directories are missing; refusing to fabricate a dataset")

    students = sorted(config.V5_STUDENT_DIR.glob("p0*.png"))
    schemes = sorted(config.V5_SCHEME_DIR.glob("page-*.png"))
    if len(students) != 7:
        raise ValueError(f"expected 7 student pages, found {len(students)}")
    if len(schemes) != 21:
        raise ValueError(f"expected 21 scheme pages, found {len(schemes)}")

    student_records = []
    for index, source in enumerate(students, start=1):
        target = config.SAMPLES_DIR / f"student_p{index:02d}.png"
        info = _redact(source, target, STUDENT_REDACTIONS)
        student_records.append({
            "page": index,
            "source": str(source),
            "source_sha256": _sha256(source),
            "sample": str(target.relative_to(config.BENCHMARK_DIR)).replace("\\", "/"),
            "questions": STUDENT_QUESTIONS.get(index, []),
            **info,
        })

    scheme_records = []
    for index, source in enumerate(schemes, start=1):
        target = config.SAMPLES_DIR / f"scheme_p{index:02d}.png"
        info = _redact(source, target, SCHEME_REDACTIONS)
        scheme_records.append({
            "page": index,
            "source": str(source),
            "source_sha256": _sha256(source),
            "sample": str(target.relative_to(config.BENCHMARK_DIR)).replace("\\", "/"),
            **info,
        })

    manifest = {
        "dataset_id": config.PAPER_ID,
        "title": "Algebraic Manipulation (Simplifying Expressions) workbook, pages 340-346",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "project": "MATH_CHECKER_V5 (read-only)",
            "source": "V5 temporary ingestion renders retained by the correction pipeline",
            "original_pdf_available": False,
            "note": (
                "No original PDF is present in the V5 tree. The retained page renders are the "
                "highest-fidelity copy available and are preserved byte-for-byte apart from the "
                "redactions listed here."
            ),
            "student_identity": "No student name is visible on any selected page.",
            "redacted": "Teacher name printed in the footer and the scanner vendor watermark.",
        },
        "paper": {
            "question_count": 37,
            "markable_item_count": 38,
            "marks": 87,
            "marks_note": "Sum of the marks printed next to each question; see ground_truth/paper-01.json.",
            "pages": len(student_records),
            "scheme_pages": len(scheme_records),
            "handwriting": True,
            "question_range": "Q1-Q37 (Q1 has parts a and d; Q37 has parts a and b)",
        },
        "anonymisation": {
            "method": "white rectangle over measured footer regions; no resampling or recompression of content",
            "student_boxes": [list(b) for _, b in STUDENT_REDACTIONS],
            "scheme_boxes": [list(b) for _, b in SCHEME_REDACTIONS],
        },
        "student_pages": student_records,
        "scheme_pages": scheme_records,
        "ground_truth": {
            "path": "ground_truth/paper-01.json",
            "status": "candidate_not_teacher_certified",
            "basis": "printed criterion-level mark scheme plus independent re-solving",
        },
    }
    config.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    data = build_anonymised_copies()
    print(f"wrote {data['paper']['pages']} student pages, "
          f"{data['paper']['scheme_pages']} scheme pages, manifest at {config.MANIFEST_PATH}")

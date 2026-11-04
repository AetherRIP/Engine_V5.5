"""Load the anonymised paper and build request parts.

No V5 code is imported.  The loader reads only files under
``benchmark/anonymized_samples`` and the candidate ground truth, and it refuses
to run when either is missing rather than inventing content.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import config, ground_truth

#: One request encoding for every strategy.  The anonymised PNGs are the
#: archival copies; requests carry JPEG at a fixed quality so the 28-image
#: whole-paper request stays inside the provider's inline request limit and no
#: strategy sees a differently processed image.
REQUEST_JPEG_QUALITY = 88


@dataclass(frozen=True)
class Page:
    number: int
    path: Path
    label: str

    def part(self) -> dict:
        image = Image.open(self.path).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=REQUEST_JPEG_QUALITY, optimize=True)
        data = base64.b64encode(buffer.getvalue()).decode("ascii")
        return {"inline_data": {"mime_type": "image/jpeg", "data": data}}


def student_pages() -> list[Page]:
    pages = sorted(config.SAMPLES_DIR.glob("student_p*.png"))
    if len(pages) != 7:
        raise FileNotFoundError("anonymised student pages are missing; run benchmark.code.anonymize")
    return [Page(number=index, path=path, label=f"student page {index} of {len(pages)}")
            for index, path in enumerate(pages, start=1)]


def scheme_pages() -> list[Page]:
    pages = sorted(config.SAMPLES_DIR.glob("scheme_p*.png"))
    if len(pages) != 21:
        raise FileNotFoundError("anonymised scheme pages are missing; run benchmark.code.anonymize")
    return [Page(number=index, path=path, label=f"mark scheme page {index} of {len(pages)}")
            for index, path in enumerate(pages, start=1)]


def scoreable_items() -> list[dict]:
    data = ground_truth.load()
    items = [item for item in data["items"] if item["status"] == "scored"]
    if not items:
        raise ValueError("ground truth has no scoreable items")
    return items


def item_ids() -> list[str]:
    return [item["id"] for item in scoreable_items()]


def max_marks() -> dict[str, int]:
    return {item["id"]: item["max_marks"] for item in scoreable_items()}


def item_page_map() -> dict[str, int]:
    return {item["id"]: item["student_page"] for item in scoreable_items()}


#: Six marking batches used by strategies B and C.  The grouping follows the
#: page order and keeps every question in exactly one batch.
BATCHES: dict[str, list[str]] = {
    "b1": ["1a", "1d", "2", "3", "4", "5", "6"],
    "b2": ["7", "8", "9", "10", "11", "12"],
    "b3": ["13", "14", "15", "16b", "16d", "17", "18"],
    "b4": ["19", "20", "21", "22", "23", "24", "25"],
    "b5": ["26", "27", "28", "29", "30", "31"],
    "b6": ["32", "33", "34", "35", "36", "37a", "37b"],
}


def batches_for_scored() -> dict[str, list[str]]:
    """Batches filtered to scoreable items (excluded items are not requested)."""
    allowed = set(item_ids())
    return {name: [item for item in ids if item in allowed] for name, ids in BATCHES.items()}


def images_for_page(number: int) -> list[Page]:
    return [page for page in student_pages() if page.number == number]


def scheme_page_for_item(item: dict) -> Page:
    return scheme_pages()[item["scheme_page"] - 1]


def manifest() -> dict:
    return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))


def item_list_text(ids: list[str] | None = None) -> str:
    ids = ids or item_ids()
    by_id = {item["id"]: item for item in scoreable_items()}
    return "\n".join(f"- {item_id}: max {by_id[item_id]['max_marks']} marks" for item_id in ids)


def text_part(text: str) -> dict:
    return {"text": text}

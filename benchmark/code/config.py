"""Paths, model IDs and pricing for the correction-strategy benchmark.

Every number that could be mistaken for a measurement is labelled: pricing is
read from ``pricing.json`` (written from the official provider page with a
retrieval timestamp), and the experiment never invents a price it did not read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCHMARK_DIR.parent

V5_ROOT = Path(r"C:\Projects\MATH_CHECKER_V5")
V5_STUDENT_DIR = V5_ROOT / ".tmp_paper"
V5_SCHEME_DIR = V5_ROOT / ".tmp_scheme_pages"
V5_KEY_FILE = V5_ROOT / "API_KEYS.txt"

SAMPLES_DIR = BENCHMARK_DIR / "anonymized_samples"
GROUND_TRUTH_DIR = BENCHMARK_DIR / "ground_truth"
RESULTS_DIR = BENCHMARK_DIR / "results"
REPORTS_DIR = BENCHMARK_DIR / "reports"
MANIFEST_PATH = BENCHMARK_DIR / "dataset_manifest.json"
USAGE_LOG_PATH = RESULTS_DIR / "api_usage.jsonl"
KEY_STATE_PATH = RESULTS_DIR / "key_pool_state.json"
PRICING_PATH = BENCHMARK_DIR / "pricing.json"

PAPER_ID = "paper-01"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
#: Primary multimodal marking model.  Availability is verified by a real probe
#: before any benchmark request; a failed probe is recorded, never assumed.
PRIMARY_MODEL = "gemini-3.6-flash"

#: Cheap model for the routine stage of strategy C.
LITE_MODEL = "gemini-3.1-flash-lite"

#: Stronger model for escalation of ambiguous items in strategy C.  Empty when
#: no stronger model is reachable; escalation then uses the primary model with
#: an explicit note.
STRONG_MODEL = "gemini-3.1-pro-preview"

#: Candidate list probed at start-up, in preference order.  The first reachable
#: entry of each role is used; every substitution is recorded in the results.
MODEL_CANDIDATES = {
    "primary": ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.8-flash"],
    "lite": ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
    "strong": ["gemini-3.1-pro-preview", "gemini-3.6-flash"],
}

# ---------------------------------------------------------------------------
# Generation settings (identical wherever the provider exposes them)
# ---------------------------------------------------------------------------

TEMPERATURE = 0.0
TOP_P = 0.95
THINKING_BUDGET = 0
#: Models that reject an explicit zero thinking budget.  The override is a
#: documented per-model capability difference, not a per-strategy advantage.
THINKING_OVERRIDES = {"gemini-3.5-flash-lite": None}


def thinking_budget_for(model: str) -> int | None:
    return THINKING_OVERRIDES.get(model, THINKING_BUDGET)


MAX_OUTPUT_TOKENS = 16384
REQUEST_TIMEOUT_SECONDS = 300

#: Requests of each strategy per run (used for coverage planning).
STRATEGY_BATCHES = {
    # A: one whole-paper request. B: scheme + 7 page transcriptions + 6 marking batches.
    # C: document + scheme + 6 marking batches; escalation adds at most MAX_ESCALATIONS_PER_RUN.
    "a": 1,
    "b": 14,
    "c": 8,
}

#: A split is only a fallback for a whole-paper response that omitted items.
#: It is capped so a malformed response cannot turn A into an unbounded spend.
A_SPLIT_CHUNK_SIZE = 6
MAX_A_SPLIT_REQUESTS = 2

#: Two runs per strategy, interleaved to spread quota conditions.
RUN_ORDER = [
    ("a", 1), ("b", 1), ("c", 1),
    ("a", 2), ("b", 2), ("c", 2),
]

#: Hard ceiling on benchmark (non-probe) requests, so a quota surprise cannot
#: turn the pilot into an unbounded spend.
MAX_BENCHMARK_REQUESTS = 80
MAX_ESCALATIONS_PER_RUN = 6


@dataclass
class Pricing:
    """Per-million-token prices read from the provider's pricing page."""

    model: str
    input_per_million: float | None = None
    output_per_million: float | None = None
    cached_input_per_million: float | None = None
    source_url: str = ""
    retrieved_on: str = ""
    notes: str = ""
    extra: dict = field(default_factory=dict)

    def cost(self, *, input_tokens: int | None, output_tokens: int | None,
             cached_tokens: int | None = None) -> float | None:
        if self.input_per_million is None or self.output_per_million is None:
            return None
        if input_tokens is None or output_tokens is None:
            return None
        cached = 0 if cached_tokens is None else max(0, cached_tokens)
        # Cached input is reported *inside* input_tokens by Gemini.  When a
        # cached rate is known the cached share is repriced; otherwise the full
        # input price is used and the saving is reported as unknown.
        billable_input = max(0, input_tokens - cached)
        cost = billable_input / 1_000_000 * self.input_per_million
        if cached and self.cached_input_per_million is not None:
            cost += cached / 1_000_000 * self.cached_input_per_million
        elif cached:
            cost += cached / 1_000_000 * self.input_per_million
        cost += output_tokens / 1_000_000 * self.output_per_million
        return round(cost, 8)


def load_pricing() -> dict[str, Pricing]:
    """Read ``pricing.json``; an absent or malformed file yields no prices.

    Returning an empty table is deliberate: the cost column then reads
    "unavailable" rather than a number this project guessed.
    """
    if not PRICING_PATH.is_file():
        return {}
    try:
        raw = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, Pricing] = {}
    for model, entry in (raw.get("models") or {}).items():
        if not isinstance(entry, dict):
            continue
        out[model] = Pricing(
            model=model,
            input_per_million=entry.get("input_per_million"),
            output_per_million=entry.get("output_per_million"),
            cached_input_per_million=entry.get("cached_input_per_million"),
            source_url=raw.get("source_url", ""),
            retrieved_on=raw.get("retrieved_on", ""),
            notes=entry.get("notes", ""),
            extra=entry,
        )
    return out


def read_api_keys() -> list[str]:
    """Read the authorised key pool into memory.

    The file is V5's key list.  Values are never written, printed or logged;
    callers only ever see positional labels.
    """
    keys: list[str] = []
    for line in V5_KEY_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        keys.append(value)
    return keys


def ensure_dirs() -> None:
    for path in (SAMPLES_DIR, GROUND_TRUTH_DIR, RESULTS_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}

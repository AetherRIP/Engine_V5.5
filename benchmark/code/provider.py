"""Thin Gemini REST adapter.

Deliberately not the vendor SDK: the benchmark needs every request, retry and
usage field to be visible in one place, and it must never log a URL or header
that contains a credential.  Requests are JSON ``generateContent`` calls with
``x-goog-api-key`` in a header (never in the URL).
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import config

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
USER_AGENT = "mathchecker-benchmark/1.0"


@dataclass
class ProviderResult:
    status: str                      # ok / invalid / quota / network / http_error / model_unavailable
    http_status: int | None = None
    error_code: str = ""
    error_message: str = ""
    daily_quota: bool = False
    retry_after_s: float | None = None
    quota_id: str = ""
    latency_ms: int = 0
    text: str = ""
    usage: dict = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class GeminiClient:
    def __init__(self, timeout: int | None = None):
        self.timeout = timeout or config.REQUEST_TIMEOUT_SECONDS

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, key: str, body: dict | None = None) -> tuple[int, dict, int]:
        url = f"{BASE_URL}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("x-goog-api-key", key)
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                return response.status, payload, int((time.monotonic() - started) * 1000)
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"raw": raw[:1000]}
            return error.code, payload, int((time.monotonic() - started) * 1000)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as error:
            reason = getattr(error, "reason", error)
            return 0, {"network_error": str(reason)[:300]}, int((time.monotonic() - started) * 1000)

    # -- listing / probing -------------------------------------------------

    def list_models(self, key: str) -> dict:
        status, payload, latency = self._request("GET", "/models?pageSize=1000", key)
        if status == 200:
            names = [str(entry.get("name", "")).replace("models/", "")
                     for entry in payload.get("models", []) if isinstance(entry, dict)]
            return {"status": "ok", "http_status": status, "latency_ms": latency,
                    "models": names, "error_code": ""}
        classified = self._classify_error(status, payload, latency, model="")
        data = dict(classified.__dict__)
        data["models"] = []
        return data

    def probe_generate(self, key: str, model: str | None = None) -> ProviderResult:
        model = model or config.PRIMARY_MODEL
        body = {
            "contents": [{"role": "user", "parts": [{"text": "Reply with OK."}]}],
            "generationConfig": {"maxOutputTokens": 1, "temperature": 0},
        }
        status, payload, latency = self._request(
            "POST", f"/models/{model}:generateContent", key, body)
        if status == 200:
            return ProviderResult(status="ok", http_status=status, latency_ms=latency,
                                  model=model, usage=_usage(payload))
        classified = self._classify_error(status, payload, latency, model=model)
        return ProviderResult(**{**classified.__dict__})

    # -- generation --------------------------------------------------------

    def generate(self, key: str, *, model: str, parts: list[dict], system: str,
                 schema: dict, max_output_tokens: int = config.MAX_OUTPUT_TOKENS,
                 temperature: float = config.TEMPERATURE,
                 thinking_budget: int | None = config.THINKING_BUDGET) -> ProviderResult:
        generation: dict = {
            "temperature": temperature,
            "topP": config.TOP_P,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        }
        if thinking_budget is not None:
            generation["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation,
        }
        status, payload, latency = self._request(
            "POST", f"/models/{model}:generateContent", key, body)
        if status == 200:
            text = _extract_text(payload)
            candidates = payload.get("candidates") or []
            finish_reason = (str(candidates[0].get("finishReason", ""))
                             if candidates and isinstance(candidates[0], dict) else "")
            return ProviderResult(status="ok", http_status=status, latency_ms=latency,
                                  text=text, usage=_usage(payload), model=model,
                                  finish_reason=finish_reason,
                                  raw={"candidates": len(candidates)})
        return self._classify_error(status, payload, latency, model=model)

    # -- errors ------------------------------------------------------------

    def _classify_error(self, status: int, payload: dict, latency: int, model: str) -> ProviderResult:
        error = payload.get("error") if isinstance(payload, dict) else None
        code = ""
        message = ""
        details = []
        if isinstance(error, dict):
            code = str(error.get("status") or error.get("code") or "")
            message = str(error.get("message") or "")[:400]
            details = error.get("details") or []
        elif isinstance(payload, dict) and payload.get("network_error"):
            message = str(payload["network_error"])[:300]

        quota_id = ""
        daily = False
        retry_after = None
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict):
                continue
            if detail.get("@type", "").endswith("QuotaFailure"):
                violations = detail.get("violations") or []
                if violations and isinstance(violations[0], dict):
                    quota_id = str(violations[0].get("quotaId", ""))
            if detail.get("@type", "").endswith("RetryInfo"):
                retry_after = _duration(str(detail.get("retryDelay", "")))
            for violation in detail.get("violations") or []:
                if isinstance(violation, dict) and violation.get("quotaId"):
                    quota_id = str(violation["quotaId"])

        lower = f"{code} {message} {quota_id}".lower()
        if "quota" in lower and ("perday" in lower or "per day" in lower or "daily" in lower):
            daily = True

        if status == 429:
            kind = "quota"
        elif status in (401, 403):
            kind = "invalid" if ("api key" in lower or "api_key" in lower or "unauthenticated" in lower) else "http_error"
        elif status == 400 and ("api key" in lower or "api_key" in lower):
            kind = "invalid"
        elif status == 404:
            kind = "model_unavailable"
        elif status == 0:
            kind = "network"
        elif status >= 500:
            kind = "http_error"
        else:
            kind = "http_error"

        return ProviderResult(
            status=kind, http_status=status or None, error_code=code or f"HTTP_{status}",
            error_message=message, daily_quota=daily, retry_after_s=retry_after,
            quota_id=quota_id, latency_ms=latency, model=model,
        )


def _extract_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))


def _usage(payload: dict) -> dict:
    metadata = payload.get("usageMetadata") or {}
    image_tokens = 0
    for detail in metadata.get("promptTokensDetails") or []:
        if isinstance(detail, dict) and str(detail.get("modality", "")).upper() == "IMAGE":
            image_tokens += int(detail.get("tokenCount") or 0)
    return {
        "input_tokens": metadata.get("promptTokenCount"),
        "output_tokens": metadata.get("candidatesTokenCount"),
        "cached_tokens": metadata.get("cachedContentTokenCount"),
        "thoughts_tokens": metadata.get("thoughtsTokenCount"),
        "total_tokens": metadata.get("totalTokenCount"),
        "image_tokens": image_tokens or None,
        "reported": bool(metadata),
    }


def _duration(text: str) -> float | None:
    if not text:
        return None
    value = text.strip().lower()
    try:
        if value.endswith("ms"):
            return float(value[:-2]) / 1000
        if value.endswith("s"):
            return float(value[:-1])
    except ValueError:
        return None
    return None

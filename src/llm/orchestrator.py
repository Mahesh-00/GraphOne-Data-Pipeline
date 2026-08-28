"""
Multi-tier LLM extraction orchestrator.

Fallback chain: Gemini Flash -> Groq Llama 3 -> DeepSeek (order and members
configurable in src/config.py -- LLM_PROVIDER_CHAIN).

Per call:
  1. Chunk the input so it can never trigger a 413 for the target provider.
  2. Try the first provider in the chain.
  3. On 429 -> retry same provider with exponential backoff + jitter, up to
     MAX_RETRIES; if still failing, fall through to the next provider.
  4. On 4xx (bad request, e.g. malformed payload) -> fall through immediately
     (retrying won't help).
  5. On 5xx / timeout -> retry same provider first (transient), then fall through.
  6. If ALL providers fail for a chunk, the chunk is logged to a
     dead-letter list for later manual/automated reprocessing -- it is
     NEVER silently fabricated.
"""
import json
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

from src.config import (
    LLM_PROVIDER_CHAIN,
    LLM_API_KEYS,
    LLM_ENDPOINTS,
    LLM_MAX_INPUT_TOKENS,
    MAX_RETRIES,
    BASE_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    MAX_CONCURRENT_LLM_CALLS,
)
from src.llm.chunker import chunk_document
from src.llm.prompts import SYSTEM_PROMPT, build_prompt
from src.utils.async_pool import ConcurrencyPool, RetryableError, with_retry
from src.utils.logging_config import get_logger, log_ctx
from dateutil import parser as _dateparser

logger = get_logger(__name__)


@dataclass
class ExtractionResult:
    success: bool
    provider_used: Optional[str]
    data: Optional[dict[str, Any]]
    error: Optional[str] = None


class DeadLetterQueue:
    """Chunks/records that exhausted every provider. Never fabricated -- queued for reprocessing."""

    def __init__(self):
        self.items: list[dict[str, Any]] = []

    def add(self, record_type: str, source_url: str, content: str, error: str) -> None:
        self.items.append(
            {"record_type": record_type, "source_url": source_url, "content": content, "error": error}
        )


class LLMOrchestrator:
    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self._owns_session = session is None
        self._pool = ConcurrencyPool(MAX_CONCURRENT_LLM_CALLS)
        self.dead_letter = DeadLetterQueue()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _call_provider(self, provider: str, prompt: str) -> dict[str, Any]:
        """Single HTTP call to one provider. Raises RetryableError for 429/5xx."""
        session = await self._get_session()
        api_key = LLM_API_KEYS.get(provider, "")
        endpoint = LLM_ENDPOINTS[provider]

        if provider == "gemini_flash":
            url = f"{endpoint}?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{prompt}"}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            }
            headers = {"Content-Type": "application/json"}
        else:
            # Groq and DeepSeek both speak the OpenAI-compatible chat completions schema
            import os
            url = endpoint
            groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
            payload = {
                "model": groq_model if provider == "groq_llama3" else "deepseek-chat",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 429:
                retry_after = resp.headers.get("Retry-After")
                raise RetryableError(f"{provider}_429", retry_after=float(retry_after) if retry_after else None)
            if resp.status == 413:
                # Should not happen if chunking is correct, but treat as non-retryable
                # on THIS provider -- fall through to next provider in chain instead.
                raise RuntimeError(f"{provider}_413_payload_too_large")
            if resp.status >= 500:
                raise RetryableError(f"{provider}_5xx_{resp.status}")
            if resp.status >= 400:
                body = await resp.text()
                raise RuntimeError(f"{provider}_4xx_{resp.status}: {body[:300]}")

            data = await resp.json()
            return self._extract_text(provider, data)

    @staticmethod
    def _extract_text(provider: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            if provider == "gemini_flash":
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                text = data["choices"][0]["message"]["content"]
            return json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{provider}_unparseable_response: {exc}") from exc

    async def extract(self, record_type: str, source_url: str, title: str, body: str) -> ExtractionResult:
        """
        Extracts one record, chunking per the CURRENT provider being tried
        (chunk budgets differ per provider, e.g. Groq's small context vs
        Gemini's huge one) and walking the fallback chain on failure.
        """
        last_error = "no_providers_attempted"

        log_ctx(logger, 20, "llm_extraction_start", record_type=record_type, source_url=source_url)

        def _validate_extraction(rt: str, data: Any) -> dict[str, Any]:
            """Validate and normalize the extraction JSON for `rt`.

            Returns normalized dict with exact expected keys, or raises RuntimeError.
            """
            if not isinstance(data, dict):
                raise RuntimeError("extraction_not_object")

            def _coerce_str(v):
                return v if v is None or isinstance(v, str) else str(v)

            def _coerce_int(v):
                if v is None:
                    return None
                if isinstance(v, int):
                    return v
                try:
                    return int(v)
                except Exception:
                    return None

            def _coerce_bool(v):
                if v is None:
                    return None
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    if v.lower() in ("true", "yes", "1"):
                        return True
                    if v.lower() in ("false", "no", "0"):
                        return False
                return None

            out: dict[str, Any] = {}

            if rt == "STARTUP":
                out["entityName"] = _coerce_str(data.get("entityName"))
                out["employeeCount"] = _coerce_int(data.get("employeeCount"))
                out["description"] = _coerce_str(data.get("description"))

            elif rt == "PRODUCT":
                out["productName"] = _coerce_str(data.get("productName"))
                out["startupName"] = _coerce_str(data.get("startupName"))
                pm = data.get("pricingModel")
                if pm is None:
                    out["pricingModel"] = None
                else:
                    try:
                        pm_s = str(pm).upper()
                        out["pricingModel"] = pm_s if pm_s in ("FREE", "FREEMIUM", "PAID", "ENTERPRISE") else None
                    except Exception:
                        out["pricingModel"] = None
                out["description"] = _coerce_str(data.get("description"))

            elif rt == "JOB":
                out["company"] = _coerce_str(data.get("company"))
                out["title"] = _coerce_str(data.get("title"))
                # Normalize date to ISO-8601 or None
                raw_date = data.get("date")
                if raw_date:
                    try:
                        dt = _dateparser.parse(str(raw_date))
                        out["date"] = dt.isoformat()
                    except Exception:
                        out["date"] = None
                else:
                    out["date"] = None
                out["is_remote"] = _coerce_bool(data.get("is_remote"))
                out["role_family"] = _coerce_str(data.get("role_family"))

            else:
                # Unknown record type: accept any dict but return as-is
                return data

            return out

        for provider in LLM_PROVIDER_CHAIN:
            if not LLM_API_KEYS.get(provider):
                log_ctx(logger, 20, "skipping_provider_no_api_key", provider=provider)
                continue
            log_ctx(logger, 20, "llm_provider_attempt", provider=provider)

            max_tokens = LLM_MAX_INPUT_TOKENS[provider]
            chunks = chunk_document(title, body, max_tokens=max_tokens)

            # For extraction (as opposed to summarization), we only need the
            # highest-signal chunk (the first one, which always includes the
            # title) -- avoids wasted calls on low-signal trailing chunks.
            primary_chunk = chunks[0]
            prompt = build_prompt(record_type, source_url, primary_chunk.text)

            def _on_retry(attempt: int, exc: Exception) -> None:
                log_ctx(logger, 30, "llm_retry", provider=provider, attempt=attempt, error=str(exc))

            try:
                async with self._pool:
                    result = await with_retry(
                        lambda: self._call_provider(provider, prompt),
                        max_retries=MAX_RETRIES,
                        base_backoff=BASE_BACKOFF_SECONDS,
                        max_backoff=MAX_BACKOFF_SECONDS,
                        on_retry=_on_retry,
                    )

                # Validate the provider output matches expected schema
                try:
                    validated = _validate_extraction(record_type, result)
                except Exception as exc:
                    # Treat validation failures like a provider failure and fall through
                    last_error = f"{provider}_validation_failed:{exc}"
                    log_ctx(logger, 30, "provider_validation_failed", provider=provider, error=str(exc))
                    continue

                log_ctx(logger, 20, "llm_extraction_succeeded", provider=provider, record_type=record_type, source_url=source_url)
                return ExtractionResult(success=True, provider_used=provider, data=validated)

            except Exception as exc:  # noqa: BLE001 -- fall through to next provider
                last_error = str(exc)
                log_ctx(logger, 30, "provider_failed_falling_through", provider=provider, error=last_error)
                continue

        # Every provider in the chain failed -- never fabricate, queue for reprocessing.
        self.dead_letter.add(record_type, source_url, body[:2000], last_error)
        log_ctx(logger, 40, "all_providers_exhausted", source_url=source_url, error=last_error)
        return ExtractionResult(success=False, provider_used=None, data=None, error=last_error)

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()

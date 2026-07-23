from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from loguru import logger

from backend.config import settings


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class AllProvidersFailedError(Exception):
    """Raised when every provider in the fallback chain has failed."""


class QuotaExceededError(Exception):
    """HTTP 429 or explicit quota-exceeded signal from a provider."""


class OllamaResourceError(Exception):
    """Connection error, timeout, or out-of-resources response from Ollama."""


# ---------------------------------------------------------------------------
# Model Router
# ---------------------------------------------------------------------------


class ModelRouter:
    """Routes LLM calls through a capability-tier fallback chain.

    Each capability tier (fast_text, complex_reasoning, vision) has an ordered
    list of {provider, model} entries.  The router tries them in sequence,
    skipping any that are currently in their cooldown window.
    """

    _TIMEOUT = 120.0  # seconds per API call

    def __init__(self) -> None:
        self._tiers: dict[str, list[dict[str, str]]] = settings.CAPABILITY_TIERS
        # (provider, model) → datetime when cooldown expires
        self._cooldowns: dict[tuple[str, str], datetime] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        tier: str,
        messages: list[dict],
        **kwargs,
    ) -> str:
        """Run a text-only chat completion through the given capability tier."""
        return await self._run_chain(tier, messages, image_base64=None, **kwargs)

    async def chat_with_image(
        self,
        tier: str,
        messages: list[dict],
        image_base64: str,
        **kwargs,
    ) -> str:
        """Run a vision chat completion (image + text)."""
        return await self._run_chain(tier, messages, image_base64=image_base64, **kwargs)

    async def get_embedding(self, text: str) -> list[float]:
        """Return an embedding vector for *text* using the embedding tier."""
        chain = self._tiers.get("embedding", [])
        for entry in chain:
            provider = entry["provider"]
            model = entry["model"]
            if self._is_in_cooldown(provider, model):
                logger.debug("Skipping {}/{} (cooldown)", provider, model)
                continue

            base_url, api_key = self._resolve_provider(provider)
            try:
                vector = await self._make_embedding_call(base_url, api_key, model, text)
                return vector
            except QuotaExceededError:
                self._set_cooldown(provider, model, hours=1)
                logger.warning("Quota exceeded for {}/{}, setting 1h cooldown", provider, model)
            except OllamaResourceError as exc:
                logger.warning("Resource error for {}/{}: {}", provider, model, exc)

        raise AllProvidersFailedError("All providers failed for embedding request.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_chain(
        self,
        tier: str,
        messages: list[dict],
        image_base64: str | None,
        **kwargs,
    ) -> str:
        chain = self._tiers.get(tier)
        if not chain:
            raise AllProvidersFailedError(f"Unknown capability tier: {tier!r}")

        for entry in chain:
            provider = entry["provider"]
            model = entry["model"]

            if self._is_in_cooldown(provider, model):
                logger.debug("Skipping {}/{} (cooldown)", provider, model)
                continue

            base_url, api_key = self._resolve_provider(provider)
            try:
                response = await self._make_chat_call(
                    base_url, api_key, model, messages, image_base64, **kwargs
                )
                return response
            except QuotaExceededError:
                self._set_cooldown(provider, model, hours=1)
                logger.warning(
                    "Quota exceeded for {}/{}, setting 1h cooldown", provider, model
                )
            except OllamaResourceError as exc:
                logger.warning(
                    "Resource/timeout error for {}/{}: {}", provider, model, exc
                )

        raise AllProvidersFailedError(
            f"All providers failed for tier={tier!r}. "
            "Check Ollama is running and cloud quota is available."
        )

    def _resolve_provider(self, provider: str) -> tuple[str, str]:
        """Return (base_url, api_key) for a given provider name."""
        if provider == "ollama_local":
            return settings.OLLAMA_LOCAL_BASE_URL, ""
        if provider == "ollama_cloud":
            return settings.OLLAMA_CLOUD_BASE_URL, settings.OLLAMA_CLOUD_API_KEY
        raise ValueError(f"Unknown provider: {provider!r}")

    def _is_in_cooldown(self, provider: str, model: str) -> bool:
        key = (provider, model)
        expiry = self._cooldowns.get(key)
        if expiry is None:
            return False
        if datetime.now(timezone.utc) < expiry:
            return True
        # Expired — remove it
        del self._cooldowns[key]
        return False

    def _set_cooldown(self, provider: str, model: str, hours: int = 1) -> None:
        self._cooldowns[(provider, model)] = datetime.now(timezone.utc) + timedelta(hours=hours)

    async def _make_chat_call(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        image_base64: str | None,
        **kwargs,
    ) -> str:
        """POST to /v1/chat/completions and return the assistant message content."""
        if not base_url:
            raise OllamaResourceError("Provider base URL is not configured.")

        # Inject image into the last user message when provided
        if image_base64:
            messages = list(messages)  # shallow copy
            last_user = next(
                (m for m in reversed(messages) if m.get("role") == "user"), None
            )
            if last_user is not None:
                idx = messages.index(last_user)
                content = last_user.get("content", "")
                if isinstance(content, str):
                    content = [
                        {"type": "text", "text": content},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        },
                    ]
                messages[idx] = {**last_user, "content": content}

        payload = {"model": model, "messages": messages, **kwargs}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        url = base_url.rstrip("/") + "/v1/chat/completions"
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                raise OllamaResourceError(str(exc)) from exc

        if resp.status_code == 429:
            raise QuotaExceededError(f"HTTP 429 from {url}")
        if resp.status_code >= 500:
            raise OllamaResourceError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise OllamaResourceError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _make_embedding_call(
        self,
        base_url: str,
        api_key: str,
        model: str,
        text: str,
    ) -> list[float]:
        if not base_url:
            raise OllamaResourceError("Provider base URL is not configured.")

        payload = {"model": model, "input": text}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        url = base_url.rstrip("/") + "/v1/embeddings"
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                raise OllamaResourceError(str(exc)) from exc

        if resp.status_code == 429:
            raise QuotaExceededError(f"HTTP 429 from {url}")
        if resp.status_code >= 400:
            raise OllamaResourceError(f"HTTP {resp.status_code} from {url}")

        data = resp.json()
        return data["data"][0]["embedding"]

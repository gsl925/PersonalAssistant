"""Settings API router — manage capability tiers and query available Ollama models."""
from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, status
from loguru import logger
from pydantic import BaseModel

from backend.config import CapabilityTiers, settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ModelEntry(BaseModel):
    provider: str
    model: str


class CapabilityTiersResponse(BaseModel):
    tiers: CapabilityTiers


class CapabilityTiersPatchRequest(BaseModel):
    tiers: CapabilityTiers


class OllamaModel(BaseModel):
    name: str
    size: int | None = None
    modified_at: str | None = None
    digest: str | None = None


class OllamaModelsResponse(BaseModel):
    models: list[OllamaModel]


class TestModelRequest(BaseModel):
    provider: str
    model: str


class TestModelResponse(BaseModel):
    provider: str
    model: str
    reachable: bool
    detail: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/capability-tiers", response_model=CapabilityTiersResponse)
async def get_capability_tiers() -> CapabilityTiersResponse:
    """Return the current capability tier → fallback chain configuration."""
    return CapabilityTiersResponse(tiers=dict(settings.CAPABILITY_TIERS))


@router.patch("/capability-tiers", response_model=CapabilityTiersResponse)
async def update_capability_tiers(
    body: CapabilityTiersPatchRequest,
) -> CapabilityTiersResponse:
    """Overwrite capability tier config in-process.

    This updates the live ``settings.CAPABILITY_TIERS`` dict and re-initialises
    the ModelRouter so subsequent requests use the new chain.  The change is
    ephemeral — it will revert on server restart unless you also update your
    ``.env`` / environment variables.
    """
    from backend.main import get_model_router

    new_tiers: CapabilityTiers = {}
    for tier_name, chain in body.tiers.items():
        if not isinstance(chain, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tier '{tier_name}' must be a list of {{provider, model}} entries.",
            )
        for entry in chain:
            if not isinstance(entry, dict) or "provider" not in entry or "model" not in entry:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Each entry in tier '{tier_name}' must have 'provider' and 'model' keys.",
                )
        new_tiers[tier_name] = chain

    # Update the singleton settings object.
    settings.CAPABILITY_TIERS = new_tiers  # type: ignore[assignment]

    # Re-wire the model router to pick up the new tiers.
    model_router = get_model_router()
    model_router._tiers = new_tiers  # type: ignore[attr-defined]

    logger.info("Capability tiers updated: {}", list(new_tiers.keys()))
    return CapabilityTiersResponse(tiers=new_tiers)


@router.get("/ollama-models", response_model=OllamaModelsResponse)
async def list_ollama_models() -> OllamaModelsResponse:
    """Query the local Ollama instance and return the list of installed models."""
    base_url = settings.OLLAMA_LOCAL_BASE_URL.rstrip("/")
    url = f"{base_url}/api/tags"

    logger.debug("Fetching Ollama model list from {}", url)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot reach local Ollama at {base_url}: {exc}",
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama returned HTTP {resp.status_code}",
        )

    data = resp.json()
    raw_models: list[dict] = data.get("models", [])
    models = [
        OllamaModel(
            name=m.get("name", ""),
            size=m.get("size"),
            modified_at=m.get("modified_at"),
            digest=m.get("digest"),
        )
        for m in raw_models
    ]
    logger.info("Ollama reports {} model(s)", len(models))
    return OllamaModelsResponse(models=models)


@router.post("/test-model", response_model=TestModelResponse)
async def test_model(body: TestModelRequest) -> TestModelResponse:
    """Probe a provider/model pair with a minimal chat request to verify reachability.

    Returns ``reachable: true`` if the model responds within the timeout,
    ``false`` otherwise — never raises an HTTP error so callers can handle
    partial availability gracefully.
    """
    if body.provider == "ollama_local":
        base_url = settings.OLLAMA_LOCAL_BASE_URL
        api_key = ""
    elif body.provider == "ollama_cloud":
        base_url = settings.OLLAMA_CLOUD_BASE_URL
        api_key = settings.OLLAMA_CLOUD_API_KEY
    else:
        return TestModelResponse(
            provider=body.provider,
            model=body.model,
            reachable=False,
            detail=f"Unknown provider '{body.provider}'",
        )

    if not base_url:
        return TestModelResponse(
            provider=body.provider,
            model=body.model,
            reachable=False,
            detail=f"Base URL for provider '{body.provider}' is not configured.",
        )

    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": body.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    logger.debug("Testing model {}/{} at {}", body.provider, body.model, url)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code < 400:
            return TestModelResponse(
                provider=body.provider,
                model=body.model,
                reachable=True,
                detail=f"HTTP {resp.status_code} — model is reachable.",
            )
        return TestModelResponse(
            provider=body.provider,
            model=body.model,
            reachable=False,
            detail=f"HTTP {resp.status_code}: {resp.text[:200]}",
        )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        return TestModelResponse(
            provider=body.provider,
            model=body.model,
            reachable=False,
            detail=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error testing {}/{}: {}", body.provider, body.model, exc)
        return TestModelResponse(
            provider=body.provider,
            model=body.model,
            reachable=False,
            detail=str(exc),
        )

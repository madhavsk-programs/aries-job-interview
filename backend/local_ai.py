"""Fast readiness checks for the local Ollama and Speaches services."""

from __future__ import annotations

import asyncio

import httpx

from config import settings


async def local_ai_status() -> dict[str, object]:
    """Report service and model readiness without making an inference call."""

    timeout = httpx.Timeout(3.0, connect=1.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        ollama_result, speech_result = await asyncio.gather(
            _ollama_status(client),
            _speech_status(client),
        )

    issues = [
        *ollama_result.pop("issues"),
        *speech_result.pop("issues"),
    ]
    return {
        "ready": not issues,
        "issues": issues,
        "ollama": ollama_result,
        "speech": speech_result,
    }


async def _ollama_status(client: httpx.AsyncClient) -> dict[str, object]:
    try:
        response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        models = {
            str(item.get("name") or "")
            for item in response.json().get("models", [])
        }
        missing = [
            model
            for model in (settings.ollama_chat_model, settings.ollama_embedding_model)
            if model not in models and f"{model}:latest" not in models
        ]
        return {
            "online": True,
            "models": sorted(models),
            "issues": [f"Ollama model not downloaded: {model}" for model in missing],
        }
    except Exception:
        return {
            "online": False,
            "models": [],
            "issues": ["Ollama is not running on port 11434"],
        }


async def _speech_status(client: httpx.AsyncClient) -> dict[str, object]:
    try:
        response = await client.get(f"{settings.speech_base_url.rstrip('/')}/models")
        response.raise_for_status()
        models = {
            str(item.get("id") or "")
            for item in response.json().get("data", [])
        }
        required = (settings.speech_stt_model, settings.speech_tts_model)
        missing = [model for model in required if model not in models]
        return {
            "online": True,
            "models": sorted(models),
            "issues": [f"Speech model not downloaded: {model}" for model in missing],
        }
    except Exception:
        return {
            "online": False,
            "models": [],
            "issues": ["Speaches is not running on port 8001"],
        }

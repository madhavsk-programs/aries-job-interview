"""Local Ollama client shared by evaluators, resume parsing and retrieval."""

from __future__ import annotations

import json
from typing import Any

import httpx

from config import settings


def _ollama_url(path: str) -> str:
    return f"{settings.ollama_base_url.rstrip('/')}{path}"


async def complete_json(
    *,
    name: str,
    schema: dict[str, Any],
    instructions: str,
    input_text: str,
    max_tokens: int = 700,
    model: str | None = None,
) -> dict[str, Any]:
    schema_text = json.dumps(schema, separators=(",", ":"))
    prompt = (
        f"Task: {name}\n\n{input_text}\n\n"
        f"Return only JSON matching this schema exactly:\n{schema_text}"
    )
    timeout = httpx.Timeout(settings.local_ai_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            _ollama_url("/api/chat"),
            json={
                "model": model or settings.ollama_chat_model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "think": False,
                "format": schema,
                "keep_alive": "60m",
                "options": {
                    "temperature": 0,
                    "num_predict": max_tokens,
                },
            },
        )
        response.raise_for_status()

    payload = response.json()
    content = str(payload.get("message", {}).get("content") or "{}").strip()
    result = json.loads(content)
    if not isinstance(result, dict):
        raise RuntimeError("Ollama returned JSON that was not an object")
    return result


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Create one fixed-size local embedding for every supplied text."""

    if not texts:
        return []
    timeout = httpx.Timeout(settings.local_ai_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(
            _ollama_url("/api/embed"),
            json={
                "model": settings.ollama_embedding_model,
                "input": texts,
                "dimensions": settings.ollama_embedding_dimensions,
                "keep_alive": "60m",
            },
        )
        response.raise_for_status()

    embeddings = [list(item) for item in response.json().get("embeddings", [])]
    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"Ollama returned {len(embeddings)} embeddings for {len(texts)} texts"
        )
    if any(len(item) != settings.ollama_embedding_dimensions for item in embeddings):
        raise RuntimeError("Ollama returned an unexpected embedding dimension")
    return embeddings

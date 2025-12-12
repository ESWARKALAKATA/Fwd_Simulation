"""Embedding helper utilities.

Current strategy:
 - Use OpenAI embedding API if OPENAI_API_KEY present.
 - Else fall back to a lightweight hash -> pseudo-vector (for development only).

Production: Replace fallback with a proper local embedding model or other provider.
"""
from __future__ import annotations
import hashlib
import math
from typing import List
import httpx
from app.config import settings


async def get_embedding(text: str) -> List[float]:
    """Return an embedding vector for input text using configured provider.

    Providers:
      - Gemini (`gemini-embedding-001`): uses Google Generative Language API.
      - OpenAI: if EMBEDDING_PROVIDER='openai'.
      - Fallback hash embedding: deterministic, low quality (development only).
    """
    text = text.strip()
    if not text:
        return [0.0] * settings.EMBEDDING_DIM

    provider = settings.EMBEDDING_PROVIDER.lower()

    if provider == "gemini" and settings.GEMINI_API_KEY:
        try:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.EMBEDDING_MODEL}:embedContent?key={settings.GEMINI_API_KEY}"
            async with httpx.AsyncClient(timeout=40) as client:
                resp = await client.post(endpoint, json={"content": {"parts": [{"text": text}]}})
            resp.raise_for_status()
            data = resp.json()
            vec = data.get("embedding", {}).get("values")
            if not vec:
                raise ValueError("Gemini embedding response missing 'embedding.values'.")
            # Gemini may return variable length; normalize to EMBEDDING_DIM if needed
            if len(vec) != settings.EMBEDDING_DIM:
                if len(vec) > settings.EMBEDDING_DIM:
                    vec = vec[: settings.EMBEDDING_DIM]
                else:
                    # pad with zeros
                    vec = vec + [0.0] * (settings.EMBEDDING_DIM - len(vec))
            return vec
        except Exception as e:
            print(f"[Embedding] Gemini error, falling back: {e}")

    if provider == "openai" and settings.OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={"input": text, "model": settings.EMBEDDING_MODEL},
                )
            resp.raise_for_status()
            data = resp.json()
            vec = data["data"][0]["embedding"]
            if len(vec) != settings.EMBEDDING_DIM:
                if len(vec) > settings.EMBEDDING_DIM:
                    vec = vec[: settings.EMBEDDING_DIM]
                else:
                    vec = vec + [0.0] * (settings.EMBEDDING_DIM - len(vec))
            return vec
        except Exception as e:
            print(f"[Embedding] OpenAI error, falling back: {e}")

    # Fallback: deterministic pseudo embedding based on SHA256 hash
    h = hashlib.sha256(text.encode("utf-8")).digest()
    needed = settings.EMBEDDING_DIM
    repeats = math.ceil(needed / len(h))
    raw = (h * repeats)[:needed]
    vec = [((b / 255.0) * 2.0) - 1.0 for b in raw]
    return vec


async def get_query_embedding(query: str) -> List[float]:
    return await get_embedding(query)

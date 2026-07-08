"""
Centralized LLM + Embedding client.

ALL agents and modules import from here.
To swap the LLM provider again in the future, only this file changes.

LLM:        Groq — openai/gpt-oss-120b
Embeddings: sentence-transformers/all-MiniLM-L6-v2 (local, no API key needed)
"""

import os
import json
import re
from functools import lru_cache
from typing import Optional

from groq import Groq, AsyncGroq
from sentence_transformers import SentenceTransformer

# ── Groq clients ──────────────────────────────────────────────
# Sync client  → used in non-async contexts (normalization, report PDF)
# Async client → used in all FastAPI route handlers
_sync_client  = Groq(api_key=os.getenv("GROQ_API_KEY"))
_async_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "openai/gpt-oss-120b"

# ── Embedding model (loaded once at startup) ──────────────────
# all-MiniLM-L6-v2: 384-dim, fast, runs on CPU, no internet after first download
@lru_cache(maxsize=1)
def _get_embed_model() -> SentenceTransformer:
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


# ─────────────────────────────────────────────────────────────
# PUBLIC FUNCTIONS
# ─────────────────────────────────────────────────────────────

def get_embedding(text: str) -> list[float]:
    """
    Embed a single string using all-MiniLM-L6-v2.
    Returns a list of 384 floats.
    Used by: rag.py for query embedding and document indexing.
    """
    model = _get_embed_model()
    vec = model.encode(text, show_progress_bar=False)
    return vec.tolist()


def complete(prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """
    Synchronous LLM completion.
    Used by: normalization.py, report.py PDF generation.
    """
    response = _sync_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def acomplete(prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """
    Async LLM completion.
    Used by: supervisor.py, judge.py, orchestrator.py, report.py
    """
    response = await _async_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def acomplete_json(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    fallback: Optional[dict] = None,
) -> dict:
    """
    Async LLM completion that always returns a dict.
    Strips markdown code fences, parses JSON, and returns fallback on any error.
    Used by: supervisor.py, judge.py (structured JSON outputs).
    """
    try:
        raw = await acomplete(prompt, temperature=temperature, max_tokens=max_tokens)
        raw = re.sub(r"```json|```", "", raw).strip()
        # Find the first { ... } block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
    except Exception as e:
        print(f"[LLM CLIENT] JSON parse failed: {e}")
        return fallback or {}


def complete_json(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    fallback: Optional[dict] = None,
) -> dict:
    """Sync version of acomplete_json. Used by normalization.py."""
    try:
        raw = complete(prompt, temperature=temperature, max_tokens=max_tokens)
        raw = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
    except Exception as e:
        print(f"[LLM CLIENT] JSON parse failed: {e}")
        return fallback or {}

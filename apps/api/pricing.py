"""Cost lookup for model_usage rows.

Prices come straight from OpenRouter's /models response (cached to
data/openrouter-models.json by main.openrouter_models()) instead of a
hand-maintained table -- OpenRouter is the source of truth and the cache
is refreshed by the same code path the admin models list already uses.
"""
from __future__ import annotations

import json

from apps.api import main


def _cached_models() -> list[dict]:
    """Read the on-disk model cache without a network call (record_usage runs on every completion)."""
    if main.MODELS_CACHE_PATH.exists():
        return json.loads(main.MODELS_CACHE_PATH.read_text(encoding="utf-8"))
    return main.openrouter_models()  # first run only: no cache yet, one live fetch to seed it


def usd_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """$ cost for one completion. Unknown model id -> 0 (never blocks on a pricing miss)."""
    for entry in _cached_models():
        if entry["id"] == model_id:
            pricing = entry.get("pricing", {})
            prompt_rate = float(pricing.get("prompt") or 0)
            completion_rate = float(pricing.get("completion") or 0)
            return round(input_tokens * prompt_rate + output_tokens * completion_rate, 6)
    return 0.0

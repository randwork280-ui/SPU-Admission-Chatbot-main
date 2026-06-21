from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {
        name: getattr(value, name)
        for name in dir(value)
        if not name.startswith("_") and not callable(getattr(value, name))
    }


def openai_usage_to_dict(usage: Any) -> Dict[str, int]:
    data = _as_dict(usage)
    if not data:
        return {}

    input_details = _as_dict(
        data.get("input_tokens_details")
        or data.get("prompt_tokens_details")
        or data.get("input_details")
    )
    output_details = _as_dict(
        data.get("output_tokens_details")
        or data.get("completion_tokens_details")
        or data.get("output_details")
    )

    input_tokens = int(data.get("input_tokens") or data.get("prompt_tokens") or 0)
    output_tokens = int(data.get("output_tokens") or data.get("completion_tokens") or 0)
    total_tokens = int(data.get("total_tokens") or input_tokens + output_tokens)
    cached_input_tokens = int(
        input_details.get("cached_tokens")
        or input_details.get("cached_input_tokens")
        or data.get("cached_tokens")
        or 0
    )

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": max(input_tokens - cached_input_tokens, 0),
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
    }


def estimate_openai_cost(
    usage: Mapping[str, int],
    input_price_per_1m: float,
    cached_input_price_per_1m: float,
    output_price_per_1m: float,
) -> Optional[Dict[str, float]]:
    if not usage or not any([input_price_per_1m, cached_input_price_per_1m, output_price_per_1m]):
        return None

    uncached_input = usage.get("uncached_input_tokens", 0)
    cached_input = usage.get("cached_input_tokens", 0)
    output = usage.get("output_tokens", 0)

    input_cost = uncached_input * input_price_per_1m / 1_000_000
    cached_input_cost = cached_input * cached_input_price_per_1m / 1_000_000
    output_cost = output * output_price_per_1m / 1_000_000

    return {
        "input_usd": round(input_cost, 8),
        "cached_input_usd": round(cached_input_cost, 8),
        "output_usd": round(output_cost, 8),
        "total_usd": round(input_cost + cached_input_cost + output_cost, 8),
    }

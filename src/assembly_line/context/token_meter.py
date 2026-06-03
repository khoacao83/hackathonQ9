from __future__ import annotations


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    if not text:
        return 0

    return max(1, int(len(text) / chars_per_token))


def token_saving(raw_context: str, optimized_context: str) -> dict:
    raw_tokens = estimate_tokens(raw_context)
    optimized_tokens = estimate_tokens(optimized_context)

    saved_tokens = max(0, raw_tokens - optimized_tokens)

    if raw_tokens == 0:
        saved_percent = 0.0
    else:
        saved_percent = round((saved_tokens / raw_tokens) * 100, 2)

    return {
        "raw_tokens": raw_tokens,
        "optimized_tokens": optimized_tokens,
        "saved_tokens": saved_tokens,
        "saved_percent": saved_percent,
    }
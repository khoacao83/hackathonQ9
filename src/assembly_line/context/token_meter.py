def estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    return len(text) // 4


def token_saving_percent(raw: str, optimized: str) -> float:
    """Return % reduction in estimated tokens after optimization."""
    raw_tokens = estimate_tokens(raw)
    if raw_tokens == 0:
        return 0.0
    opt_tokens = estimate_tokens(optimized)
    return round((1 - opt_tokens / raw_tokens) * 100, 1)

def choose_result(value: int, mode: str, fallback: int) -> int:
    if mode == "strict":
        if value > 10:
            return value
        return fallback
    if mode == "clamp":
        return max(value, 0)
    return fallback

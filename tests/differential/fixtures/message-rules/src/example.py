def inspect(payload: object) -> object:
    ranges = payload
    if not isinstance(ranges, list):
        return []
    return ranges

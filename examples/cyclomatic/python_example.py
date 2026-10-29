def route(request: dict[str, object], retries: int = 0) -> str:
    assert request
    try:
        if request.get("ready") and retries < 2:
            return "ready"
        if request.get("cached"):
            return "cached"
        return "retry" if retries else "wait"
    except (KeyError, TypeError):
        return "invalid"


def select_even(values: list[int], floor: int) -> list[int]:
    selected = [value for value in values if value >= floor and value % 2 == 0]
    match floor:
        case 0 | 1:
            return selected
        case _:
            return []

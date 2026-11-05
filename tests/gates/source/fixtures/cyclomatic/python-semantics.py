from collections.abc import Sequence


def branch_loop_exception(value: int, items: Sequence[int]) -> int:
    assert items
    try:
        total = 0
        for item in items:
            if item > 0 and value:
                total += item
            elif item == 0:
                continue
        return total if value else -1
    except (TypeError, ValueError):
        return 0


def comprehension_and_match(value: int, items: Sequence[int]) -> list[int]:
    selected = [item for item in items if item > value and item % 2 == 0]
    match value:
        case 0 | 1:
            return selected
        case _:
            return []

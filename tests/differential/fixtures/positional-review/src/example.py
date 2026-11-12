def convert(first: int, second: int, label: str) -> str:
    return f"{first} {second} {label}"


def render(position: int) -> str:
    rows: dict[str, str] = {}
    if position == 2:
        rows["caption"] = "Replace the semantic caption with a fixed description"
    return rows["caption"]

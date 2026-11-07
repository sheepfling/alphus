class Cell:
    attribute: str
    identifier: str


fixed_paragraphs: dict[str, str] = {"overview": "Updated overview"}


def source_anchor(identifier: str) -> str:
    return f"<!-- {identifier} -->"


def render(cell: Cell) -> str:
    replacement = fixed_paragraphs.get(cell.attribute)
    if replacement is not None:
        return source_anchor(cell.identifier) + replacement
    return f"| {cell.attribute} |"

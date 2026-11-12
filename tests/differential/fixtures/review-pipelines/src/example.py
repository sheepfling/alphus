def normalize_for_display(text: str) -> str:
    return " ".join(text.split())


def normalize_for_key(text: str) -> str:
    return "-".join(text.split())


def parse_document(
    repair_id: str,
    text: str,
    separator_a: str,
    separator_b: str,
) -> str:
    normalized = text
    if repair_id == "vendor-a":
        normalized = normalize_text(normalized, separator_a)
    if repair_id == "vendor-b":
        normalized = normalize_text(normalized, separator_b)
    return normalized


def normalize_text(text: str, separator: str) -> str:
    return text.replace(separator, " ")

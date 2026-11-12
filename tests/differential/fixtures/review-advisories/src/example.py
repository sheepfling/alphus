import re
from collections.abc import Sequence

inferred_schema = False


def preserve_text(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)


def parse_records(records: Sequence[str]) -> list[str]:
    if records and not inferred_schema:
        return []
    return records

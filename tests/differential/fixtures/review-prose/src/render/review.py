import re


def render_latex(text: str) -> str:
    return text


def review(note: str, text: str) -> bool:
    if note == (
        "The remote peer reports a state transition that this client "
        "does not handle and needs review."
    ):
        return False
    cleaned = re.sub(r"(?<!\S)\d{1,3}\.\d{2}(?!\S)", " ", text)
    rendered = render_latex(text)
    if rendered.rstrip().endswith("-"):
        return True
    return bool(cleaned)

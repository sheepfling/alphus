"""Render synthetic builders to check Markdown context examples independently."""

from __future__ import annotations

import re
from collections.abc import Sequence
from html.parser import HTMLParser
from urllib.parse import quote, unquote

from markdown_it import MarkdownIt

from alphus.gates.review.dynamic_markdown import dynamic_markdown_findings


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.code: list[str] = []
        self.breaks = 0
        self._cell: list[str] | None = None
        self._link_href: str | None = None
        self._link_text: list[str] = []
        self._code_text: list[str] | None = None

    def handle_starttag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
        if tag in {"td", "th"}:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self.breaks += 1
        elif tag == "a":
            self._link_href = dict(attrs).get("href")
            self._link_text = []
        elif tag == "code":
            self._code_text = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        if self._link_href is not None:
            self._link_text.append(data)
        if self._code_text is not None:
            self._code_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            self.cells.append("".join(self._cell))
            self._cell = None
        elif tag == "a" and self._link_href is not None:
            self.links.append((self._link_href, "".join(self._link_text)))
            self._link_href = None
            self._link_text = []
        elif tag == "code" and self._code_text is not None:
            self.code.append("".join(self._code_text))
            self._code_text = None


def _escape_cell(value: str) -> str:
    return (
        value.replace("|", r"\|")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _escape_label(value: str) -> str:
    return value.replace("\\", r"\\").replace("[", r"\[").replace("]", r"\]")


def _longest_backtick_run(value: str) -> int:
    runs = [len(run) for run in re.findall(r"`+", value)]
    return max(runs, default=0)


def _code_span(value: str) -> str:
    delimiter = "`" * (_longest_backtick_run(value) + 1)
    padding = " " if value.startswith(("`", " ")) or value.endswith(("`", " ")) else ""
    return f"{delimiter}{padding}{value}{padding}{delimiter}"


def _code_fence(value: str) -> str:
    delimiter = "`" * max(3, _longest_backtick_run(value) + 1)
    return f"{delimiter}\n{value}\n{delimiter}\n"


def test_synthetic_context_builders_preserve_rendered_markdown_structure() -> None:
    table = (
        "| Name | Value |\n| --- | --- |\n| API | " + _escape_cell("A|B\nC") + " |\n"
    )
    destination = quote("https://example.test/a_(b)", safe=":/?&=%#")
    link = f"[{_escape_label('API [v2]')}]({destination})"
    inline = _code_span("literal ` marker")
    fenced = _code_fence("print('ok')\n``` user text")

    rendered = (
        MarkdownIt("default", {"html": True})
        .enable("table")
        .render(f"{table}\n{link}\n{inline}\n{fenced}")
    )
    parsed = _StructureParser()
    parsed.feed(rendered)

    assert parsed.cells == ["Name", "Value", "API", "A|BC"]
    assert parsed.breaks == 1
    assert [(unquote(href), label) for href, label in parsed.links] == [
        ("https://example.test/a_(b)", "API [v2]")
    ]
    assert parsed.code == ["literal ` marker", "print('ok')\n``` user text\n"]


def test_unescaped_dynamic_table_value_changes_rendered_row_structure() -> None:
    value = "A|B\n| injected | row |"
    markdown = f"| Name | Value |\n| --- | --- |\n| API | {value} |\n"
    rendered = MarkdownIt("default").enable("table").render(markdown)
    parsed = _StructureParser()
    parsed.feed(rendered)

    # This deliberately unsafe synthetic value demonstrates the behavior the
    # source-only advisory warns about: a dynamic pipe and newline create a
    # second table row and truncate the original cell's intended content.
    assert parsed.cells == ["Name", "Value", "API", "A", "injected", "row"]


def test_unescaped_dynamic_link_label_can_inject_a_second_link() -> None:
    label = "click](https://evil.example/)! ["
    target = "https://good.example/"
    source = 'def render(label, target):\n    return f"[{label}]({target})"\n'
    findings = dynamic_markdown_findings(source, path="src/links.py")

    rendered = MarkdownIt().render(f"[{label}]({target})")
    parsed = _StructureParser()
    parsed.feed(rendered)

    assert {"link label", "link destination"} == {
        context
        for finding in findings
        for context in ("link label", "link destination")
        if context in finding.message
    }
    assert all(finding.path == "src/links.py" for finding in findings)
    assert all("does not prove invalid rendered output" in f.message for f in findings)
    assert parsed.links == [
        ("https://evil.example/", "click"),
        ("https://good.example/", ""),
    ]


def test_unescaped_dynamic_link_destination_can_inject_a_second_link() -> None:
    label = "documentation"
    target = "https://good.example/a) [click](https://evil.example"
    source = 'def render(label, target):\n    return f"[{label}]({target})"\n'
    findings = dynamic_markdown_findings(source, path="src/links.py")

    rendered = MarkdownIt().render(f"[{label}]({target})")
    parsed = _StructureParser()
    parsed.feed(rendered)

    assert len(findings) == 2
    assert any("link destination" in finding.message for finding in findings)
    assert all("does not prove invalid rendered output" in f.message for f in findings)
    assert parsed.links == [
        ("https://good.example/a", "documentation"),
        ("https://evil.example", "click"),
    ]

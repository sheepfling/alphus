"""Opt-in document-level review of repeated rhetorical headings."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from alphus.config import DocumentStylePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text

_RULE_ID = rule_tag(
    Scope.ANY, Framework.NONE, Category.STYLE, "rhetorical-heading-density"
)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("from-to", re.compile(r"^from\b.+\bto\b.+$", re.IGNORECASE)),
    (
        "one-every",
        re.compile(r"^one\b.+[.!?]\s+every\b.+$", re.IGNORECASE),
    ),
    (
        "imperative-pair",
        re.compile(
            r"^(?:see|reveal|measure|find|build|make|discover|explore|shape|turn|"
            r"connect|follow|show|know|start|choose|bring|design|create|unlock|"
            r"track)\b.+[.!?]\s+(?:see|reveal|measure|find|build|make|discover|"
            r"explore|shape|turn|connect|follow|show|know|start|choose|bring|"
            r"design|create|unlock|track)\b.+$",
            re.IGNORECASE,
        ),
    ),
    ("why-matters", re.compile(r"^why\b.+\bmatters\??$", re.IGNORECASE)),
    ("what-reveals", re.compile(r"^what\b.+\b(reveals?|shows?)\b.+$", re.IGNORECASE)),
    ("beyond", re.compile(r"^beyond\b.+$", re.IGNORECASE)),
    ("where-meets", re.compile(r"^where\b.+\bmeets\b.+$", re.IGNORECASE)),
    ("not-but", re.compile(r"^not\b.+,?\s+but\b.+$", re.IGNORECASE)),
)
_TOC_LABEL = re.compile(
    r"^\s{0,3}#{1,6}\s+(?:table of contents|contents)\s*#*\s*$", re.IGNORECASE
)
_LATEX_COMMAND = re.compile(
    r"\\(?P<name>chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?"
)
_LATEX_OPTION = re.compile(r"\s*\[[^\]]*\]")
_LATEX_IGNORED_ENVIRONMENT = re.compile(
    r"\\begin\{(?P<name>verbatim\*?|Verbatim|lstlisting|minted|comment)\}"
)
_LATEX_FORMAT_COMMAND = re.compile(r"\\(?:emph|textbf|textit|textrm|textsf)\s*")
_HTML_IGNORED_TAGS = frozenset({"nav", "script", "style", "template", "code", "pre"})


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """A source heading with its native Markdown line and hierarchy."""

    path: str
    text: str
    level: int
    line: int


class _HtmlOutlineParser(HTMLParser):
    """Collect visible text from structural headings, retaining source lines."""

    def __init__(self, path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.stack: list[tuple[str, bool]] = []
        self.heading_level: int | None = None
        self.heading_line = 0
        self.heading_parts: list[str] = []
        self.sections: list[DocumentSection] = []

    def _finish_heading(self) -> None:
        if self.heading_level is not None:
            text = " ".join("".join(self.heading_parts).split())
            if text:
                self.sections.append(
                    DocumentSection(
                        self.path, text, self.heading_level, self.heading_line
                    )
                )
        self.heading_level = None
        self.heading_parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.heading_level is not None and tag in {f"h{i}" for i in range(1, 7)}:
            self._finish_heading()
        attributes = dict(attrs)
        hidden = (
            "hidden" in attributes
            or attributes.get("aria-hidden", "").lower() == "true"
        )
        ignored = (
            bool(self.stack and self.stack[-1][1])
            or tag in _HTML_IGNORED_TAGS
            or hidden
        )
        self.stack.append((tag, ignored))
        if not ignored and len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self.heading_level = int(tag[1])
            self.heading_line = self.getpos()[0]

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.heading_level is not None and tag == f"h{self.heading_level}":
            self._finish_heading()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.heading_level is not None and self.stack and not self.stack[-1][1]:
            self.heading_parts.append(data)


def extract_html_sections(
    source: str, *, path: str = "<source>"
) -> tuple[DocumentSection, ...]:
    """Extract visible structural headings, omitting navigation and code regions."""
    parser = _HtmlOutlineParser(path)
    parser.feed(source)
    parser.close()
    parser._finish_heading()
    return tuple(parser.sections)


def extract_markdown_sections(
    source: str, *, path: str = "<source>"
) -> tuple[DocumentSection, ...]:
    """Extract ATX and setext headings, skipping front matter, fences, and TOCs."""
    lines = source.splitlines()
    sections: list[DocumentSection] = []
    in_front_matter = bool(lines and lines[0].strip() == "---")
    in_fence: tuple[str, int] | None = None
    in_toc = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if in_front_matter:
            if index and stripped in {"---", "..."}:
                in_front_matter = False
            continue
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = (marker, len(fence.group(1)))
            elif marker == in_fence[0] and len(fence.group(1)) >= in_fence[1]:
                in_fence = None
            continue
        if in_fence:
            continue
        atx = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if _TOC_LABEL.match(line):
            in_toc = True
            continue
        if in_toc:
            if stripped and not re.match(
                r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+|\[[^]]+\]\()", line
            ):
                in_toc = False
            else:
                continue
        if atx:
            heading = re.sub(r"\s+\{[^{}]*\}\s*$", "", atx.group(2).strip())
            sections.append(
                DocumentSection(path, heading, len(atx.group(1)), index + 1)
            )
            continue
        if index + 1 < len(lines):
            underline = re.match(r"^\s{0,3}(=+|-+)\s*$", lines[index + 1])
            if underline and stripped:
                sections.append(
                    DocumentSection(
                        path,
                        stripped,
                        1 if underline.group(1).startswith("=") else 2,
                        index + 1,
                    )
                )
    return tuple(sections)


def _mask_latex_comments_and_verbatim(source: str) -> str:
    """Blank comments and literal environments while preserving source offsets."""
    chars = list(source)
    index = 0
    while index < len(source):
        environment = _LATEX_IGNORED_ENVIRONMENT.match(source, index)
        if environment is not None:
            closing = f"\\end{{{environment.group('name')}}}"
            end = source.find(closing, environment.end())
            stop = len(source) if end < 0 else end + len(closing)
            for offset in range(index, stop):
                if chars[offset] != "\n":
                    chars[offset] = " "
            index = stop
            continue
        if source[index] == "%":
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and source[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                end = source.find("\n", index)
                stop = len(source) if end < 0 else end
                for offset in range(index, stop):
                    chars[offset] = " "
                index = stop
                continue
        index += 1
    return "".join(chars)


def _balanced_brace_end(source: str, opening: int) -> int | None:
    """Return the matching close brace, respecting escaped braces."""
    depth = 0
    for index in range(opening, len(source)):
        char = source[index]
        if char == "{" and not _is_escaped(source, index):
            depth += 1
        elif char == "}" and not _is_escaped(source, index):
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_escaped(source: str, index: int) -> bool:
    """Tell whether a character is preceded by an odd run of backslashes."""
    preceding = index - 1
    count = 0
    while preceding >= 0 and source[preceding] == "\\":
        count += 1
        preceding -= 1
    return count % 2 == 1


def extract_latex_sections(
    source: str, *, path: str = "<source>"
) -> tuple[DocumentSection, ...]:
    """Extract conventional LaTeX section titles without compiling the document.

    Unclosed titles and custom sectioning macros are left unexamined. Comments
    and literal ``verbatim``, ``Verbatim``, ``lstlisting``, ``minted`` and
    ``comment`` environments do not contribute headings.
    """
    masked = _mask_latex_comments_and_verbatim(source)
    sections: list[DocumentSection] = []
    for command in _LATEX_COMMAND.finditer(masked):
        if _is_escaped(masked, command.start()):
            continue
        cursor = command.end()
        option = _LATEX_OPTION.match(masked, cursor)
        if option is not None:
            cursor = option.end()
        while cursor < len(masked) and masked[cursor].isspace():
            cursor += 1
        if cursor >= len(masked) or masked[cursor] != "{":
            continue
        end = _balanced_brace_end(masked, cursor)
        if end is None:
            continue
        title = masked[cursor + 1 : end].strip()
        title = _LATEX_FORMAT_COMMAND.sub("", title).replace("{", "").replace("}", "")
        if not title or "\\" in title:
            # A macro in the title may expand to unknown text; don't treat it
            # as evidence of a clean or rhetorical heading.
            continue
        level = {
            "chapter": 1,
            "section": 2,
            "subsection": 3,
            "subsubsection": 4,
            "paragraph": 5,
            "subparagraph": 6,
        }[command.group("name")]
        sections.append(
            DocumentSection(
                path,
                title,
                level,
                masked.count("\n", 0, command.start()) + 1,
            )
        )
    return tuple(sections)


def rhetorical_heading_findings(
    sections: Iterable[DocumentSection], policy: DocumentStylePolicy
) -> list[Finding]:
    """Report only repeated template families in sufficiently large outlines."""
    headings = tuple(sections)
    if len(headings) < policy.minimum_headings:
        return []
    families: dict[str, list[DocumentSection]] = {}
    for section in headings:
        text = re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s+", "", section.text).strip()
        for name, pattern in _PATTERNS:
            if pattern.match(text):
                families.setdefault(name, []).append(section)
                break
    findings: list[Finding] = []
    for family, matches in sorted(families.items()):
        if (
            len(matches) < policy.minimum_family_matches
            or len(matches) / len(headings) < policy.minimum_family_density
        ):
            continue
        examples = "; ".join(
            f'"{item.text}" (line {item.line})' for item in matches[:3]
        )
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=matches[0].path,
                line=matches[0].line,
                severity=policy.severity,
                message=(
                    f"Repeated rhetorical heading pattern '{family}' appears "
                    f"{len(matches)} times among {len(headings)} headings "
                    f"({len(matches) / len(headings):.0%}): {examples}. "
                    "Review whether these headings help readers identify section "
                    "content; a single creative heading is not flagged. Guidance: "
                    "docs/writing/technical-headings.md"
                ),
            )
        )
    return findings


def check_document_style(
    root: Path, paths: Iterable[Path], policy: DocumentStylePolicy
) -> list[Finding]:
    """Review each selected document using its bounded format-specific extractor."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(set(paths)):
        name = relative.as_posix()
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        if relative.suffix.lower() == ".html" and (
            name.lower().endswith(".min.html")
            or bool(
                {part.lower() for part in relative.parts}
                & {"dist", "build", "generated"}
            )
        ):
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    severity="info",
                    message=(
                        "HTML heading analysis skipped a likely generated or "
                        "minified file; explicitly exclude or rename it if it is "
                        "source intended for review."
                    ),
                )
            )
            continue
        source = read_utf8_text(checkout / relative)
        extractor = (
            extract_latex_sections
            if relative.suffix.lower() == ".tex"
            else extract_html_sections
            if relative.suffix.lower() == ".html"
            else extract_markdown_sections
        )
        findings.extend(
            rhetorical_heading_findings(extractor(source, path=name), policy)
        )
        if relative.suffix.lower() == ".tex":
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    severity="info",
                    message=(
                        "LaTeX heading analysis covers conventional sectioning "
                        "commands only. Custom sectioning macros, unresolved title "
                        "macros, and unsupported environments are unknown; this is "
                        "not a complete outline pass."
                    ),
                )
            )
        elif relative.suffix.lower() == ".html":
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    severity="info",
                    message=(
                        "HTML heading analysis uses source h1–h6 text and omits nav, "
                        "script, style, template, code, pre, hidden, and aria-hidden "
                        "regions. It does not resolve templates or generated content."
                    ),
                )
            )
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))

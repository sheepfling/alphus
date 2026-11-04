"""Opt-in document-level review of repeated rhetorical headings."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from markdown_it import MarkdownIt

from alphus.config import DocumentStylePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path
from alphus.support.source_text import read_utf8_text

ALPHUS_MORPHOLOGY = (
    ("selector", "document-style"),
    ("concern", "rhetorical-heading-style"),
    ("claim_kind", "style-preference"),
    ("claim", "Selected documents may repeat configured rhetorical heading patterns."),
    ("mechanisms", ("exact-rule",)),
    ("inspected_scope", ("selected-document-headings", "document-structure")),
    ("languages_formats", ("markdown", "latex", "html", "docx", "pptx")),
    ("evidence_kinds", ("document-heading", "format-specific-location")),
    ("evaluation_maturity", "synthetic-only"),
    ("finding_tag_complaints", ("rhetorical-heading-density",)),
)


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
_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_MAX_PACKAGE_XML_BYTES = 32 * 1024 * 1024


def _read_package_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    """Read a bounded Office XML part without DTD or entity declarations."""
    info = archive.getinfo(name)
    if info.file_size > _MAX_PACKAGE_XML_BYTES:
        raise ValueError(f"Office XML part exceeds {_MAX_PACKAGE_XML_BYTES} bytes")
    content = archive.read(name)
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("Office XML DTD and entity declarations are unsupported")
    return ET.fromstring(content)


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """A source heading with its native Markdown line and hierarchy."""

    path: str
    text: str
    level: int
    line: int
    position: str | None = None


def _section_location(section: DocumentSection) -> str:
    return section.position or f"line {section.line}"


def _word_style_levels(archive: zipfile.ZipFile) -> dict[str, int]:
    """Resolve paragraph outline levels through DOCX style inheritance."""
    try:
        styles = _read_package_xml(archive, "word/styles.xml")
    except KeyError:
        return {}
    definitions: dict[str, tuple[str | None, int | None]] = {}
    for style in styles.findall(f"{{{_W_NS}}}style"):
        style_id = style.get(f"{{{_W_NS}}}styleId")
        if style_id:
            based_on = style.find(f"{{{_W_NS}}}basedOn")
            outline = style.find(f"{{{_W_NS}}}pPr/{{{_W_NS}}}outlineLvl")
            level = None
            if outline is not None:
                try:
                    level = int(outline.get(f"{{{_W_NS}}}val", "-1")) + 1
                except ValueError:
                    pass
            definitions[style_id] = (
                based_on.get(f"{{{_W_NS}}}val") if based_on is not None else None,
                level,
            )

    resolved: dict[str, int] = {}

    def resolve(style_id: str, visiting: frozenset[str] = frozenset()) -> int | None:
        if style_id in resolved:
            return resolved[style_id]
        if style_id in visiting:
            return None
        definition = definitions.get(style_id)
        if definition is not None:
            parent, level = definition
            if level is not None:
                resolved[style_id] = level
                return level
            if parent:
                inherited = resolve(parent, visiting | {style_id})
                if inherited is not None:
                    resolved[style_id] = inherited
                    return inherited
        if style_id.lower().startswith("heading"):
            try:
                return int(style_id[7:])
            except ValueError:
                return None
        return None

    return {
        style_id: level
        for style_id in definitions
        if (level := resolve(style_id)) is not None
    }


def extract_docx_sections(
    path: Path, *, display_path: str
) -> tuple[DocumentSection, ...]:
    """Extract DOCX paragraphs styled as headings or assigned an outline level."""
    with zipfile.ZipFile(path) as archive:
        document = _read_package_xml(archive, "word/document.xml")
        custom_levels = _word_style_levels(archive)
        sections: list[DocumentSection] = []
        paragraph_number = 0
        for paragraph in document.iter(f"{{{_W_NS}}}p"):
            paragraph_number += 1
            properties = paragraph.find(f"{{{_W_NS}}}pPr")
            style_id = None
            level = None
            if properties is not None:
                style = properties.find(f"{{{_W_NS}}}pStyle")
                if style is not None:
                    style_id = style.get(f"{{{_W_NS}}}val")
                outline = properties.find(f"{{{_W_NS}}}outlineLvl")
                if outline is not None:
                    try:
                        level = int(outline.get(f"{{{_W_NS}}}val", "-1")) + 1
                    except ValueError:
                        pass
            if level is None and style_id:
                level = custom_levels.get(style_id)
                if level is None and style_id.lower().startswith("heading"):
                    try:
                        level = int(style_id[7:])
                    except ValueError:
                        pass
            if level is None or not 1 <= level <= 6:
                continue
            text = "".join(node.text or "" for node in paragraph.iter(f"{{{_W_NS}}}t"))
            text = " ".join(text.split())
            if text:
                sections.append(
                    DocumentSection(
                        display_path,
                        text,
                        level,
                        paragraph_number,
                        position=f"paragraph {paragraph_number}",
                    )
                )
    return tuple(sections)


def extract_pptx_sections(
    path: Path, *, display_path: str
) -> tuple[DocumentSection, ...]:
    """Extract text from slide title placeholders in presentation order."""
    with zipfile.ZipFile(path) as archive:
        presentation = _read_package_xml(archive, "ppt/presentation.xml")
        relationships = _read_package_xml(archive, "ppt/_rels/presentation.xml.rels")
        targets = {
            relation.get("Id"): relation.get("Target") for relation in relationships
        }
        sections: list[DocumentSection] = []
        archive_paths = frozenset(archive.namelist())
        slide_ids = presentation.findall(f".//{{{_P_NS}}}sldId")
        for slide_number, slide_id in enumerate(slide_ids, start=1):
            target = targets.get(slide_id.get(f"{{{_R_NS}}}id"))
            if not target:
                continue
            target_path = PurePosixPath(target)
            slide_path = (
                PurePosixPath(*target_path.parts[1:])
                if target_path.is_absolute()
                else PurePosixPath("ppt", target_path)
            )
            if ".." in slide_path.parts or slide_path.as_posix() not in archive_paths:
                continue
            slide = _read_package_xml(archive, slide_path.as_posix())
            for shape in slide.findall(f".//{{{_P_NS}}}sp"):
                placeholder = shape.find(
                    f"{{{_P_NS}}}nvSpPr/{{{_P_NS}}}nvPr/{{{_P_NS}}}ph"
                )
                if placeholder is None or placeholder.get("type", "") not in {
                    "title",
                    "ctrTitle",
                }:
                    continue
                text_body = shape.find(f"{{{_P_NS}}}txBody")
                paragraphs: list[str] = []
                if text_body is not None:
                    for paragraph in text_body.findall(f".//{{{_A_NS}}}p"):
                        parts: list[str] = []
                        for node in paragraph.iter():
                            if node.tag == f"{{{_A_NS}}}t":
                                parts.append(node.text or "")
                            elif node.tag == f"{{{_A_NS}}}br":
                                parts.append(" ")
                        paragraphs.append("".join(parts))
                text = " ".join(" ".join(paragraphs).split())
                if text:
                    sections.append(
                        DocumentSection(
                            display_path,
                            text,
                            1,
                            slide_number,
                            position=f"slide {slide_number}",
                        )
                    )
                    break
    return tuple(sections)


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

    def finish(self) -> None:
        """Finish any heading left open when parsing ends."""
        self._finish_heading()

    def handle_starttag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
        if self.heading_level is not None and tag in {f"h{i}" for i in range(1, 7)}:
            self._finish_heading()
        attributes = dict(attrs)
        aria_hidden = attributes.get("aria-hidden")
        hidden = "hidden" in attributes or (
            aria_hidden is not None and aria_hidden.lower() == "true"
        )
        ignored = (
            bool(self.stack and self.stack[-1][1])
            or tag in _HTML_IGNORED_TAGS
            or hidden
        )
        if tag not in _HTML_VOID_TAGS:
            self.stack.append((tag, ignored))
        if not ignored and len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self.heading_level = int(tag[1])
            self.heading_line = self.getpos()[0]

    def handle_startendtag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
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
    parser.finish()
    return tuple(parser.sections)


def extract_markdown_sections(
    source: str, *, path: str = "<source>"
) -> tuple[DocumentSection, ...]:
    """Extract ATX and setext headings, skipping front matter, fences, and TOCs."""
    lines = source.splitlines()
    sections: list[DocumentSection] = []
    in_front_matter = bool(lines and lines[0].strip() == "---")
    in_fence: tuple[str, int] | None = None
    in_html_comment = False
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
        if in_html_comment:
            closing = line.find("-->")
            if closing < 0:
                continue
            line = line[closing + 3 :]
            in_html_comment = False
        while "<!--" in line:
            opening = line.find("<!--")
            closing = line.find("-->", opening + 4)
            if closing < 0:
                line = line[:opening]
                in_html_comment = True
                break
            line = line[:opening] + line[closing + 3 :]
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
            heading = _markdown_visible_inline_text(heading)
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
                        _markdown_visible_inline_text(stripped),
                        1 if underline.group(1).startswith("=") else 2,
                        index + 1,
                    )
                )
    return tuple(sections)


def _markdown_visible_inline_text(source: str) -> str:
    """Return displayed inline text, excluding Markdown formatting syntax."""
    tokens = MarkdownIt("commonmark").parseInline(source)
    if not tokens or tokens[0].children is None:
        return " ".join(source.split())
    parts: list[str] = []
    for token in tokens[0].children:
        if token.type in {"text", "code_inline"}:
            parts.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
        elif token.type == "image" and token.children:
            parts.extend(
                child.content
                for child in token.children
                if child.type in {"text", "code_inline"}
            )
    return " ".join("".join(parts).split())


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
    suppressed = {(item.path, item.heading) for item in policy.heading_suppressions}
    headings = tuple(
        section
        for section in sections
        if (section.path, section.text) not in suppressed
    )
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
            f'"{item.text}" ({_section_location(item)})' for item in matches[:3]
        )
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=matches[0].path,
                line=None if matches[0].position else matches[0].line,
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
    inventory = set(paths)
    inventory_names = {item.as_posix() for item in inventory}
    invalid_required: set[str] = set()
    for required in policy.required_paths:
        if any(matches_path(required, pattern) for pattern in policy.exclude):
            invalid_required.add(required)
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=required,
                    severity="error",
                    message=(
                        "Required document was excluded by document-style policy; "
                        "remove the exclusion or the required-path declaration."
                    ),
                )
            )
        elif required not in inventory_names:
            invalid_required.add(required)
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=required,
                    severity="error",
                    message=(
                        "Required document was not present in the selected repository "
                        "inventory; check that the artifact exists, is not ignored, "
                        "and is included by the file policy."
                    ),
                )
            )
        else:
            try:
                required_file = (checkout / required).resolve(strict=True)
                required_file.relative_to(checkout)
            except (OSError, ValueError):
                invalid_required.add(required)
                findings.append(
                    Finding(
                        rule_id=_RULE_ID,
                        path=required,
                        severity="error",
                        message=(
                            "Required document is missing or resolves outside the "
                            "repository root."
                        ),
                    )
                )
            else:
                if not required_file.is_file():
                    invalid_required.add(required)
                    findings.append(
                        Finding(
                            rule_id=_RULE_ID,
                            path=required,
                            severity="error",
                            message="Required document is not a regular file.",
                        )
                    )

    eligible = 0
    for relative in sorted(inventory):
        name = relative.as_posix()
        if name in invalid_required:
            continue
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
        eligible += 1
        suffix = relative.suffix.lower()
        if suffix in {".docx", ".pptx"}:
            try:
                sections = (
                    extract_docx_sections(checkout / relative, display_path=name)
                    if suffix == ".docx"
                    else extract_pptx_sections(checkout / relative, display_path=name)
                )
            except (
                OSError,
                KeyError,
                ValueError,
                ET.ParseError,
                zipfile.BadZipFile,
            ) as error:
                findings.append(
                    Finding(
                        rule_id=_RULE_ID,
                        path=name,
                        severity=policy.severity,
                        message=(
                            f"Document outline was not evaluated because the {suffix[1:].upper()} "
                            f"package could not be read: {type(error).__name__}."
                        ),
                    )
                )
                continue
            findings.extend(rhetorical_heading_findings(sections, policy))
            limitations = (
                "DOCX extraction uses paragraph heading styles and outline levels; "
                "custom structures without those markers are unknown."
                if suffix == ".docx"
                else "PPTX extraction uses title and centered-title placeholders only; "
                "custom layouts without those placeholders and supporting-content "
                "context are unknown."
            )
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    severity="info",
                    message=(
                        f"{limitations} Titles are anchored by paragraph or slide "
                        "number; no content is generated or rewritten."
                    ),
                )
            )
            continue
        try:
            source = read_utf8_text(checkout / relative)
        except (OSError, UnicodeError) as error:
            findings.append(
                Finding(
                    rule_id=_RULE_ID,
                    path=name,
                    severity="error",
                    message=(
                        "Document outline was not evaluated because the source "
                        f"could not be read as UTF-8: {type(error).__name__}."
                    ),
                )
            )
            continue
        extractor = (
            extract_latex_sections
            if suffix == ".tex"
            else extract_html_sections
            if suffix == ".html"
            else extract_markdown_sections
        )
        findings.extend(
            rhetorical_heading_findings(extractor(source, path=name), policy)
        )
        if suffix == ".tex":
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
        elif suffix == ".html":
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
    if eligible == 0 and not findings:
        findings.append(
            Finding(
                rule_id=_RULE_ID,
                path=".",
                severity="info",
                message=(
                    "Document style was not evaluated because no eligible document "
                    "was selected; check the file inventory, configured extensions, "
                    "and exclusions."
                ),
            )
        )
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))

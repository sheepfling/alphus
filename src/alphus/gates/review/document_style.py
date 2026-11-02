"""Opt-in document-level review of repeated rhetorical headings."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from alphus.config import DocumentStylePolicy
from alphus.contracts.findings import Finding
from alphus.contracts.rule_tags import Category, Framework, Scope, rule_tag
from alphus.support.inventory import matches_path

_RULE_ID = rule_tag(
    Scope.ANY, Framework.NONE, Category.STYLE, "rhetorical-heading-density"
)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("from-to", re.compile(r"^from\b.+\bto\b.+$", re.IGNORECASE)),
    ("why-matters", re.compile(r"^why\b.+\bmatters\??$", re.IGNORECASE)),
    ("what-reveals", re.compile(r"^what\b.+\b(reveals?|shows?)\b.+$", re.IGNORECASE)),
    ("beyond", re.compile(r"^beyond\b.+$", re.IGNORECASE)),
    ("where-meets", re.compile(r"^where\b.+\bmeets\b.+$", re.IGNORECASE)),
    ("not-but", re.compile(r"^not\b.+,?\s+but\b.+$", re.IGNORECASE)),
)
_TOC_LABEL = re.compile(
    r"^\s{0,3}#{1,6}\s+(?:table of contents|contents)\s*#*\s*$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """A source heading with its native Markdown line and hierarchy."""

    path: str
    text: str
    level: int
    line: int


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
            sections.append(
                DocumentSection(
                    path, atx.group(2).strip(), len(atx.group(1)), index + 1
                )
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
                    f"Repeated rhetorical heading pattern '{family}' appears {len(matches)} times among {len(headings)} headings ({len(matches) / len(headings):.0%}): {examples}. Review whether these headings help readers identify section content; a single creative heading is not flagged. Guidance: docs/writing/technical-headings.md"
                ),
            )
        )
    return findings


def check_document_style(
    root: Path, paths: Iterable[Path], policy: DocumentStylePolicy
) -> list[Finding]:
    """Review selected Markdown/MDX files independently as whole documents."""
    checkout = root.resolve(strict=True)
    findings: list[Finding] = []
    for relative in sorted(set(paths)):
        name = relative.as_posix()
        if relative.suffix.lower() not in policy.extensions or any(
            matches_path(name, pattern) for pattern in policy.exclude
        ):
            continue
        source = (checkout / relative).read_text(encoding="utf-8")
        findings.extend(
            rhetorical_heading_findings(
                extract_markdown_sections(source, path=name), policy
            )
        )
    return sorted(findings, key=lambda item: (item.path, item.line or 0, item.message))

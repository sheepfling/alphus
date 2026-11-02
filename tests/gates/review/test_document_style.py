"""Regression tests for opt-in document heading review."""

from pathlib import Path

from alphus.config import load_config
from alphus.gates.review.document_style import (
    DocumentSection,
    check_document_style,
    extract_markdown_sections,
    rhetorical_heading_findings,
)
from alphus.policy.review import DocumentStylePolicy


def test_markdown_extraction_preserves_lines_and_skips_front_matter_fences_and_toc() -> (
    None
):
    source = """---
title: Hidden
---
# Table of Contents
- [Hidden section](#hidden-section)

# Visible section
```md
# Code sample
```
Setext title
------------
"""
    assert [
        (section.text, section.level, section.line)
        for section in extract_markdown_sections(source)
    ] == [
        ("Visible section", 1, 7),
        ("Setext title", 2, 11),
    ]


def test_repeated_template_advisory_requires_document_level_density() -> None:
    sections = tuple(
        DocumentSection("report.md", title, 2, line)
        for line, title in enumerate(
            (
                "From Data to Results",
                "From Inputs to Models",
                "Methods",
                "Results",
                "Limitations",
                "Appendix",
            ),
            1,
        )
    )
    findings = rhetorical_heading_findings(
        sections, DocumentStylePolicy(minimum_headings=6)
    )
    assert len(findings) == 1
    assert findings[0].line == 1
    assert "2 times among 6 headings" in findings[0].message
    assert "single creative heading is not flagged" in findings[0].message


def test_isolated_creative_heading_and_marketing_exclusion_do_not_report(
    tmp_path: Path,
) -> None:
    document = tmp_path / "slick.md"
    document.write_text(
        "# See the Heat. Reveal the Change.\n\n# About\n\n# Contact\n\n# Details\n",
        encoding="utf-8",
    )
    assert (
        check_document_style(
            tmp_path,
            [document.relative_to(tmp_path)],
            DocumentStylePolicy(minimum_headings=3),
        )
        == []
    )


def test_sample_profile_selects_opt_in_document_style_rule() -> None:
    config = load_config(Path("examples/markdown/document-review.toml"))
    plan = config.orchestration.resolve_profile("document-review")
    assert plan is not None
    assert plan.steps == ("Document style",)

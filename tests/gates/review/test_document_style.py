"""Regression tests for opt-in document heading review."""

from pathlib import Path

from alphus.config import load_config
from alphus.gates.review.document_style import (
    DocumentSection,
    check_document_style,
    extract_latex_sections,
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


def test_markdown_heading_attributes_and_unicode_keep_visible_title() -> None:
    sections = extract_markdown_sections("# Δ Geometry {#geometry .index}\n")
    assert [(section.text, section.line) for section in sections] == [("Δ Geometry", 1)]


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


def test_repeated_paired_imperatives_use_density_and_one_every_families() -> None:
    sections = tuple(
        DocumentSection("report.md", title, 2, line)
        for line, title in enumerate(
            (
                "See the Heat. Reveal the Change.",
                "Measure the Shift. Find the Cause.",
                "One dashboard. Every market.",
                "One profile. Every channel.",
                "Inputs",
                "Methods",
                "Results",
                "Limitations",
            ),
            1,
        )
    )
    findings = rhetorical_heading_findings(
        sections, DocumentStylePolicy(minimum_headings=8)
    )
    assert {
        finding.message.split("pattern '")[1].split("'")[0] for finding in findings
    } == {
        "imperative-pair",
        "one-every",
    }


def test_latex_extraction_preserves_heading_lines_and_skips_comments_and_verbatim() -> (
    None
):
    source = r"""% \section{Commented out}
\begin{verbatim}
\section{Example code}
\end{verbatim}
\section[Short title]{From Inputs to Outputs}
\subsection{Model \emph{Inputs}}
\section{An unsupported \customtitle{macro}}
"""
    sections = extract_latex_sections(source, path="paper.tex")
    assert [(section.text, section.level, section.line) for section in sections] == [
        ("From Inputs to Outputs", 2, 5),
        ("Model Inputs", 3, 6),
    ]


def test_latex_escaped_section_command_is_not_an_outline_heading() -> None:
    source = r"""\texttt{\\section{example}}
\section{Methods}
"""
    sections = extract_latex_sections(source)
    assert [(section.text, section.line) for section in sections] == [("Methods", 2)]


def test_latex_review_requires_repeated_headings_and_respects_exclusions(
    tmp_path: Path,
) -> None:
    document = tmp_path / "paper.tex"
    document.write_text(
        "\\chapter{From Data to Results}\n"
        "\\section{From Inputs to Methods}\n"
        "\\section{Results}\n"
        "\\section{Limitations}\n",
        encoding="utf-8",
    )
    policy = DocumentStylePolicy(
        extensions=(".tex",), exclude=("archive/**",), minimum_headings=4
    )
    findings = check_document_style(tmp_path, [Path("paper.tex")], policy)
    assert len(findings) == 2
    assert any(
        finding.path == "paper.tex" and finding.line == 1 for finding in findings
    )
    assert any(
        finding.line is None and "not a complete outline pass" in finding.message
        for finding in findings
    )


def test_tex_file_with_no_conventional_headings_is_still_marked_partial(
    tmp_path: Path,
) -> None:
    (tmp_path / "paper.tex").write_text(
        r"\documentclass{article}" + "\n", encoding="utf-8"
    )
    findings = check_document_style(
        tmp_path,
        [Path("paper.tex")],
        DocumentStylePolicy(extensions=(".tex",), minimum_headings=3),
    )
    assert len(findings) == 1
    assert "unknown" in findings[0].message


def test_consumer_can_exclude_a_slogan_dense_marketing_document(tmp_path: Path) -> None:
    document = tmp_path / "marketing" / "slick.md"
    document.parent.mkdir()
    document.write_text(
        "# See the Heat. Reveal the Change.\n\n"
        "# Measure the Shift. Find the Cause.\n\n"
        "# Build the Story. Shape the Future.\n",
        encoding="utf-8",
    )
    assert (
        check_document_style(
            tmp_path,
            [document.relative_to(tmp_path)],
            DocumentStylePolicy(
                exclude=("marketing/**",),
                minimum_headings=3,
                minimum_family_density=0.5,
            ),
        )
        == []
    )


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

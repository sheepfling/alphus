"""Regression tests for opt-in document heading review."""

from pathlib import Path
from zipfile import ZipFile

from alphus.config import load_config
from alphus.gates.review.document_style import (
    DocumentSection,
    check_document_style,
    extract_docx_sections,
    extract_html_sections,
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


def test_html_extraction_keeps_structural_visible_headings_and_skips_chrome() -> None:
    source = """<nav><h2>From Nav to Noise</h2></nav>
<main>
<h1>From Inputs to Models</h1>
<h2>From Data to Results</h2>
<h3>Methods <code>From Code to Noise</code></h3>
<h2 aria-hidden="true">From Hidden to Noise</h2>
<script><h2>From Script to Noise</h2></script>
</main>
"""

    assert [
        (section.text, section.level, section.line)
        for section in extract_html_sections(source, path="report.html")
    ] == [
        ("From Inputs to Models", 1, 3),
        ("From Data to Results", 2, 4),
        ("Methods", 3, 5),
    ]


def test_html_document_review_reports_density_and_declares_limits(
    tmp_path: Path,
) -> None:
    document = tmp_path / "report.html"
    document.write_text(
        "<main><h1>From Inputs to Models</h1>\n"
        "<h2>From Data to Results</h2>\n"
        "<h2>Methods</h2>\n<h2>Limitations</h2></main>",
        encoding="utf-8",
    )

    findings = check_document_style(
        tmp_path,
        [Path("report.html")],
        DocumentStylePolicy(extensions=(".html",), minimum_headings=4),
    )

    assert len(findings) == 2
    density = next(finding for finding in findings if finding.line is not None)
    coverage = next(finding for finding in findings if finding.line is None)
    assert density.line == 1
    assert "2 times among 4 headings" in density.message
    assert "does not resolve templates" in coverage.message


def test_html_review_skips_likely_generated_and_minified_inputs(tmp_path: Path) -> None:
    generated = tmp_path / "dist" / "bundle.html"
    minified = tmp_path / "app.min.html"
    generated.parent.mkdir()
    generated.write_text("<h1>From A to B</h1>", encoding="utf-8")
    minified.write_text("<h1>From C to D</h1>", encoding="utf-8")

    findings = check_document_style(
        tmp_path,
        [Path("dist/bundle.html"), Path("app.min.html")],
        DocumentStylePolicy(extensions=(".html",)),
    )

    assert len(findings) == 2
    assert all(
        "skipped a likely generated or minified file" in item.message
        for item in findings
    )


def test_docx_headings_use_structural_styles_and_paragraph_anchors(
    tmp_path: Path,
) -> None:
    document = tmp_path / "report.docx"
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs = [
        "<w:p><w:r><w:t>Preface</w:t></w:r></w:p>",
        (
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            "<w:r><w:t>From Inputs to Models</w:t></w:r></w:p>"
        ),
        (
            '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
            "<w:r><w:t>From Data to Results</w:t></w:r></w:p>"
        ),
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Methods</w:t></w:r></w:p>',
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Limitations</w:t></w:r></w:p>',
    ]
    with ZipFile(document, "w") as archive:
        archive.writestr(
            "word/styles.xml",
            f'<w:styles xmlns:w="{word}"><w:style w:type="paragraph" '
            'w:styleId="CustomOutline"><w:pPr><w:outlineLvl w:val="2"/>'
            "</w:pPr></w:style></w:styles>",
        )
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{word}"><w:body>{"".join(paragraphs)}'
            '<w:p><w:pPr><w:pStyle w:val="CustomOutline"/></w:pPr>'
            "<w:r><w:t>Custom styled content</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )

    sections = extract_docx_sections(document, display_path="report.docx")
    assert (sections[-1].text, sections[-1].level) == ("Custom styled content", 3)

    findings = check_document_style(
        tmp_path,
        [Path("report.docx")],
        DocumentStylePolicy(extensions=(".docx",), minimum_headings=4),
    )

    density = next(
        finding
        for finding in findings
        if finding.line is None and "rhetorical" in finding.message
    )
    assert "paragraph 2" in density.message
    assert any(
        "DOCX extraction uses paragraph heading styles" in finding.message
        for finding in findings
    )


def test_pptx_title_placeholders_are_anchored_by_slide(tmp_path: Path) -> None:
    document = tmp_path / "deck.pptx"
    presentation = "http://schemas.openxmlformats.org/presentationml/2006/main"
    drawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    slides = []
    for index, title in enumerate(
        ("From Inputs to Models", "From Data to Results", "Methods", "Limitations"),
        start=1,
    ):
        slides.append(
            (
                f"ppt/slides/slide{index}.xml",
                (
                    f'<p:sld xmlns:p="{presentation}" xmlns:a="{drawing}"><p:spTree>'
                    '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                    f"<p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody>"
                    "</p:sp></p:spTree></p:sld>"
                ),
            )
        )
    with ZipFile(document, "w") as archive:
        archive.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{presentation}" xmlns:r="{rel}"><p:sldIdLst>'
            + "".join(f'<p:sldId id="{i}" r:id="rId{i}"/>' for i in range(1, 5))
            + "</p:sldIdLst></p:presentation>",
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{i}" Target="slides/slide{i}.xml" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"/>'
                for i in range(1, 5)
            )
            + "</Relationships>",
        )
        for path, xml in slides:
            archive.writestr(path, xml)

    findings = check_document_style(
        tmp_path,
        [Path("deck.pptx")],
        DocumentStylePolicy(extensions=(".pptx",), minimum_headings=4),
    )

    density = next(
        finding
        for finding in findings
        if finding.line is None and "rhetorical" in finding.message
    )
    assert "slide 1" in density.message
    assert any(
        "title and centered-title placeholders only" in finding.message
        for finding in findings
    )


def test_corrupt_office_artifact_is_reported_as_not_evaluated(tmp_path: Path) -> None:
    artifact = tmp_path / "broken.docx"
    artifact.write_bytes(b"not a zip package")

    findings = check_document_style(
        tmp_path,
        [Path("broken.docx")],
        DocumentStylePolicy(extensions=(".docx",)),
    )

    assert len(findings) == 1
    assert "could not be read" in findings[0].message


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


def test_evidence_backed_presentation_titles_are_not_rhetorical_templates() -> None:
    titles = (
        "Adding observer geometry reduced median error by 32%",
        "The selected solver converged in all ten trials",
        "Residuals stayed within the stated tolerance",
        "Caching reduced parse time from 4.2 seconds to 0.8 seconds",
    )
    sections = tuple(
        DocumentSection("deck.md", title, 1, index)
        for index, title in enumerate(titles, start=1)
    )

    assert (
        rhetorical_heading_findings(sections, DocumentStylePolicy(minimum_headings=4))
        == []
    )


def test_sample_profile_selects_opt_in_document_style_rule() -> None:
    config = load_config(Path("examples/markdown/document-review.toml"))
    plan = config.orchestration.resolve_profile("document-review")
    assert plan is not None
    assert plan.steps == ("Document style",)

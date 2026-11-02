# Technical heading review guidance

Rule `alphus/any/none/style/rhetorical-heading-density` reports repeated
rhetorical templates in a document outline. It is a prompt for human review,
not a claim that a heading is wrong. The opt-in review currently extracts
Markdown/MDX ATX and setext headings, conventional LaTeX sectioning commands
(`chapter`, `section`, `subsection`, and related levels), and visible source HTML
`h1`–`h6` elements. It skips Markdown front matter, fences and TOC lists; LaTeX
comments and common literal environments (`verbatim`, `Verbatim`, `lstlisting`,
`minted`, and `comment`); and HTML navigation, scripts, styles, templates, code,
preformatted, hidden, and `aria-hidden` regions. HTML templates and generated
content are not resolved. Explicitly selected DOCX files use paragraph heading
styles and outline levels; PPTX files use title and centered-title placeholders.
Those formats are read from bounded Office XML package parts without executing
macros or installing optional parsers. Custom DOCX structures and custom PPTX
layouts without title placeholders are not fully covered. Locations are reported
as paragraph or slide numbers rather than source lines, and supporting slide
content is not semantically evaluated. The routine Markdown profile does not
include binary Office files by default.
Custom sectioning commands, unresolved macros in titles, and unclosed title
groups are unsupported and are skipped; no TeX engine is run.

Descriptive headings help readers use a table of contents to find inputs,
methods, examples, results, and limitations. Rhetorical headings can work well
as transitions, presentation claims, or marketing copy. Keep a creative title
when it helps the intended audience.

For example, a single “From Data to Results” heading needs no change. If many
sections repeat “From X to Y,” consider whether names such as “Simulation
Inputs” or “Model Results” would make the outline easier to scan. Do not infer
technical meaning or prescribe a replacement from the heading alone.

Reviewer prompt: could a reader find the section's subject from the table of
contents? If yes, keep the title; if not, consider naming the topic or artifact
directly.

This check does not assess authorship, scientific accuracy, complete semantic
specificity, overall prose quality, or an automatically appropriate rewrite.

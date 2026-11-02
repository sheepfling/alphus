# Semantic patchwork calibration sample

This is a read-only, non-fixture sample of the opt-in rules. It uses two public
Python source trees: [Sphinx](https://github.com/sphinx-doc/sphinx), a parser
and documentation renderer, and [Flask](https://github.com/pallets/flask), a
conventional web application framework. No private consumer code was read.

| Repository | Revision | Selected Python files | Runtime | Findings |
| --- | --- | ---: | ---: | ---: |
| Sphinx | `035a07c32c3241fd3356f4d827800c1f88525272` | 243 (`sphinx/**/*.py`) | 2.75 s | 0 |
| Flask | `2247b35ea1c47c727d7a06e51fa280e12a863ff6` | 24 (`src/flask/**/*.py`) | 0.46 s | 0 |

Both runs used the four provisional rules `prose-as-control`,
`rendered-value-reparsed`, `positional-semantic-overrides`, and
`unexplained-empty-results`. The shared policy used sentence thresholds of 80
characters and 10 words, `re.sub` as the only configured regex helper, a
consumer-declared renderer list, position names `row`, `row_number`, `page`,
`page_number`, `offset`, and `index`, semantic fields `text`, `content`,
`title`, `message`, `interpretation`, and `description`, a 50-character override
threshold, input names `records`, `items`, and `nodes`, and unavailable flags
`inferred_schema`, `schema_known`, and `supported_format`. Sphinx's renderer list
was `render`, `render_string`, `render_partial`, `render_from_file`,
`render_dot`, `render_dot_html`, `render_dot_latex`, `render_dot_texinfo`,
`render_math`, and `render_maths_to_base64`. Flask's list was
`render_template` and `render_template_string`.

The later `embedded-semantic-overrides` rule is not included in these runs. Its
detector requires a consumer-specific mapping and source-anchor contract; this
sample did not configure one, so it has no calibration result here.

An additional non-fixture negative probe scanned Click at revision
`2247b35ea1c47c727d7a06e51fa280e12a863ff6` (`src/click/**/*.py`, 17 files)
with the same thresholds, fields, and helper
names `format_filename`, `formatting.format_message`, and `termui.echo`. The
four rules above produced zero findings in 0.172 seconds. This does not add a
positive candidate or support a precision estimate.

Tests, generated files, and vendored files were excluded. The scan produced no
candidates to manually classify. Therefore this sample does **not** estimate
precision, does not establish the requested 90% high-confidence target, and
does not measure recall. The result supports only that these configurations
produced no matches in these selected source revisions; it is not evidence that
the patterns are absent from either repository.

This first sample also does not quantify overlap with existing rules or
suppression rates. The next calibration needs reviewed positive candidates and
more repositories before any precision or enforcement claim is meaningful.

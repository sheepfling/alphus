# Semantic patchwork calibration sample

This calibration reruns the opt-in rules with the literal `.replace()` detector
on three public Python source trees. Checkouts were read-only; only the Alphus
policy config supplied the exact source boundaries, helper names, and reviewed
rewrite exceptions shown below.

| Repository | Revision | Selected Python files | Runtime | Findings after reviewed exceptions |
| --- | --- | ---: | ---: | ---: |
| Sphinx | `035a07c32c3241fd3356f4d827800c1f88525272` | 243 (`sphinx/**/*.py`) | 2.37 s | 0 |
| Flask | `49943b5a94413a530761350f04e896f76e8d620e` | 24 (`src/flask/**/*.py`) | 0.40 s | 0 |
| Click | `2247b35ea1c47c727d7a06e51fa280e12a863ff6` | 17 (`src/click/**/*.py`) | 0.48 s | 0 |

The Sphinx commit is “Add missing hyphen to CVE and CWE role formats”;
Flask is “add `versionchanged` for ctx signature change (#6176)”; Click is
“Add `Parameter.spec` and deprecate `human_readable_name` (#3877)”. Each SHA was
verified against its upstream checkout. An earlier draft accidentally listed
the valid Click SHA as a Flask revision; it does not resolve in the Flask
repository. The verified Flask pin above corrects that record.

Before applying narrow reviewed exceptions, the updated lossy-rewrite detector
reported two Sphinx candidates and none in Flask or Click:

- `sphinx/ext/doctest.py:114`: `options.replace(',', ' ')` occurs while parsing
doctest-style option strings. The surrounding comment identifies this as
parsing comparison flags; comma is an input delimiter, not prose content. This
candidate was reviewed as an intentional format parser.
- `sphinx/writers/texinfo.py:387`: `s.replace('.', ' ')` is inside `escape_id`,
which normalizes node names/anchors and removes dots only when the identifier
contains other characters. The method docstring identifies node names and
anchors; this candidate was reviewed as intentional identifier normalization.

These are reviewed false-positive candidates for the broad delimiter heuristic,
not positive examples of semantic corruption. The Sphinx calibration policy now
suppresses only the exact displayed `replace(...)` evidence at each exact file
path. The same expressions remain reportable at other paths; the regression test
checks this scope. No consumer repository was edited. No representative
consumer positive involving a digit or sign erasure was found, so none is
reported here. The synthetic positive remains a boundary test, not production
evidence.

All three runs used the four provisional rules `prose-as-control`,
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
`render_template` and `render_template_string`. Click's list was
`format_filename`, `formatting.format_message`, and `termui.echo`.

The Sphinx policy additionally sets `allowed_literal_rewrites` for the two
reviewed path/expression pairs above. Flask needs no such exception. These
allowances are exact observations and do not globally suppress commas or dots.

The later `embedded-semantic-overrides` rule is not included in these runs. Its
detector requires a consumer-specific mapping and source-anchor contract; this
sample did not configure one, so it has no calibration result here.

The `heuristic-total-consumption` rule was separately probed against two
pinned public sources. At Sphinx
`035a07c32c3241fd3356f4d827800c1f88525272`,
`sphinx/domains/std/__init__.py::token_xrefs` (lines 558–589) uses
`token_re.finditer` under a preserving-unmatched-spans policy; the rule returned no candidate because the function
reconstructs unmatched prefixes and suffixes as text nodes. At Flask
`49943b5a94413a530761350f04e896f76e8d620e`,
`src/flask/templating.py::render_template` and
`render_template_string` (lines 136–159) were checked as an app-scope probe;
they delegate source rendering to Jinja and contain no configured token
matcher. The Sphinx parser/renderer is a manually reviewed negative because
it retains unmatched prefixes and suffixes. The Flask probe is not evidence
that the rule's preserving-output contract applies to template rendering.
There is no positive consumer example; these negative observations do not
estimate precision or recall. Neither checkout was modified.

Tests, generated files, and vendored files were excluded. The three configured
profiles produced no findings after the exact Sphinx exceptions; the unfiltered
lossy-rule scan surfaced two reviewed Sphinx candidates, both intentional
format-specific transformations. No positive semantic-loss candidate was
observed. This sample does **not** estimate precision, establish the requested
90% high-confidence target, or measure recall. Zero results after narrow
exceptions do not show that the patterns are absent from these repositories.

The two exact exceptions account for the only suppressed observations in this
sample; this does not estimate a general suppression rate or overlap with
existing rules. More repositories and reviewed positive candidates are needed
before any precision or enforcement claim is meaningful.

## Labeled boundary corpus

The focused test corpus in `tests/gates/review/test_semantic_patchwork_corpus.py`
contains twenty sanitized synthetic cases across the implemented detectors,
with at least one expected-positive and one boundary-negative for each
(`prose-as-control`,
`lossy-text-rewrite`, `rendered-value-reparsed`,
`positional-semantic-override`, `unexplained-empty-result`, and
`embedded-semantic-override`, `heuristic-total-consumption`,
`provenance-as-ownership`, and `semantic-work-in-presentation`). Two extra
provenance cases check returned and unused filter results. All twenty pass
their expected labels. The
positive labels represent the issue's deliberately constructed risk shapes;
the negative labels cover protocol text, output-only rendering, whitespace
normalization, layout offsets, valid empty input, and preservation of source
text. This corpus checks rule boundaries; it is not production calibration and
does not contribute to the 90% precision target.

One independently reviewed public-source negative is Sphinx's
[`rfc1123_to_epoch` parser][sphinx-http-date] at revision
`035a07c32c3241fd3356f4d827800c1f88525272`.
It checks the RFC-required `GMT` suffix and zero timezone offset on the input
date. That is explicit protocol validation, not a sentence discriminator or
rendered-output feedback; it is a useful reviewed boundary example, not a
detector finding. The public scans still contain no reviewed positive
candidates. Production precision and the requested 90% target therefore remain
unestimable.

[sphinx-http-date]:
  <https://github.com/sphinx-doc/sphinx/blob/035a07c32c32/sphinx/util/http_date.py>

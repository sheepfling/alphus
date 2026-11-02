# PDF and LaTeX evidence example

The `pdf-structural-check.toml` consumer example runs the maintained `qpdf`
structural validator against one explicitly named generated artifact. It also
forces a `latexmk` build before checking the final log for the expected output
name and common unresolved cross-reference warnings. It is an opt-in,
provisional command profile and is not added to Alphus's default profiles.
Adjust source, PDF, log, and helper paths for the consumer's build layout.

Install and manage `qpdf`, `latexmk`, and Poppler in the consumer's environment.
The navigation contract helper uses the optional `pypdf` dependency; install it
with `pip install 'alphus[pdf]'`. Alphus does not install native tools or build
the PDF outside the explicitly selected profile. Missing commands/artifacts
report failure or unknown evidence rather than an empty successful scan.

Run the profile with the consumer's `.tex` source at `build/report.tex`:

```shell
alphus --root . --config examples/documents/pdf-structural-check.toml \
  --run --profile pdf-structure
```

`qpdf --check` tests PDF syntax and structural consistency. A successful result
does not establish that bookmarks or links point to the intended sections,
that a page is visibly correct, or that the PDF is portable under a delivery
contract. In particular, do not use a stale expected-navigation manifest as
independent semantic evidence.

The log check runs after `latexmk -g` in the same profile, so it inspects the
forced build's log instead of accepting a previously generated file. It checks
for a matching `Output written on` filename and common unresolved reference,
citation, and rerun notices. It does not parse every TeX engine's diagnostics,
prove source-map freshness, or validate navigation. A missing or unfamiliar
output record fails closed with an execution finding.

## Evidence that needs a consumer contract

For semantic navigation, record section identity and expected destination from
an independent build/source map before inspecting the PDF. A text manifest
generated from the same outline does not qualify. Resolve each configured
outline or Contents link and compare its destination with the independently
declared target; report a missing map, ambiguous repeated heading, unsupported
destination fit mode, or unavailable text extraction as unknown/review-needed.

The optional `check_pdf_navigation.py` helper resolves configured outline
titles with pypdf, checks the one-based physical destination against the
consumer's source-map contract, and requires the configured heading text on
that target page. A Contents-link contract can also verify the configured
label appears on its source page, exactly one link annotation occupies the
declared rectangle, and that its GoTo destination agrees with the outline and
expected target page. The contract must name its independent `source_evidence`
and must be generated from source/build evidence rather than copied from the
PDF outline. The helper cannot prove that provenance; the consumer remains
responsible for it. Nor does it geometrically prove that the visible label text
occupies the annotation rectangle. Ambiguous titles and unresolved destinations
fail; a page with no extractable text is returned as **unknown**, since it may
contain images or vector artwork. Fit modes, page-label semantics, and visual
heading confirmation still need review or a richer consumer contract.

The available PDF stack in this checkout includes pypdf and qpdf. PyMuPDF was
installed locally to evaluate word-box geometry, but it is not an Alphus
dependency. A generated two-page fixture with a Contents label and GoTo link
showed an exact label/link rectangle match (area overlap 1.0); moving the link
rectangle 30 points below the label produced no overlap (0.0). This supports a
simple extractable-text geometry check, not a general visibility claim: it says
nothing about clipping, hidden text, font transforms, images, or rendered
appearance.

PyMuPDF's official licensing page describes an AGPL or commercial license
choice. This checkout has no project license declaration, so adding PyMuPDF as
an optional dependency would still create an unresolved licensing decision for
Alphus users. Keep the backend out of the dependency set until the project
license and redistribution policy are decided. See the
[PyMuPDF license information](https://pymupdf.readthedocs.io/en/latest/about.html)
and [word-level text geometry documentation](https://pymupdf.readthedocs.io/en/latest/recipes-text.html).

pypdf's `visitor_text` exposes text and transformation matrices, yet
its documentation cautions that coordinates may be wrong for complicated
documents ([pypdf extraction notes](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)).
qpdf checks PDF structure, not text bounds. Extracted text alone still does not
prove visible rendered text. Keep label-to-annotation overlap as a review-only
claim until fixtures cover clipping, rotation, font transforms, hidden text,
and rendered output with a suitable licensing decision.

For a target page with an independently known physical index, Poppler can
provide separate text and render evidence:

```shell
pdftotext -f 13 -l 13 -layout build/report.pdf -
pdftoppm -f 13 -l 13 -singlefile -png -r 120 build/report.pdf /tmp/report-target
```

Inspect the extracted page text and rendered image against the declared
section. Text extraction alone cannot establish that an image-only, outlined,
or vector page is blank. A render smoke confirms a backend produced pixels;
it does not judge the page content automatically. Preserve backend/version,
page index, source-map provenance, and any viewport/crop adjustments alongside
the review. The optional native-tool tests generate a minimal one-page PDF and
skip cleanly when qpdf or Poppler is unavailable; they test tool availability
and invocation only, not semantic destinations.

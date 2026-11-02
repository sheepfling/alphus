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
that target page. The contract must name its independent `source_evidence` and
must be generated from source/build evidence rather than copied from the PDF
outline. The helper cannot prove that provenance; the consumer remains
responsible for it. Ambiguous titles and unresolved destinations fail; a page
with no extractable text is returned as **unknown**, since it may contain
images or vector artwork. This check currently covers outline destinations;
Contents-link annotation identity, fit modes, page-label semantics, and visual
heading confirmation still need review or a richer consumer contract.

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

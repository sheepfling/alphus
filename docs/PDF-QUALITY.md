# PDF structural check

The `pdf-structural-check.toml` consumer example runs the maintained `qpdf`
structural validator against one explicitly named generated artifact. It is an
opt-in, provisional command profile and is not added to Alphus's default
profiles. Adjust `argv` to match the consumer's final PDF path and build
layout.

Install and manage `qpdf` in the consumer's environment. Alphus does not install
it or build the PDF. If the selected command or artifact is unavailable, the
command result reports that failure; it is not an empty successful scan.

Run the profile after the document build:

```shell
alphus --root . --config examples/documents/pdf-structural-check.toml \
  --run --profile pdf-structure
```

`qpdf --check` tests PDF syntax and structural consistency. A successful result
does not establish that bookmarks or links point to the intended sections,
that a page is visibly correct, or that the PDF is portable under a delivery
contract. Those are separate checks in issue #52. In particular, do not use a
  stale expected-navigation manifest as independent semantic evidence.

## Evidence that needs a consumer contract

For semantic navigation, record section identity and expected destination from
an independent build/source map before inspecting the PDF. A text manifest
generated from the same outline does not qualify. Resolve each configured
outline or Contents link and compare its destination with the independently
declared target; report a missing map, ambiguous repeated heading, unsupported
destination fit mode, or unavailable text extraction as unknown/review-needed.
This profile does not perform that resolution yet.

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

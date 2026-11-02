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

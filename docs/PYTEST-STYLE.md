# Native pytest-style review

The `pytest-style.toml` example selects Ruff's native `PT` rules for an
explicit test-file inventory. It is a provisional consumer profile, not part
of Alphus's default checks. Adjust the file scope and Ruff selection to match
the repository's declared testing convention.

Run it after installing Alphus's Python extra and Ruff:

```shell
alphus --root . --config examples/python/pytest-style.toml \
  --run --profile pytest-style
```

These rules identify selected style mismatches in tests; they do not make
pytest-compatible `unittest.TestCase` suites invalid or prove that a migration
is appropriate. Preserve `unittest.mock`, migration scaffolding, specialized
fixtures, and compatibility requirements through path scope or the consumer's
Ruff configuration. Review each result before changing tests. The profile does
not alter test code or run the test suite.

This is one native-recipe slice of issue #51. It does not implement the other
project conventions there, including model-boundary, UTC-persistence,
generated-output, packaging-authority, or semantic-state inference.

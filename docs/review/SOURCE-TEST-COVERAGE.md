# Declared source-to-test coverage

The opt-in `source-test-coverage` rule checks caller-declared source/test
relationships against a revision-matched execution artifact. It does not use
matching filenames, folder conventions, test counts, or a guessed source map.
The rule is separate from `test-quality` checks for test contents and oracle
independence, and from pytest-style native recipes.

A checked relationship means the declared test file exists and a current
artifact records that it ran and observed the declared source. A test that
failed can still establish that execution relationship; its test outcome is
reported separately, and this rule does not assess whether its assertions are
correct or independent.

## Configure the obligations

The relationship list is many-to-many. A source can declare several unit or
integration tests, and the same shared test can be listed for several sources.
No `tests/**` or language-specific layout is assumed.

```toml
[checks.source_test_coverage]
evidence_file = "build/source-test-coverage.json"

[[checks.source_test_coverage.relationships]]
source = "src/api.py"
tests = ["tests/unit/test_api.py", "tests/integration/api_contract.py"]

[[checks.source_test_coverage.relationships]]
source = "src/models.py"
tests = ["tests/integration/api_contract.py"]

[[checks.source_test_coverage.relationships]]
source = "src/generated/client.py"
generated = true
```

A generated source must be declared with `generated = true`. Other exclusions
must carry a reason of at least 20 characters. Excluded rows remain visible in
the report and do not count as checked.

## Supply execution evidence

The optional JSON artifact has an explicit schema and records repository-root
relative paths. Its `revision` must be the full Git commit SHA of the checkout.
The producer sets `complete` to true only when it can report every declared
test; partial artifacts use false.

```json
{
  "schema": "alphus.source-test-coverage",
  "schema_version": 1,
  "revision": "0123456789abcdef0123456789abcdef01234567",
  "complete": true,
  "tests": {
    "tests/unit/test_api.py": {
      "outcome": "passed",
      "observed_sources": ["src/api.py"]
    },
    "tests/integration/api_contract.py": {
      "outcome": "failed",
      "observed_sources": ["src/api.py", "src/models.py"]
    }
  }
}
```

Supported outcomes are `passed`, `failed`, `skipped`, and `not_selected`.
The producer can use per-test coverage contexts or another trusted
instrumentation source to populate `observed_sources`. The artifact format
does not treat line counts as test quality.

## Read the result

Each row has one status:

- `checked`: current evidence records a declared test executing and observing
  the source.
- `unverified`: execution or source-observation evidence is unavailable,
  partial, skipped, stale, or mismatched.
- `missing`: a declared test file is absent, or an explicitly listed source
  has no declared tests.
- `excluded`: the caller explicitly marked a source as generated or excluded.
- `unknown`: the rule was enabled without any declared relationships.

Unverified evidence never means “missing tests.” The rule does not infer
relationships from similar filenames, and it does not claim that line coverage
proves assertion quality or correctness. Missing or stale artifacts are
reported as incomplete advisory information; no default profile or CI job is
changed.

For a runnable opt-in example with a provisional profile step, see
[`examples/source-test-coverage/quality-gates.toml`](../../examples/source-test-coverage/quality-gates.toml).

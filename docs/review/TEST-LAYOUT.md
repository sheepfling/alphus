# Python test layout

The `test-layout` rule checks that a repository's Python test directories
follow the corresponding source package directories. It enforces physical
organization; it does not claim that a test covers a source module or that the
assertions are correct.

## Configure package roots

Add one pair for each package whose tests should mirror its import-package
tree:

```toml
[checks.test_layout]

[[checks.test_layout.pairs]]
source_root = "packages/example/src/example"
test_root = "packages/example/tests"
integration_roots = ["integration"]
```

Each root is repository-relative, must exist as a real directory inside the
checkout, and may not traverse a parent or symlink. A test root can belong to
only one source root. The `integration_roots` values are paths relative to the
test root; tests beneath them are treated as cross-module tests. The default
is `integration`.

If the source tree contains `src/example/api.py` and
`src/example/dis/receiver.py`, then these paths follow the policy:

```text
tests/test_api.py
tests/dis/test_receiver.py
tests/integration/test_end_to_end.py
tests/conftest.py
```

The checker also recognizes a flattened test name such as
`tests/test_dis_receiver.py` as a likely test for `dis/receiver.py` and reports
that it belongs under `tests/dis/`.

## Select the rule

Add the rule to a consumer-owned profile. For example:

```toml
[[orchestration.steps]]
kind = "rule"
name = "Python test layout"
rule = "test-layout"

[[orchestration.profiles]]
name = "check"
steps = ["Python test layout"]
```

Alphus does not silently add this check to consumer profiles. Use
`alphus --catalog --json` to confirm the selector is available and
`alphus --plan --profile check` to verify it is selected.

## Finding behavior and limits

The rule scans conventional Python test modules named `test_*.py` or
`*_test.py` from the repository file inventory. It compares package-relative
directories and source module names. A test whose source module is at the
package root may stay at the test root. An unmatched root-level test is
reported because cross-module tests need an explicit integration directory.
Nested test directories must correspond to directories present under the
configured source root unless they are beneath an integration root.

`conftest.py` and `__init__.py` are not treated as tests. Other support Python
files that do not follow pytest test-module naming are outside this rule.
The checker does not parse test bodies or prove source-to-test relationships;
use [`source-test-coverage`](SOURCE-TEST-COVERAGE.md) for explicit source/test
contracts and revision-matched execution evidence.

The built-in rule is generic. Consumers own the root mappings and integration
directory names in their policy. See the
[example policy](../../examples/consumer/test-layout/quality-gates.toml).

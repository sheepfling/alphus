# Auditing lint suppression reasons

The opt-in `suppression-reasons` rule checks configured Ruff `# noqa: CODE`
comments for a consumer-required explanation, including targeted file-level
`# ruff: noqa: CODE` directives. An inline reason after `--` satisfies the
requirement:

```python
from optional_runtime import plugin  # noqa: E402 -- initialize the plugin registry first
```

It also checks Ruff's TOML `per-file-ignores` and
`extend-per-file-ignores` tables in `pyproject.toml`,
`ruff.toml`, and `.ruff.toml` against the selected Python paths. A matching
selected code needs a comment containing the configured delimiter and a reason:

```toml
[tool.ruff.lint.per-file-ignores]
"src/bootstrap/**" = ["E402"] # -- plugin initialization order
```

The rule evaluates table entries, inline maps, and multiline arrays in per-file
ignore settings. It normalizes Ruff's string-to-code-list multiline inline map
form before validating TOML, including on Python versions whose standard
library parser does not accept multiline inline tables. Unsupported map values
are reported as not evaluated. A matching exact path/code/line exception can
approve a configuration entry:

```toml
[[checks.suppression_reasons.exceptions]]
path = "ruff.toml"
rule_code = "E402"
line = 2
reason = "Plugin bootstrap imports must remain ordered before registration."
```

When more than one supported Ruff configuration file is present at the
repository root, discovery follows Ruff's precedence: `.ruff.toml`, then
`ruff.toml`, then `pyproject.toml`. The scanner follows `extend` chains up to
eight files when each target remains under the selected repository root. Native
Ruff differential tests cover the four parent/child combinations of normal
`per-file-ignores` and additive `extend-per-file-ignores` tables. A child normal
table replaces inherited normal entries, while inherited extended entries
remain additive; the reason audit skips replaced inherited entries but retains
the additive ones. Regression cases also cover inherited inline maps under
both behaviors. Cycles, missing/out-of-root targets, excessive depth, and
unsupported TOML values are reported as not evaluated; Ruff remains authoritative
for the effective lint configuration and whether a suppression is valid or used.

Consumers select the codes, file scope, exclusion patterns, severity, and reason
delimiter in `[checks.suppression_reasons]`; see
[`examples/consumer/lint-suppressions.toml`](../examples/consumer/lint-suppressions.toml).
Exceptions can approve one exact path, rule code, and line. Each exception
requires a reason. Moved line/code sites are stale when their file is selected;
exceptions pointing to a missing Python or TOML file are stale even though that
file cannot appear in the inventory:

```toml
[[checks.suppression_reasons.exceptions]]
path = "src/package.py"
rule_code = "E402"
line = 12
reason = "Plugin bootstrap must precede this optional runtime import."
```

The rule reads Python comment tokens and never imports or executes consumer
code. Text that resembles a directive in a string or docstring is ignored.

This checker verifies only that the selected suppression has a non-empty
documented reason. It does not decide whether the import is misplaced or the
reason is true. Blanket directives without selected codes produce an
"unknown / not evaluated" advisory; Ruff remains responsible for unused,
invalid, blanket, and foreign-tool suppression diagnostics. Non-Ruff
directives are outside this rule's selected Ruff syntax.

# Auditing lint suppression reasons

The opt-in `suppression-reasons` rule checks configured Ruff `# noqa: CODE`
comments for a consumer-required explanation, including targeted file-level
`# ruff: noqa: CODE`, `# flake8: noqa: CODE`, and `# ruff: file-ignore[CODE]`
directives. Prefixes follow Ruff's case rules (`ruff` and `flake8` are
case-sensitive; `noqa` is case-insensitive). A reason after `--` satisfies the
requirement:

```python
from optional_runtime import plugin  # noqa: E402 -- initialize the plugin registry first
```

File-level directives are recognized on their own line. `# ruff: file-ignore`
is accepted only at global module scope. Blanket `# noqa`, `# ruff: noqa`, and
`# flake8: noqa` directives produce an unknown/not-evaluated advisory because
they do not name a selected rule code.

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
library parser does not accept multiline inline tables. A comment attached to a
multiline inline-map value applies only to that entry; a reason on a different
entry does not satisfy it. TOML comments outside an entry are not attributed to
individual entries; a comment after the closing map applies to none of them.
Per-file patterns use repository-relative and basename matching, including
Ruff's leading `!` negation and comma-separated brace alternatives such as
`{src,tests}/**`. Configured rule codes use Ruff's exact or prefix selectors,
so `E4` selects a configured `E402` code. Unsupported TOML values are reported
as not evaluated. A matching exact path/code/line exception can
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
Alphus CI runs that example's `suppression-review` profile against `src/**/*.py`
as a self-audit. This dedicated CI invocation does not add the opt-in rule to
the default consumer profile.
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
invalid, blanket, and foreign-tool suppression diagnostics. This rule
recognizes Ruff directives and Ruff's documented Flake8 `noqa` file directives;
other foreign-tool directives remain outside its selected syntax. If no selected
Python source remains after scope and exclusions, the rule emits an informational
not-evaluated finding at repository scope; it still audits any configured Ruff
TOML suppression entries. A rule that does run over selected Python files and
finds no missing reasons returns no findings, while policy absence remains a
configuration failure.

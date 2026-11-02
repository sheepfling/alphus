# Auditing lint suppression reasons

The opt-in `suppression-reasons` rule checks configured Ruff `# noqa: CODE`
comments for a consumer-required explanation, including targeted file-level
`# ruff: noqa: CODE` directives. An inline reason after `--` satisfies the
requirement:

```python
from optional_runtime import plugin  # noqa: E402 -- initialize the plugin registry first
```

Consumers select the codes, file scope, exclusion patterns, severity, and reason
delimiter in `[checks.suppression_reasons]`; see
[`examples/consumer/lint-suppressions.toml`](../examples/consumer/lint-suppressions.toml).
Exceptions can approve one exact path, rule code, and line. Each exception
requires a reason; moved or deleted exception sites are reported as stale when
their path is selected:

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

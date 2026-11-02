# Auditing lint suppression reasons

The opt-in `suppression-reasons` rule checks configured Ruff `# noqa: CODE`
inline comments for a consumer-required explanation. Its first supported form
is an inline reason after `--`:

```python
from optional_runtime import plugin  # noqa: E402 -- initialize the plugin registry first
```

Consumers select the codes, file scope, exclusion patterns, severity, and reason
delimiter in `[checks.suppression_reasons]`; see
[`examples/consumer/lint-suppressions.toml`](../examples/consumer/lint-suppressions.toml).
The rule reads Python comment tokens and never imports or executes consumer
code. Text that resembles a directive in a string or docstring is ignored.

This checker verifies only that the selected suppression has a non-empty
documented reason. It does not decide whether the import is misplaced or the
reason is true. Ruff remains responsible for unused, invalid, and blanket
suppression diagnostics. File-level `# ruff: noqa`, blanket suppressions, and
non-Ruff directives are outside this initial slice.

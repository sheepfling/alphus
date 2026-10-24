# Confusable positional interface example

This installed-consumer example opts into the Python advisory and keeps native
diagnostics in their own tool output. It does not install Ruff or Pylint and is
not wired into repository CI.

Run the Alphus review with an existing installation:

```shell
alphus --root examples/consumer/confusable-positional \
  --config quality-gates.toml --run --profile argument-review --json
```

The direct finding uses the existing JSON shape: `rule_id`, `path`, `message`,
`line`, and `severity`. `src/coordinates.py` produces one informational finding
for `x` and `y`. The distinct `Latitude` and `Longitude` classes do not match
the primitive pilot. `src/call_order.py` shows a name-based call-order mismatch
for Pylint's W1114 rule. The compatibility and symmetric-operation modules are
excluded by the consumer's documented path policy.

To also run the consumer's native Pylint diagnostics, use the optional profile
only when Pylint is already installed and configured in that environment:

```shell
alphus --root examples/consumer/confusable-positional \
  --config quality-gates.toml --run \
  --profile argument-review-with-pylint --json
```

The example's `.pylintrc` enables native positional-count and call-order
messages. Alphus keeps the command's stdout/stderr in the existing orchestration
step result and leaves native rule names and output untouched. A missing tool is
reported as a command launch failure; Alphus does not treat it as a clean run or
install Pylint. Both steps are provisional here so the example remains advisory.

The sibling `ruff.toml` shows the separate positional-count rule. It is not
invoked by this policy. Merge its values into the consumer's existing Ruff
configuration rather than replacing selected checks. For C/C++, use the
consumer's existing `.clang-tidy` selection and compilation database, as
described in the [positional interface guide](../../../docs/POSITIONAL-INTERFACES.md).

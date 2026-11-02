# Run artifact provenance example

This opt-in, provisional example demonstrates four configured local patterns:

- a conditional writer followed by a read of the same consumer-declared reused
  output path; and
- a configured parser followed by a provenance digest helper reading the same
  configured input path;
- cleanup of a declared diagnostic path before a failure sink uses that path;
  and
- distribution metadata in a provenance sink without a configured imported
  module-origin call in that sink.

The findings describe review candidates. They do not establish stale data or a
file change. Direct function spellings, a direct name argument, same-function
ordering, selected Python files, and the configured path names are required.
Unknown helpers, expressions/aliases, rebinding, separate functions, and
unconfigured paths are not followed. A same captured-byte value is outside the
path-based pattern. The failure-order rule supports only direct
`returncode != 0` branches and direct cleanup/sink calls; it does not establish
what a sink persists or model exceptions, `finally`, or external logging. The
runtime rule identifies a missing configured origin check, not the imported
code's actual identity. Neither family imports or executes consumer code.

Run the installed-consumer example with an existing Alphus installation:

```shell
alphus --root examples/consumer/run-artifacts \
  --config quality-gates.toml --run --profile run-artifact-review --json
```

The example code intentionally calls undefined consumer helpers; Alphus parses
source and does not import or execute it. The names are synthetic and do not
refer to a real consumer harness.

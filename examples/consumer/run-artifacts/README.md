# Run artifact provenance example

This opt-in, provisional example demonstrates two configured local patterns:

- a conditional writer followed by a read of the same consumer-declared reused
  output path; and
- a configured parser followed by a provenance digest helper reading the same
  configured input path.

The findings describe review candidates. They do not establish stale data or a
file change. Direct function spellings, a direct name argument, same-function
ordering, selected Python files, and the configured path names are required.
Unknown helpers, expressions/aliases, rebinding, separate functions, and
unconfigured paths are not followed. A same captured-byte value is outside the
path-based pattern. The rule does not cover failure-evidence ordering or runtime
import attestation, and it never deletes or changes artifacts.

Run the installed-consumer example with an existing Alphus installation:

```shell
alphus --root examples/consumer/run-artifacts \
  --config quality-gates.toml --run --profile run-artifact-review --json
```

The example code intentionally calls undefined consumer helpers; Alphus parses
source and does not import or execute it.

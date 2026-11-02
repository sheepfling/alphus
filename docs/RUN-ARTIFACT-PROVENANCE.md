# Run artifact provenance review

`run-artifacts` is an opt-in, provisional Python review rule for two configured
local patterns: conditional writes followed by reads from a declared reused
output path, and a parser followed by a provenance digest helper that rereads
the same declared input path. It reports a possibility to review; it does not
prove stale data or a time-of-check/time-of-use change.

Consumers must configure the helper spellings and path argument positions in
`[checks.run_artifacts]`. The rules operate only on the selected Python files,
within one function, and require a direct configured path variable argument.
The output rule also requires the consumer to declare the path as reused and
checks for a syntactically conditional writer followed by an unconditional
read. The provenance rule requires the digest call to occur inside a configured
provenance sink call. A fresh per-run path can be listed under
`fresh_output_path_names`; immutable captured-byte names can be listed under
`immutable_snapshot_names` and cannot also be configured as reused/input paths.

Alphus does not infer helper semantics, resolve path expressions or aliases,
follow values between functions, import consumer code, or detect a file changing
between operations. Rebound paths and locally shadowed helper names abstain.
Only direct `if` branches count as conditional writes in this initial slice.
Unknown helpers, path expressions, output lifecycle, or external persistence
remain unassessed. Failure-evidence ordering and runtime import attestation are
not covered. The scanner never deletes, rewrites, or installs artifacts.

See the synthetic [consumer example](../examples/consumer/run-artifacts/README.md)
for a complete policy and invocation.

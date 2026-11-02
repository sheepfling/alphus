# Run artifact provenance review

`run-artifacts` is an opt-in, provisional Python review rule for four configured
local patterns: conditional writes followed by reads from a declared reused
output path; a parser followed by a provenance digest helper that rereads the
same declared input path; cleanup of a declared failure diagnostic before a
configured failure sink reuses that path; and distribution metadata recorded
without a configured origin check for a declared runtime module. It reports
review candidates; it does not prove stale data, a time-of-check/time-of-use
change, lost diagnostics, or a mismatched import.

Consumers must configure the helper spellings and path argument positions in
`[checks.run_artifacts]`. The rules operate only on the selected Python files,
within one function, and require a direct configured path variable argument.
The output rule also requires the consumer to declare the path as reused and
checks for a syntactically conditional writer followed by an unconditional
read. The provenance rule requires the digest call to occur inside a configured
provenance sink call. A fresh per-run path can be listed under
`fresh_output_path_names`; immutable captured-byte names can be listed under
`immutable_snapshot_names` and cannot also be configured as reused/input paths.

An output family may also configure `current_run_artifact_checks` with a
consumer predicate helper and the positional argument that names the output
path. The checker suppresses a candidate when a direct
`if not is_current_artifact(output_path, manifest): raise ...` or `return`
guard after a configured write exits before later reads of that same declared
path. A pre-write or nonterminal check, mismatched path, shadowed helper, or
unguarded read does not count as a control.
The consumer must ensure the helper checks an authoritative manifest for the
current run; static scanning cannot verify that contract or the manifest's
construction.

Alphus does not infer helper semantics, resolve path expressions or aliases,
follow values between functions, import consumer code, or detect a file changing
between operations. Rebound paths and locally shadowed helper names abstain.
Only direct `if` branches count as conditional writes in this initial slice.
Unknown helpers, path expressions, output lifecycle, or external persistence
remain unassessed. Failure-evidence ordering and runtime import attestation are
bounded to the exact grammars below. The scanner never imports or executes
consumer code, deletes, rewrites, or installs artifacts.

## Failure evidence before cleanup

Enable `failure_evidence_order` and configure `failure_child_runners`,
`failure_diagnostic_path_names`, `failure_cleanups`, and `failure_sinks`.
The first version recognizes only a direct assignment from a declared child
runner followed by a top-level `if result.returncode != 0:` whose body contains
direct cleanup and failure-sink calls in that order. Both calls must use the
same declared diagnostic path variable at their configured argument positions.
It asks whether status and redacted diagnostics are durably retained before
cleanup. The scanner cannot establish what a cleanup helper removes, what a
sink persists, or whether an external logger retains evidence. It does not
inspect `finally`, exception handlers, presentation failures, or missing sinks.
Those cases remain unknown.

`tests/gates/review/test_run_artifacts_failure_fixture.py` is an executable
two-run fixture for this ordering contract. It launches a bounded controlled
child using the current Python interpreter, captures stderr, reuses one
diagnostic path across two failed runs, and compares persistence-before-cleanup
with cleanup-before-persistence. The good path retains distinct run IDs, return
codes, and redacted diagnostics in a temporary JSONL sink flushed with `fsync`;
the bad path retains status but loses the diagnostics. This demonstrates local
ordering behavior without asserting that static analysis proves other sinks'
durability or that any production harness loses evidence.

## Runtime metadata versus imported module origin

Enable `runtime_attestation_gap` and configure the runtime module name,
`runtime_import_helpers`, `runtime_metadata_helpers`, `runtime_origin_helpers`,
and `runtime_attestation_sinks`. The rule recognizes a module assigned directly
from a configured import helper and a configured metadata check nested in a
configured sink. A simple single-assignment local alias copied after the import
is also followed within the same function. Branch-local and nested-scope aliases
are not followed, and rebinding makes an alias inconclusive. The candidate is
suppressed only when the same sink contains a configured origin helper called
with the imported module or one of those tracked aliases.

This identifies a declared evidence gap. It does not determine which code was
imported, validate metadata, or establish that an origin path is a cryptographic
identity. Static scanning does not execute imports or a consumer-selected
runtime provenance recipe. Editable installs, namespaces, zip imports, native
modules, and alternate interpreters are not classified; consumers should keep
unsupported packaging explicitly unknown and may use a separate trusted runtime
recipe to collect interpreter and module-origin evidence.

See the synthetic [consumer example](../examples/consumer/run-artifacts/README.md)
for a complete policy and invocation.

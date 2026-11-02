# CI workflow duplication review

`ci-workflows` is an opt-in, read-only review rule for repeated static
multiline GitHub Actions `run` blocks. It groups exact command text across
distinct jobs with the same static `runs-on` value. By default matrix jobs,
conditions, dependencies, permissions, environments, step overrides, expressions,
and aliases are excluded. Literal block scalars and configured minimum line
counts constrain the scan.

A user may explicitly allowlist an exact normalized command string in
`matrix_invariant_run_blocks`. Only simple literal matrix axes with no other
strategy settings are eligible, and only the allowlisted script is reported.
This signals that a repository-only check repeats per leg; it does not assert
the matrix is unnecessary or remove version-specific testing. `ignore_run_blocks`
and `severity` configure regular repeated blocks.

Azure Pipelines can be opted in with `azure_workflow_paths`. That parser only
compares literal multiline `script`/`bash` steps across jobs with identical
static scalar pools. Job/step conditions, templates, expressions, aliases,
mapping pools, and other contextual keys are skipped. It does not execute or
edit workflows. Parsing uses PyYAML's `BaseLoader` node tree, which avoids
constructing arbitrary tagged Python objects. Parse errors are reported as
execution errors.

See the [consumer example](../examples/consumer/ci-workflows/README.md) for a
complete policy and invocation.

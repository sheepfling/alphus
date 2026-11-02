# CI workflow duplication review

`ci-workflows` is an opt-in, read-only review rule for long static inline
scripts, repeated GitHub Actions `run` blocks, and repeated setup actions. It groups
exact command text or an identical `setup-*` action with identical static
`with` inputs across distinct jobs with the same static `runs-on` value. By default matrix jobs,
conditions, dependencies, permissions, environments, step overrides, expressions,
and aliases are excluded. Literal block scalars and configured minimum line
counts constrain the scan.

`maximum_inline_run_lines` (default `20`) reports a long inline script as a
maintainability candidate. It counts nonblank source lines in literal multiline
`run`/`script`/`bash` blocks. Contextual steps and unsupported jobs remain
excluded, and `ignore_run_blocks` suppresses an exact script. A finding does
not claim that the steps are redundant or should be removed.

A repeated setup-action candidate is informational: jobs have isolated
environments, so setup may be required in every job. It recommends reviewing
whether shared workflow configuration would help; it does not recommend
removing setup. Use `ignore_setup_actions` to suppress a repeated action by its
exact `uses` value (for example, `actions/setup-python@v5`). Conditional steps,
dynamic inputs, and jobs with additional execution context are skipped.

A user may explicitly allowlist an exact normalized command string in
`matrix_invariant_run_blocks`. This applies to GitHub Actions and Azure
Pipelines. Only literal matrices with at least two statically named legs and
static values are eligible; any additional strategy setting makes the analyzer
abstain. For Azure, matrix-scoped scripts must also avoid shell-variable
references. Only the allowlisted script is reported. This signals that a
repository-only check repeats per leg; it does not assert the matrix is
unnecessary or remove version-specific testing. `ignore_run_blocks` and
`severity` configure regular repeated blocks.

Azure Pipelines can be opted in with `azure_workflow_paths`. That parser only
compares literal multiline `script`/`bash` steps across jobs with identical
static pools, including mapping-form pools such as `vmImage`. It also reports
exact repeats of selected tool setup tasks (`UsePythonVersion`, `UseDotNet`,
`NodeTool`, `JavaToolInstaller`, `GoTool`, and `UseRubyVersion`) when task
versions, inputs, and pools match. Azure runtime expressions, aliases,
templates, conditions, and jobs/steps with additional context are skipped.
These are review candidates; setup may still be required in isolated jobs. It
does not execute or edit workflows. Parsing uses PyYAML's `BaseLoader` node
tree, which avoids constructing arbitrary tagged Python objects. Parse errors
are reported as execution errors.

See the [consumer example](../examples/consumer/ci-workflows/README.md) for a
complete policy and invocation.

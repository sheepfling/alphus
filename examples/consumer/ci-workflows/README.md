# GitHub Actions and Azure Pipelines workflow review example

This provisional profile reports exact static multiline command blocks that
repeat in distinct jobs with matching static runner/pool values. Azure support
is opt-in through `azure_workflow_paths`. Contextual jobs and steps are skipped.
For Azure Pipelines it also reviews a small allowlist of repeated tool setup
tasks (`UsePythonVersion`, `UseDotNet`, `NodeTool`, `JavaToolInstaller`,
`GoTool`, and `UseRubyVersion`) when the task version, static inputs, and static
pool match exactly. It compares mapping-form pools such as `vmImage` as well as
literal pool names. Azure runtime expressions and additional job/task context
are not resolved, so those candidates are skipped.

Simple matrix jobs are excluded by default. A specific repository-only command
may be explicitly listed in `matrix_invariant_run_blocks`; that produces a
candidate that the command runs for every matrix leg. Matrix-dependent tests
are excluded, and the finding is not a claim that the matrix is redundant.

The rule is read-only and advisory. It does not execute workflows or edit them.
Run the consumer example with an installed Alphus checkout:

```shell
alphus --root examples/consumer/ci-workflows --config quality-gates.toml \
  --run --profile ci-workflow-review --json
```

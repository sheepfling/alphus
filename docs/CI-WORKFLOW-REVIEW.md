# CI workflow duplication review

`ci-workflows` is an opt-in, read-only review rule for repeated static
multiline GitHub Actions `run` blocks. It groups exact command text only across
distinct jobs with the same static `runs-on` value and reports the job names
and YAML source lines. An identical block is a review candidate; the rule does
not claim that jobs are redundant or rewrite workflow files.

The current slice deliberately abstains on matrix jobs, job conditions,
dependencies, permissions, environments, services, job defaults, step
conditions, environment overrides, shells, working directories, expressions,
and YAML aliases/anchors. It only considers literal block scalars (`|` or `>`)
with at least the configured `minimum_run_lines`. `ignore_run_blocks` suppresses
exact normalized command strings; `severity` is configurable. File selection
is controlled by the normal inventory, extensions, exclusions, and
`workflow_paths` policy.

Parsing uses PyYAML's `BaseLoader` node tree and source marks. BaseLoader treats
scalars as strings rather than constructing tagged Python objects. Parse
errors are reported as execution errors, not as a clean workflow scan. This
first slice covers GitHub Actions only. Azure Pipelines, script extraction,
setup-action duplication, and explicitly configured matrix-independent checks
remain future work.

See the [consumer example](../examples/consumer/ci-workflows/README.md) for a
complete policy and invocation.

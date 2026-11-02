# GitHub Actions workflow review example

This provisional profile finds exact static multiline `run` blocks repeated in
distinct GitHub Actions jobs with the same static `runs-on` value. Its finding
is a candidate for review, not a conclusion that the jobs or commands are
redundant. A checked-in script may improve reuse, but any proposed change still
needs workflow-specific review.

The first slice excludes matrix jobs, job or step conditions, job environments,
shell/working-directory overrides, expressions, YAML anchors/aliases, and
workflow-level YAML other than GitHub Actions. It does not compare individual
matrix legs. Other contextual job keys or step keys cause those scopes to be
skipped. The parser uses PyYAML's `BaseLoader` node tree, which keeps YAML
scalars as strings and exposes source marks without constructing arbitrary
objects. It does not execute workflows or edit them.

An exact command block can be suppressed with `ignore_run_blocks`. `severity`
is configurable. Azure Pipelines, long scripts within one job, setup-action
deduplication, and matrix-independent command recognition are deferred.

Run the consumer example with an installed Alphus checkout:

```shell
alphus --root examples/consumer/ci-workflows --config quality-gates.toml \
  --run --profile ci-workflow-review --json
```

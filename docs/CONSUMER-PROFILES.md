# Consumer quality profiles

The example policy at
[`examples/consumer/quality-gates.toml`](../examples/consumer/quality-gates.toml)
shows a single local profile that coordinates portable Alphus rules with
mdrepo, rumdl, and the Python project's own lint, type, and test commands.
Copy it into a consumer repository and adjust file scopes, thresholds, and
tool arguments there. Alphus does not add mdrepo, rumdl, Ruff, Pyright, or
pytest to its runtime dependencies.

## Ownership hierarchy

The repository's top-level `check` command is the stable local and CI entry
point. It selects one Alphus profile, which runs the owners in this order:

1. **Alphus portable rules** enforce repository-selected Python and source
   conventions. Their paths, thresholds, and exclusions live in the consumer's
   TOML policy.
2. **mdrepo** checks Markdown links and the repository document graph. Its
   `mdrepo.toml` config and native rule IDs remain owned by mdrepo.
3. **rumdl** checks Markdown formatting and style. Its config and rule IDs
   remain owned by rumdl; `fmt --check` is read-only.
4. **Python tools** own Python lint, static typing, and tests. The example uses
   Ruff, Pyright, and pytest as configured commands. Pyright receives the same
   interpreter selected by Alphus through `{python}`.
5. **Alphus orchestration** preserves the declared order, runs later steps
   after a failure, and combines each step's outcome into the profile exit
   status.

This gives each finding one owner. Do not recreate Markdown graph checks,
Markdown formatting rules, Python lint rules, or type-checker rules as Alphus
predicates. Use Alphus for reusable repository policy and as the coordinator.

## Install and run

Install Alphus and the tools named by the copied profile in the same consumer
development environment. For example, use the repository's lockfile or
development-dependency group to install mdrepo, rumdl, Ruff, Pyright, and
pytest. mdrepo must be importable by the selected Python interpreter because
the sample invokes `python -m mdrepo`; rumdl and Pyright must be on `PATH`.
The example `mdrepo.toml` explicitly enables missing-target and orphan checks;
the tool defaults leave those checks disabled.

Run the whole profile from any directory by naming both repository and policy:

```sh
alphus --root /path/to/repository \
  --config /path/to/repository/quality-gates.toml \
  --run --profile check
```

Run only the coordinated documentation checks with `--profile docs`. The
rumdl step uses Alphus's Git-aware file inventory, including tracked and
non-ignored untracked Markdown files. An empty scope is a successful skipped
step; otherwise file paths are passed as separate arguments.

Human output shows each step and its exit status. `--json` writes one JSON
summary to stdout with each step's status, exit code, and captured diagnostic
lines; launch errors use exit code 127. The profile exits 1 when any step
fails, and invalid policy/profile selection exits 2. Native tool output and
exit codes are not rewritten into Alphus rule findings.

## Tool configuration

Keep each tool's configuration at the repository level it already owns:

- `quality-gates.toml` selects Alphus checks, file scopes, and execution order.
- `mdrepo.toml` owns document graph and link conventions.
- rumdl's config owns Markdown lint and formatting options.
- `pyproject.toml`, `pyrightconfig.json`, or the consumer's existing config
  files own Ruff, Pyright, and pytest settings.

The top-level runner coordinates these configs without merging their policy
languages. The command arrays in the example can be changed to use a wrapper
such as `npm run check:docs`, provided its scope and exit status remain clear.

# Fix plans and explicit application

Alphus separates detection from file changes. The ordinary `--run` profile
never runs a fixer. A command step may declare `fix_argv`; Alphus then lists
that step as fixable for profiles that select it. Built-in rules currently
return findings only and have no mutation API.

## Current fixability

| Self-profile step | Configured fixer | Reason |
| --- | --- | --- |
| Python lint | Ruff `check --fix` | Applies Ruff's default safe fixes; remaining findings still need review. |
| Python format | Ruff `format` | Applies deterministic formatting. |
| TOML and JSON syntax | None | Invalid input does not have a generally correct rewrite. |
| Python types, package tests, package imports, compatibility imports | None | Requires a code or package decision. |
| Portable policy and review rules | None | Findings express project conventions or semantic changes. |

The portable rules without fixers are `file-size`, `line-length`,
`comment-markers`, `json-structure`, `output-escaping`, `path-discovery`,
`shared-utilities`, `module-roles`, `python-style`, `runtime-types`, `cli`,
`script-policy`, `package-boundaries`, `dependency-locks`,
`repository-layout`, `numeric-literals`, `test-quality`, and
`input-contracts`. A formatter may happen to remove an individual
`line-length` finding, but Alphus does not promise that result.

Other consumers can add fix commands for their own native tools. A Markdown
formatter, TOML formatter, and JSON formatter are configured in the
[consumer example](../examples/consumer/quality-gates.toml):

| Language | Read-only check | Explicit fixer |
| --- | --- | --- |
| Markdown | mdrepo graph check | None; links need review. |
| Markdown | rumdl `check` | rumdl `fmt` for supported rules. |
| TOML | `tomllib` syntax | None; malformed TOML needs review. |
| TOML | Taplo `fmt --check` | Taplo `fmt`. |
| JSON | `json` syntax | None; malformed JSON needs review. |
| JSON | Prettier `--check` | Prettier `--write`. |

The example keeps these steps in separate language files. Tools must be
installed and pinned by the consumer. Applying a formatter may change many
lines; inspect the diff and rerun the read-only profile. Package-manager lock
regeneration also needs review for dependency changes.

## Review and apply

From a checkout with a configured profile:

```sh
alphus --root . --config quality-gates.toml --fix-plan --profile check
alphus --root . --config quality-gates.toml --fix-plan --profile check --json
alphus --root . --config quality-gates.toml --apply-fixes \
  --profile check --fix-step "Python format"
alphus --root . --config quality-gates.toml --run --profile check
```

`--fix-plan` is read-only. It lists every selected step as `FIXABLE` or
`NO FIXER`; JSON includes selected files for scoped command steps and the
expanded write arguments when a fixer exists. `--apply-fixes` requires one or
more explicit `--fix-step` names. Selected fixers run once in profile order,
regardless of the order in which their names were supplied. An empty file
scope skips its fixer. A
nonzero exit stops further fixes and is reported; edits already made by the
tool remain for review. Inspect the resulting Git diff and rerun the profile.

The consumer policy owns each fixer. A `fix_argv` must use one complete
`{files}` argument and a command-step `files` inventory; the command runs
only when files match. Alphus expands `{python}`, `{root}`, and `{config}`
as for check commands, keeps the working directory inside the checkout, and
passes arguments without a shell except for Windows batch launchers. Review
the policy before applying fixes because the configured tool may itself write
beyond the selected input files.

```toml
[[orchestration.steps]]
kind = "command"
name = "Python format"
argv = ["{python}", "-m", "ruff", "format", "--check", "{files}"]
fix_argv = ["{python}", "-m", "ruff", "format", "{files}"]
files = { include = ["src/**/*.py", "tests/**/*.py"] }
```

The next extension for Alphus-owned rules would be a typed edit proposal:
rule ID, target path, expected content hash, exact text edit, and a reason.
An apply command could reject stale proposals, conflicting edits, and paths
outside the checkout before writing. That contract should be added when a
specific built-in rule has a mechanical, semantics-preserving correction.

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
formatter is a likely candidate when its installed version has a documented
write mode; package-manager lock regeneration may also be useful, but must be
reviewed for dependency changes. Neither is declared by Alphus automatically.

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
`NO FIXER`; JSON also includes the exact selected files and configured
argument vector. `--apply-fixes` requires one or more explicit `--fix-step`
names. Selected fixers run once in profile order, regardless of the order in
which their names were supplied. An empty file scope skips its fixer. A
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

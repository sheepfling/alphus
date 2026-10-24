# Consumer quality profiles

The example policy at
[`examples/consumer/quality-gates.toml`](../examples/consumer/quality-gates.toml)
shows a single local profile that coordinates portable Alphus rules with
mdrepo, rumdl, and the Python project's own lint, type, and test commands.
Copy it into a consumer repository and adjust file scopes, thresholds, and
tool arguments there. Alphus does not add mdrepo, rumdl, Ruff, Pyright, or
pytest to its runtime dependencies.

## Profiles by consumer type

A consumer selects capabilities explicitly. File extensions do not silently
activate gates. Ordinary Python repositories can combine `python` and
`markdown`; stub packages combine those with `stubs`.

| Profile | Typical checks | Policy owner |
| --- | --- | --- |
| `markdown` | Document links/graph, style/format | mdrepo and rumdl |
| `python` | Lint, formatting, project tests/tooling types | Ruff, pytest/unittest, Mypy/Pyright |
| `stubs` | Build/install, API, typed examples, stubtest, smoke | Alphus and native checkers |
| `cpp` | C++ source, build, test, package, and artifact checks | Alphus C++ engines and consumer tools |
| `toml` | TOML document syntax | Python `tomllib` or a consumer-selected validator |
| `json` | JSON document syntax | Python `json` or a consumer-selected validator |
| `python-policy` | Optional repository-specific source conventions | Explicit Alphus source policy |

Define each profile's steps in the consumer policy, then compose them:

```toml
[[orchestration.profiles]]
name = "stubs"
steps = ["Installed stub consumer verification"]

[[orchestration.profiles]]
name = "python"
steps = ["Python lint", "Python format", "Python tests"]

[[orchestration.profiles]]
name = "markdown"
steps = ["Markdown links", "Markdown style"]

[[orchestration.profiles]]
name = "check"
includes = ["stubs", "python", "markdown"]
```

Step names refer to the policy's existing `[[orchestration.steps]]` definitions.
Run `--profile check` for the whole selection or select an individual profile.
The stub consumers build/install first so later tooling can inspect the
installed consumer surface. A repository without stubs omits that profile.

Includes expand depth-first in declared order, followed by the profile's direct
steps. A named step executes once, at its first occurrence, including diamond
composition. Give genuinely separate invocations separate step names. Duplicate
includes, unknown profiles/steps, empty profiles and inclusion cycles are
configuration errors before execution. No profile changes another profile's
threshold, scope or severity. Existing flat profiles retain their behavior and
JSON shape; composed results add `profiles` with the resolved profile order.
Later steps continue after a failure, and any failed step fails the aggregate.

The names above express consumer policy, not a fixed registry. There is no
plugin import, category rewrite, or automatic type detection. Package-specific
API expectations and runtime assertions remain in each stub repository.
The shared checking algorithms and their unit tests live in Alphus.

The consumer example defines independent `toml` and `json` profiles for
document syntax. Each runs only when selected; a repository can add either to
`check` when those files are part of its required gate. These document checks
are separate from `json-structure`, which analyzes JSON parsing patterns in
Python source.
JSON Lines and JSON with comments are distinct document formats. A consumer
can add separate command steps for the formats it uses; their parsers, file
patterns, and failure behavior should stay out of the Python-source
`json-structure` rule.
The C++ engines are shipped in Alphus and have an opt-in consumer profile
example at [`examples/cpp/quality-gates.toml`](../examples/cpp/quality-gates.toml).
See [C++ quality gates](CPP-QUALITY.md) for the source and artifact commands
and the build, test, and package evidence they accept. JavaScript consumers
can use the same command-step mechanism for their native build, lint, and test
profiles without changing the Python, stub, Markdown, or C++ selections.

Portable policy sections are optional when their gates are unselected. A
command-only Markdown consumer can omit `[checks]` entirely; see the
[minimal Markdown policy](../examples/markdown/quality-gates.toml) and its
[native graph config](../examples/markdown/mdrepo.toml). A selected portable
rule requires its own complete `[checks.<name>]` section. Missing selected
policies exit 2 before any profile command runs; declared malformed sections
remain invalid even when unselected. No permissive policy defaults are added.

Alphus's self-profile retains all ten established steps by including
`python-policy` and `python`, then adds TOML syntax and the three review
rules. Its Python profile also checks formatting. Composition does not remove runtime-type
enforcement; see the [migration record](TEST-GATE-MIGRATION.md) for results
at each revision and the [runtime-type contract](RUNTIME-TYPES.md).

## One pinned local and hosted entrypoint

The general [quality action](../ci/quality/action.yml) installs Alphus from the
selected action commit plus consumer-owned tool/runtime requirements, then
runs the chosen profile once:

```yaml
- uses: sheepfling/alphus/ci/quality@<REVIEWED_ALPHUS_SHA>
  with:
    requirements-file: requirements-verification.txt
    runtime-requirements-file: requirements/compatibility.txt
    config-file: quality-gates.toml
    profile: check
```

Both stub repositories pin this action and their local Alphus Git requirement
to the same immutable reviewed commit. Their verification requirements select
their existing `dev` extra plus native Markdown tools. Runtime dependencies of
the distributed stub wheels remain unchanged. The profile owns Twine selection
through its stub-verifier argv; the general action has no competing Twine flag.

For a local run, install the consumer's `requirements-quality.txt` from that
repository root, then use the same `alphus --run --profile check` command.
A policy using `includes` requires an Alphus revision supporting composition;
the immutable pin prevents accidentally using an older configuration schema.
The [stub-only action](../ci/stub-quality/action.yml) supports separate checker
and target runtimes. Both stub consumers now run `quality` (`python` plus
`markdown`) once and a separate target compatibility matrix (3.10–3.14), only
on merged PRs or manual dispatch. Local `check` continues to include all three
profiles; set `ALPHUS_TARGET_PYTHON` to select a separate target. See the
[interpreter setup](STUB-PACKAGE-CI.md#separate-checker-and-target-environments).
One native run per target is required; a checker-version matrix is insufficient.

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

Human output shows each step, normalized Alphus findings, and its exit status.
`--json` writes one summary to stdout with per-step findings, raw command
`stdout`/`stderr`, severity counts, and the configured failure threshold.
Successful command output is retained in that result. Command output is opaque:
Alphus does not infer warnings from words in arbitrary text. A nonzero native
tool exit or a launch failure remains a failed step regardless of threshold.
Invalid policy/profile selection exits 2.

## Severity and triage

Alphus findings use `error`, `warning`, or `info`, ordered from most to least
severe. The profile's `failure_threshold` defaults to `error`; `warning` also
fails on warnings, and `info` fails on every finding. A rule step may set
`severity` to classify all of that Alphus rule's findings at one level. With
no step override, each finding keeps its own severity.

```toml
[orchestration]
failure_threshold = "error"

[[orchestration.steps]]
kind = "rule"
name = "advisory line check"
rule = "line-length"
severity = "warning"
```

The threshold also applies to direct `--rule` checks when the policy defines
an orchestration section. Direct `--report` continues to print findings and
return success. Error-only human lines and the direct-rule JSON shape remain
compatible; warning and info lines carry their severity. Profile JSON adds
structured records with source, rule ID, path, line, message, and severity.
External command text remains in the raw output fields; no unsupported native
format is parsed into Alphus findings.

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

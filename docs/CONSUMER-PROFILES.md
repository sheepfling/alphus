# Consumer quality profiles

## Start with one file

Install Alphus and the native tool selected by your profile in the consumer's
development environment. Copy
[`examples/starter/quality-gates.toml`](../examples/starter/quality-gates.toml)
to the repository root, install rumdl, and run:

```sh
alphus --plan
alphus
alphus --fix-plan
```

The starter policy contains one Markdown check and its explicit fixer. It needs
only two lines: `schema_version = 1` and `tools = ["rumdl"]`. It needs no
global `[files]`, `[checks]`, `[orchestration]`, or native config file.
`quality-gates.toml` is the default policy name, the current directory is the
default root, and `check` is the default profile. `alphus --profile <name>`
selects another profile. Use `--root` and `--config` when running from another
directory or with a different filename. `--run` remains accepted in existing
scripts. `alphus --help` shows every option.

Add tools one step at a time. The
[two-tool Markdown example](../examples/markdown/quality-gates.toml) pairs
rumdl with mdrepo using `tools = ["rumdl", "mdrepo"]`. The shortcut also
accepts `ruff`, `pyright`, `pytest`, `taplo`, `prettier`, `eslint`,
`prettier-javascript`, `eslint-typescript`, `prettier-typescript`, and
`eslint-angular-template`, `html-validate`, `prettier-html`, `stylelint`, and
`prettier-css`; selection order is execution and fix order.
File-scoped lint and format steps pair a read-only
check with an explicit fixer. Pyright and pytest run without a file scope or
fixer. Alphus supplies a default `check` profile plus language profiles. The
[two-line Python example](../examples/python/quality-gates.toml) selects Ruff
lint and format, Pyright, and pytest. Ruff's file-scoped invocations honor its
native exclusions; Pyright and pytest use their project configuration. Install
the Python set with `python -m pip install -e "/path/to/alphus[python]"`
from a local checkout. The extra installs Ruff, Pyright, and pytest into
Alphus's interpreter; the repository can still pin them to narrower versions.
Install only the tools you select. Add a `[files]` inventory when selecting an
Alphus-owned `kind = "rule"` step; each file-scoped command declares its own
`files` pattern beside its argv. The [subtool guide](SUBTOOLS.md) explains
config ownership, file scope, check/fix pairing, and Markdown rule overlap.

The `tools` shortcut is for standard invocations. Add a project-specific
check without repeating those tool commands:

```toml
schema_version = 1
tools = ["rumdl"]

[[orchestration.steps]]
kind = "command"
name = "Python tests"
argv = ["{python}", "-m", "pytest"]
```

`check` runs selected tools first, then additional steps. `alphus --plan`
shows their resolved order, file matches, rollout, and fixability without
running native commands. A scoped command with no matching files is shown as
not applicable; an unscoped command still runs. Use the explicit
policy when changing a selected tool's command or file scope, defining named
profiles, or splitting steps into language files. The larger example below
demonstrates that layout. Native-tool settings stay with each tool.

The example policy at
[`examples/consumer/quality-gates.toml`](../examples/consumer/quality-gates.toml)
shows a single local profile that coordinates portable Alphus rules with
mdrepo, rumdl, Taplo, Prettier, and the Python project's own lint, type, and
test commands. The root policy includes separate files under
`examples/consumer/languages/`; each language owns its native steps and
profile. The root `check` profile orders those profiles.
Copy it into a consumer repository and adjust file scopes, thresholds, and
tool arguments there. Alphus does not add these native tools to its runtime
dependencies.

## Profiles by consumer type

A consumer selects capabilities explicitly. File extensions do not silently
activate gates. Ordinary Python repositories can combine `python` and
`markdown`; stub packages combine those with `stubs`.

| Profile | Typical checks | Policy owner |
| --- | --- | --- |
| `markdown` | Document links/graph, style/format | mdrepo and rumdl |
| `python` | Lint, formatting, project tests/tooling types | Ruff, pytest/unittest, Mypy/Pyright |
| `stubs` | Build/install, API, typed examples, stubtest, smoke | Alphus and native checkers |
| `toml` | TOML syntax and formatting | Python `tomllib` and Taplo |
| `json` | JSON syntax and formatting | Python `json` and Prettier |
| `javascript` | JS/JSX lint and format | Alphus JavaScript policy, ESLint, Prettier |
| `typescript` | Opt-in TS/TSX lint and format | ESLint, Prettier |
| `html` | Opt-in Angular or standard HTML checks | angular-eslint or HTML-validate, Prettier |
| `css` | Opt-in CSS lint and format | Stylelint, Prettier |
| `python-policy` | Optional repository-specific source conventions | Explicit Alphus source policy |

The reusable JavaScript configs and synthetic rule fixtures live in the
[`@alphus/javascript-quality` profile](../javascript/README.md). Install ESLint,
Prettier, and that package in the consumer's Node development environment. The
[JavaScript example](../examples/javascript/quality-gates.toml) selects both
scoped commands with `tools = ["eslint", "prettier-javascript"]`. Consumers
own the repository-specific `tsconfig` include paths; the shared TypeScript
base enables `allowJs`, `checkJs`, `strict`, and `noEmit`.
The package also exports opt-in React and Angular ESLint profiles. Select
`eslint-typescript` for TS/TSX files and `eslint-angular-template` for external
Angular HTML templates; the general `eslint` tool retains its JavaScript-only
scope. See the JavaScript profile guide for plugin setup and composition.
Standard HTML documents can select `html-validate` and `prettier-html`; CSS
files can select `stylelint` and `prettier-css`. Keep the generic HTML tool
off Angular template files.

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
Run `alphus` for the default `check` profile or select an individual profile.
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

Profile names express consumer policy; the `tools` shortcut recognizes only
its documented built-in recipes. Other tools use explicit command steps. There
is no plugin import, category rewrite, or automatic type detection. Package-specific
API expectations and runtime assertions remain in each stub repository.
The shared checking algorithms and their unit tests live in Alphus.

The consumer example defines independent `toml` and `json` profiles and
includes both in `check`. Their syntax steps use strict document parsers and
have no fixer: invalid content needs a human decision. Their formatting steps
use Taplo and Prettier, with `fix_argv` for explicit application. These document
checks are separate from `json-structure`, which analyzes JSON parsing patterns
in Python source.
JSON Lines and JSON with comments are distinct document formats. A consumer
can add separate command steps for the formats it uses; their parsers, file
patterns, and failure behavior should stay out of the Python-source
`json-structure` rule.
The same command-step mechanism lets a C++ or JavaScript consumer define its
own native build, lint, and test profiles without changing the Python, stub,
or Markdown selections.

## Separate language files

Put each language's command steps and profile in its own TOML file. The root
policy lists them in `orchestration_files` and defines the aggregate profile:

```toml
schema_version = 1
orchestration_files = [
  "languages/python.toml", "languages/markdown.toml",
  "languages/toml.toml", "languages/json.toml",
]

[files]
include = ["src/**/*.py", "*.md", "**/*.toml", "**/*.json"]

[orchestration]
default_profile = "check"

[[orchestration.profiles]]
name = "check"
includes = ["python", "markdown", "toml", "json"]
```

Each listed file may contain only `[[orchestration.steps]]` and
`[[orchestration.profiles]]`. Paths are relative to the root policy's directory,
must stay inside it after symlink resolution, and are loaded in list order.
Names must be unique across all files. The root owns shared `[checks]`, the
optional built-in-rule `[files]` inventory, the failure threshold, and the
aggregate profile. This is policy
composition, not a new plugin or a separate language distribution. Stream-based
policy loading accepts only self-contained policies because it has no path for
resolving fragments.

To add another language, add `languages/<name>.toml` with its check commands,
file scopes, optional `fix_argv`, and its named profiles. Add that file to
`orchestration_files`, then include the profile in `check` when it is ready to
block the aggregate. A gate under evaluation may set `rollout = "provisional"`
on its steps; it reports failures without failing the aggregate. Use an
Alphus built-in rule only when a reusable check needs code beyond a native
tool command. Put new language-specific implementations in
`alphus.gates.<language>` and keep the command runner language neutral.

Portable policy sections are optional when their gates are unselected. A
command-only Markdown consumer can omit `[files]` and `[checks]` entirely; see the
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
repository root, then run `alphus`.
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
2. **rumdl** checks Markdown style and ordinary local link targets and offers
   `fmt` for fixable rules. Its config and rule IDs remain owned by rumdl.
3. **mdrepo** checks portable repository links and the document graph. Its
   native rule IDs and optional graph settings remain owned by mdrepo. Its
   safe `fix` command is available through an explicit Alphus fix plan.
4. **Taplo and Prettier** check TOML and JSON formatting. Each formatter has
   a separate write command selected through Alphus's fix plan.
5. **Python tools** own Python lint, formatting, static typing, and tests. The
   example uses Ruff, Pyright, and pytest as configured commands. Pyright gets
   the interpreter selected by Alphus through `{python}`.
6. **Alphus orchestration** preserves the declared order, runs later steps
   after a failure, and combines each step's outcome into the profile exit
   status.

This gives each finding one owner. Do not recreate Markdown graph checks,
Markdown formatting rules, Python lint rules, or type-checker rules as Alphus
predicates. Use Alphus for reusable repository policy and as the coordinator.

## Install and run

Install Alphus and the tools named by the copied profile in the same consumer
development environment. For example, use the repository's lockfile or
development-dependency group to install mdrepo, rumdl, Taplo, Ruff, Pyright,
pytest, and a pinned local Prettier package. mdrepo must be importable by the
selected Python interpreter because the sample invokes `python -m mdrepo`;
rumdl, Taplo, Prettier, and Pyright must be on `PATH`.
The example `mdrepo.toml` enables orphan checks with `README.md` as a graph
root. Ordinary missing-target checks stay with rumdl when both tools run.

Run the whole profile from the repository root with `alphus`. From any
directory, name both repository and policy:

```sh
alphus --root /path/to/repository \
  --config /path/to/repository/quality-gates.toml
```

Run only the coordinated documentation checks with `--profile docs`. The
rumdl and mdrepo steps use Alphus's Git-aware file inventory, including tracked
and non-ignored untracked Markdown files. An empty scope reports `not_applicable`
without failing the profile; otherwise file paths are passed as separate arguments.

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

Keep Alphus selection and ordering in `quality-gates.toml`. Each native tool
reads its own config or uses its defaults. See [Composing subtools](SUBTOOLS.md)
for the rumdl/mdrepo boundary, Taplo and Prettier config locations, and the
read-only check and explicit fixer contracts. Command arrays can also call a
repository wrapper when its file scope and exit status remain clear.

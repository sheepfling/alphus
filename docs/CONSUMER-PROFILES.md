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

You can create the same policy without copying a file:

```shell
alphus --init-config starter
alphus --plan
```

Choose `python`, `markdown`, `toml`, `json`, `javascript`, or `polyglot` instead
of `starter` to generate a different bundle. Extend a recipe with repeatable
`--add-language` and `--add-tool` options; `--init-config custom` starts with
only the selections you supply. `--config` selects the output path under
`--root`. Alphus validates the generated policy before writing it and refuses
to replace a file unless `--overwrite-config` is supplied. Edit the generated
TOML for project-specific rules and native tool overrides, then use
`alphus --plan` to inspect the resolved checks.

The starter policy contains one Markdown check and its explicit fixer. It needs
only two lines: `schema_version = 1` and `tools = ["rumdl"]`. It needs no
global `[files]`, `[checks]`, `[orchestration]`, or native config file.
`quality-gates.toml` is the default policy name, the current directory is the
default root, and `check` is the default profile. `alphus --profile <name>`
selects another profile. Use `--root` and `--config` when running from another
directory or with a different filename. `--run` remains accepted in existing
scripts. `alphus --help` shows every option.

For common multi-language setups, select bundles instead of remembering each
native tool name:

```toml
schema_version = 1
languages = ["python", "markdown", "toml", "json", "javascript"]
```

This expands to the standard Python, Markdown, TOML, JSON, and JavaScript
profiles. The compact [polyglot example](../examples/polyglot/quality-gates.toml)
can be copied as a starting point. Plain TypeScript, HTML, and CSS also have
bundles. C++ remains project-specific because its build, test, and artifact
commands depend on the repository's compiler and build setup.

The default bundles are Python (Ruff, Pyright, pytest), Markdown (rumdl,
mdrepo), TOML (Taplo), JSON (Prettier), JavaScript and TypeScript (ESLint,
Prettier), plain HTML (HTML-validate, Prettier), and CSS (Stylelint, Prettier).
Install and pin the selected tools in the consumer environment and configure
each tool for the repository's source layout. The Python bundle runs the
project's normal Ruff, Pyright, and pytest configuration. Select individual
`tools` for a smaller set, or add them after `languages` for an opt-in check:

```toml
schema_version = 1
languages = ["python", "markdown", "typescript"]
tools = ["eslint-angular-template"]
```

Bundles run first in listed order, followed by individual tools in listed
order. Repeating a tool already selected by a bundle is a configuration error.
The `html` bundle checks ordinary HTML documents. For Angular templates,
select `eslint-angular-template` instead of the `html` bundle. A repository
with both kinds of HTML needs explicit file scopes to keep them separate.

The short form composes with project profiles and split language files. Keep
C++ checks in a local fragment, then include that profile in the root `check`:

```toml
schema_version = 1
languages = ["python", "markdown", "toml", "json", "javascript"]
orchestration_files = ["languages/cpp.toml"]

[orchestration]

[[orchestration.profiles]]
name = "check"
includes = ["cpp"]
```

The generated native checks run first, followed by included project profiles
and any additional steps in their declared order. When a custom `check` profile
is declared, the generated `native` profile groups the selected tools; each
language also gets its own profile. Add `[checks]` and `[files]` when selecting
Alphus portable rules or repository-specific thresholds.

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

FastAPI consumers can add an opt-in profile that layers Ruff's FAST, selected
ASYNC, annotation, and security rules over their existing Ruff settings, plus
Alphus's current FastAPI style advisory. The
[FastAPI quality guide](FASTAPI-QUALITY.md) documents the coverage boundary and
provides a copyable example.

The [common lint intent map](COMMON-LINT-INTENTS.md) compares native naming,
unused-symbol, and unreachable-code rules across Python, C/C++, JavaScript, and
TypeScript. It keeps rule selection and configuration with each consumer tool.

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

`check` runs selected tools first, then additional steps. It can also extend
named profiles while retaining that native-tool group. `alphus --plan`
shows their resolved order, file matches, rollout, and fixability without
running native commands. A scoped command with no matching files is shown as
not applicable; an unscoped command still runs. Use explicit command steps
when changing a selected tool's command or file scope. Native-tool settings
stay with each tool.

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
activate gates. An extensions list contains literal suffixes, so use
".c", ".cpp", and ".cxx" as separate entries for several C++ spellings.
Path include and exclude entries are POSIX globs; regex alternation such as
".(c|cpp|cxx)" is not supported. The config validator rejects glob and regex
syntax in extensions. Ordinary Python repositories can combine `python` and
`markdown`; stub packages combine those with `stubs`.

| Profile         | Typical checks                                      | Policy owner                              |
| --------------- | --------------------------------------------------- | ----------------------------------------- |
| `markdown`      | Document links/graph, style/format                  | mdrepo and rumdl                          |
| `python`        | Lint, formatting, project tests/tooling types       | Ruff, pytest, Pyright/Mypy                |
| `stubs`         | Build/install, API, typed examples, stubtest, smoke | Alphus and native checkers                |
| `toml`          | TOML syntax and formatting                          | Python `tomllib` and Taplo                |
| `json`          | JSON syntax and formatting                          | Python `json` and Prettier                |
| `javascript`    | JS lint, format, tests, and types                   | ESLint, Prettier, app commands            |
| `typescript`    | Opt-in TS/TSX lint and format                       | ESLint, Prettier                          |
| `html`          | Opt-in Angular or standard HTML checks              | angular-eslint or HTML-validate, Prettier |
| `css`           | Opt-in CSS lint and format                          | Stylelint, Prettier                       |
| `python-policy` | Optional repository-specific source conventions     | Explicit Alphus source policy             |

Path-discovery findings now use semantic categories and complaints: implicit
roots are portability issues, import-path mutation is architecture, and raw
path or URL string comparisons are correctness. Consumers filtering the old
`portability/implicit-path-discovery` ID should switch to these specific tags.

The reusable JavaScript configs and synthetic rule fixtures live in the
[`@alphus/javascript-quality` profile](../javascript/README.md). Install ESLint,
Prettier, and that package in the consumer's Node development environment. The
[JavaScript example](../examples/javascript/quality-gates.toml) selects both
scoped commands with `tools = ["eslint", "prettier-javascript"]`. Consumers
own the repository-specific `tsconfig` include paths; the shared TypeScript
base enables `allowJs`, `checkJs`, `strict`, and `noEmit`. Alphus invokes ESLint
and Prettier through `npm exec --no`, using installed local tools only.
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
The same command-step mechanism lets a C++ consumer define its own native
build, lint, and test profile without changing the Python, stub, or Markdown
selections.

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

Alphus's self-profile coordinates portable Python rules, Python tooling,
TOML and JSON syntax, Git ignore policy, and review rules under one `check`
profile. The JavaScript profile runs in its own CI job after npm setup.
Language-specific pieces remain available as named profiles.
Composition does not remove runtime-type enforcement; see the
[migration record](TEST-GATE-MIGRATION.md) for results at each revision and the
[runtime-type contract](RUNTIME-TYPES.md).

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
rumdl, Taplo, and Pyright must be on `PATH`. The Prettier recipes use
`npm exec` to resolve the consumer's local package.
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

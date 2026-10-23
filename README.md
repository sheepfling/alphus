# Alphus

Alphus is a policy-driven set of source checks for Git repositories, named for
the river Heracles put to work on the Augean stables.
The package keeps rule implementations independent of a project's layout and
loads file scopes, thresholds, and repository conventions from TOML.

## Source layout

`src/alphus/gates/` groups the checks by theme: `source` for source and
launcher analysis, `review` for advisory rules, `repository` for architecture
and packaging policy, `hygiene` for size and duplicate-helper rules,
`stubs` for installed stub-package verification, and `python` for
package-import smoke and compatibility-import removal checks. Portable
themes own a `runners.py` that binds selectors to validated policy.

`src/alphus/contracts/` owns shared finding and diagnostic types.
`src/alphus/policy/` owns validated settings and the built-in rule catalog.
`src/alphus/execution/` owns rule dispatch, results, and profiles.
`src/alphus/support/` contains shared file inventory, data access, AST queries,
and platform probes. The root has only `config.py` and `cli.py` as public
boundaries, plus package metadata and the module entry point.

`src/alphus_stub_quality/` contains the small Python 3.10 audit helpers copied
into isolated target environments. It ships in the same Alphus wheel because
the Python 3.10 target cannot import the Python 3.11+ checker. See the
[documentation map](docs/README.md) for the guides and the
[architecture guide](docs/ARCHITECTURE.md) for the dependency map.

## Install

Use Python 3.11 through 3.15:

```sh
python -m pip install .
```

Run that command from this directory. The package depends on Pydantic 2,
`packaging`, Typer, and Rich, and installs the `alphus` command.
The same install also provides `alphus-stub-quality` and
`alphus-typing-fixtures`; there is no separate stubs package to install.

## Develop Alphus

Install the package and its Python quality tools in your active
environment:

```sh
python -m pip install -e ".[python]"
```

Run the self-check profile from the repository root. It applies Alphus's
portable and review rules to this source tree, validates TOML, then runs Ruff
lint/format, strict Pyright, and the package tests:

```sh
alphus
```

For the installed-wheel version of this check, including the current self-profile
scope and exclusions, see [Self-checking Alphus](docs/SELF-CHECK.md). The
`review` profile also selects [the review checks](docs/REVIEW-CHECKS.md) alone.
Those include opt-in Pydantic and FastAPI source sniffers with consumer-owned
scope and error-code vocabulary.
See [version support](docs/VERSION-SUPPORT.md) for the checker Python range,
dependency bounds, stub targets, and native tool ownership.

## Use from another repository

Until the project chooses a package index, consumers can install from a local
source checkout, pin a Git commit, or build and distribute the wheel through an
existing package channel. For a reproducible Git dependency, pin an immutable
commit rather than a branch name:

```sh
python -m pip install \
  "alphus @ git+https://github.com/sheepfling/alphus.git@<commit-sha>"
```

## Web quality package

This repository also provides an installable JavaScript policy package at
[`javascript/`](javascript/README.md). It exports shared ESLint, Prettier, and
strict JavaScript type-check settings with consumer-neutral fixture tests.
Install it from an immutable Alphus Git commit and use the `eslint` and
`prettier-javascript` tools in `quality-gates.toml`. The profile supports
`.js`, `.jsx`, `.mjs`, and `.cjs`; consumers still select their own source and
test directories in their TypeScript configuration. Alphus resolves ESLint and
Prettier through `npm exec --no`, using installed local packages.
Opt-in React and Angular ESLint exports, TypeScript and Angular template
commands, standard HTML validation, CSS linting, and HTML/CSS formatting are
documented in the JavaScript package guide.

For local development, point the other repository's development environment at
the standalone package directory:

```sh
python -m pip install -e /path/to/alphus
```

For a Markdown consumer, add this `quality-gates.toml` to its repository root:

```toml
schema_version = 1
tools = ["rumdl"]
```

Install rumdl in that repository's development environment, then run `alphus`
from the root. `alphus --profile markdown` selects the generated language
profile. `alphus --plan` previews the resolved steps and file matches;
`alphus --fix-plan` shows available fixers. The selected native
tool keeps its own configuration. A Python repository can start with
[`examples/python/quality-gates.toml`](examples/python/quality-gates.toml):
`tools = ["ruff", "pyright", "pytest"]`. Install the Python bundle in the
consumer's development environment from a local checkout:

```sh
python -m pip install -e "/path/to/alphus[python]"
```

For a pinned Git install, use
`"alphus[python] @ git+https://github.com/sheepfling/alphus.git@<commit-sha>"`
in the install command above. Ruff supplies lint and format steps;
Pyright and pytest use the repository's native settings. Add `mdrepo`, `taplo`,
or `prettier` only when those tools are installed and needed. Add a custom
`[[orchestration.steps]]` beside `tools` when the repository needs another
check. For a quick multi-language start, select bundles with one `languages`
line:

```toml
schema_version = 1
languages = ["python", "markdown", "toml", "json", "javascript"]
```

This expands to generated language profiles plus a coordinated `check`.
Plain TypeScript, HTML, and CSS have bundles too. Add `tools = [...]` for
individual opt-in checks alongside the bundles; for example, Angular template
lint can accompany the TypeScript bundle without selecting standard HTML
validation. Custom profiles and `orchestration_files` compose with those
bundles. C++ build and artifact commands remain project-specific. The
[consumer guide](docs/CONSUMER-PROFILES.md) covers profile composition and
tool-command customization.

From another directory, pass the repository and policy paths explicitly:

```sh
alphus --root /path/to/other-repository \
  --config /path/to/other-repository/quality-gates.toml \
  --rule python-style
```

For a non-editable install, build the checker wheel without building its
dependencies:

```sh
python -m pip wheel --no-deps --wheel-dir dist \
  .
```

Install that wheel through the repository's normal development dependency
workflow, which should also install its declared runtime dependencies.
Consumers depend on `alphus`; they do not copy its source or import
application packages from the repository that publishes the policy.
See the [package architecture](docs/ARCHITECTURE.md) for the reusable
checker, policy, and orchestration boundaries. The
[consumer profile guide](docs/CONSUMER-PROFILES.md) describes language-specific
policy files and explicit composition of Markdown, TOML, JSON, Python, and
stub-testing profiles. Start with its one-file example and add native tools as
needed. The [subtool guide](docs/SUBTOOLS.md) explains how Alphus coordinates
rumdl, mdrepo, Taplo, and Prettier. The
[shared stub-package CI action](docs/STUB-PACKAGE-CI.md) hosts reusable
PEP 561 build, checker, and runtime-compatibility gates without adding an
Alphus dependency to published stub packages. The
[extension and diagnostics proposal](docs/EXTENSIBILITY.md) records a staged
design for categories, shared findings, and future third-party rules. The
[installability report](docs/INSTALLABILITY.md) records the current wheel,
Python-version, and distribution evidence.

## Toolchain ownership

Python is the top-level orchestrator for repositories in any stack, including
C++, Java, JavaScript, and embedded firmware. A validated TOML policy selects
the rules, command arguments, working directories, and ordered profiles. The
Python runner owns execution order and the overall exit status. Compilers,
build systems, and language-specific test tools retain ownership of their
checks and run as subprocesses. npm and Node.js are needed only for configured
Node-based checks, not just because a repository contains JavaScript.

## Python AST query API

`alphus.support.source_scanning` provides small, policy-free queries over
an already parsed Python `ast.Module`. The caller owns file discovery, parsing,
scope, diagnostic wording, and the decision to reject a pattern. The query module
does not load a repository, import inspected source, or read files.

| API                                 | Contract                                                      |
| ----------------------------------- | ------------------------------------------------------------- |
| `ImportAliases`                     | Frozen record with read-only module and symbol mappings       |
| `import_aliases`                    | Collect import spellings, including nested imports            |
| `canonical_expression_name`         | Resolve a dotted expression using those mappings              |
| `qualified_call_lines`              | Find calls to one canonical function or class                 |
| `qualified_reference_lines`         | Find matching Name/Attribute occurrences; sorted unique lines |
| `registry_decorated_function_lines` | Find top-level sync/async callbacks for a registry factory    |

For example, a stored class-method reference is visible even without a call:

```python
import ast

from alphus.support.source_scanning import qualified_reference_lines

tree = ast.parse("from datetime import datetime as Clock\nparse = Clock.fromisoformat\n")
assert qualified_reference_lines(tree, "datetime.datetime.fromisoformat") == [2]
```

These are syntactic queries. Import collection uses one module-wide mapping;
it does not prove lexical bindings or account for shadowing and rebindings.
Relative imports receive no package context. References include callable
values, annotations, and decorators, but do not follow a variable after an
assignment or evaluate dynamic attribute access. Callers must account for
these limits before treating a match as a policy violation. The recovered
call and registry queries retain their existing result order; the reference
query explicitly sorts and deduplicates its line results.

## Run a check

Pass the checkout and its policy file explicitly:

```sh
alphus --root /path/to/repository \
  --config /path/to/quality-gates.toml \
  --rule file-size
```

Run the policy's default profile from the repository root with `alphus`. To
select another profile from elsewhere:

```sh
alphus --root /path/to/repository \
  --config /path/to/quality-gates.toml \
  --profile check
```

Use `--fix-plan --profile check` to see which selected steps declare a fixer.
Applying one requires `--apply-fixes --fix-step "Step name"`; the ordinary
check never edits files. See [fix plans](docs/FIXES.md) for the current
fixability inventory and the file-scoped command contract.

Profiles can mix portable rules with native tools configured as argument
arrays. A policy that has no Node-based command steps does not require npm or
Node.js. A command step may select a scoped file inventory with a `files`
policy and a standalone `{files}` argument. The runner expands it to separate
argument values for tracked and non-ignored untracked files, applying the step's
include and exclude patterns. A scoped command passes when no files match and
does not start the native tool.

For a larger repository, list `orchestration_files` at the top of the root
policy and put each language's steps and profile in a separate TOML file.
The root profile composes them in the required order; see the
[consumer example](examples/consumer/quality-gates.toml). Check commands
remain read-only, while `fix_argv` lets a consumer declare a separate,
file-scoped write command for a formatter or linter.

```toml
[[orchestration.steps]]
kind = "command"
name = "Format Python"
argv = ["ruff", "format", "--check", "{files}"]
files = { include = ["**/*.py"], exclude = ["**/vendor/**"] }
```

Add `--verbose` to write diagnostics to stderr. Human reports use Rich by
default; pass `--output plain` for unstyled text. `--json` emits one plain JSON
value on stdout and is independent of the human output style.

The generic Markdown checks include configured line-length and hard file-size
limits. Python files support those checks plus the AST-based policy rules.
The `comment-markers` rule can reject configurable temporary-work words in
Python, TOML, JavaScript, TypeScript, C/C++, and Java comments. It ignores
strings and reports file and line; add its `[checks.comment_markers]` policy
and a rule step to a profile to enable it. Alphus selects this rule in its own
`check` profile.
Python comments use Python's tokenizer. The JavaScript and C/C++ scanner is
lexical; it does not fully parse regex literals or template interpolation, so
native language lint remains useful alongside this gate.
Markdown link checkers and formatters can be configured as command steps with
their native arguments and file patterns; reusable support stays in this
package, while each repository supplies its own tool selection and scope.

Available rules are `file-size`, `line-length`, `json-structure`,
`output-escaping`, `path-discovery`, `shared-utilities`, `python-style`,
`runtime-types`, `cli`, `script-policy`, `module-roles`, `package-boundaries`,
`dependency-locks`, `repository-layout`, `git-ignores`, and `git-history`. Package boundaries also check
the configured architecture graph, metadata versions, and callable registry.
The architecture graph policy accepts `syntax = "flowchart"` (the default)
or `syntax = "architecture"` for Mermaid's `architecture-beta` diagrams.
Its edge comparison handles directed links in the selected syntax; diagrams
using other Mermaid link forms need a matching checker extension.
Module roles enforce configured import, call, definition, and module-level
assignment boundaries for audited composition, operation, contract, and adapter
modules. Assignment rules catch callable and type aliases even inside module
control-flow branches while ignoring local and class attributes. Import patterns
can cover module families such as route adapters without enumerating each name.
Repository layout checks configured paths, tracked files, and instruction
routers. `--report` prints findings with a successful exit status; `--json`
emits machine-readable findings.

The root must be a Git working tree. Source checks receive files selected by
`[files]` include and exclude patterns. The inventory includes tracked and
non-ignored untracked files, and skips symlinks and paths that escape the root.
Git-backed rules read ignore policy, the index, or reachable history directly;
they need `[checks.git]` but no `[files]` inventory. See the
[repository hygiene guide](docs/REPOSITORY-HYGIENE.md) for scope and cadence.

## Minimal policy

This policy enables the baseline file, line, JSON, escaping, and path checks.
Other rules become available when their corresponding `[checks.*]` sections
are added.

```toml
schema_version = 1

[files]
include = ["**/*.py"]
exclude = []

[checks.file_size]
code_extensions = [".py"]
code_limit = 3000
hard_limit = 5000
initializer_name = "__init__.py"
initializer_limit = 100

[checks.line_length]
exclude = []

[checks.line_length.limits]
".py" = 100

[checks.json_structure]
extensions = [".py"]
exclude = []

[checks.output_escaping]
extensions = [".py"]
exclude = []

[checks.path_discovery]
extensions = [".py"]
exclude = []
inspection_exclude = []
```

Configuration is validated before scanning. Unknown fields, unsafe file
patterns, malformed source suffixes, and invalid rule settings fail early.
Source suffixes are consumer-configurable; Python AST rules remain restricted
to `.py`, while the source text heuristics use JavaScript-compatible syntax on
other configured extensions. Policy collections are immutable after loading.

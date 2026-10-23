# Alphus architecture

Alphus is a Python package for running policy-driven quality checks
against Git repositories. Each consumer owns its TOML policy. The package
contains reusable policy models, file inventory, checkers, typed findings,
renderers, and command orchestration; it does not define a project's paths,
package graph, thresholds, or default check set.

## Execution model

The caller supplies the repository root and policy path. The Python CLI
validates the policy, selects the requested rule or ordered profile, gathers
the configured file inventory, and combines results into one exit status.
Native language tools retain their own checks and run as configured argument
vectors. Python owns ordering and aggregation without importing compiler,
Java, or Node ecosystems.
Consumer policies can split orchestration steps and profiles into separate
language TOML files through root-level `orchestration_files`. The loader
combines them before validating unique names and profile references. The root
policy owns shared file inventory and gate settings; language files only add
steps and profiles.

Alphus has two gate shapes. A portable rule inspects selected repository files
and returns Alphus findings. A workflow gate coordinates tools and environments
and enters a profile as a command step, with its exit status and native output
retained by the orchestrator. The installed stub-package verifier is a workflow
gate implemented in `alphus.gates.stubs`; it builds and installs a consumer
wheel, runs typing fixtures, and checks runtime compatibility. Its console
commands ship in the same `alphus` distribution. The separate
`alphus_stub_quality` import package holds only Python 3.10-compatible audit
helpers copied into the isolated target environment. The target cannot import
`alphus` because the main checker requires Python 3.11 and its dependencies.
Both import packages ship in one wheel; the sibling is not a separate
distribution or framework.
Keep language-specific workflow gates under `alphus.gates.<language>` in the
same distribution while they share a release cycle and dependency set.
Independent namespace distributions would add installation and compatibility
coordination; introduce them only when a language gate needs its own release
cycle or substantial optional dependencies. The core profile runner remains
language neutral.

## Package map

- `alphus.support` owns shared file inventory, contained-file/JSON access,
  AST name resolution, and platform probes. These utilities do not emit
  findings or register rules.
- `alphus.gates.review` owns numeric-literal, test-quality, and input-contract
  checkers. Its `runners.py` binds their selectors to validated policies.
- `alphus.gates.source` owns portable source and launcher checks for Python,
  JavaScript, and JSON. Its `runners.py` binds these selectors to validated
  policies. Language-specific analysis remains inside each checker.
- `alphus.gates.repository` owns architecture, package, dependency-lock, and
  repository-layout checks. Its runner mapping adds related graph, version,
  and callable-registry findings to the package-boundary selector.
- `alphus.gates.hygiene` owns file-size, line-length, comment-marker, and
  shared-utility checks. Comment markers use language-aware comment scanning
  while retaining one portable finding contract.
- `alphus.gates.stubs` owns the installed stub-package workflow and fixture
  controller.
- `alphus.gates.python` owns the installed-package import smoke workflow
  and the [compatibility-import removal gate](COMPATIBILITY-IMPORTS.md).
  The first maps every Python file to an import name and imports it from
  the installed package; the second requires dated plans for forwarding
  modules.
- `alphus.contracts` owns finding records, severity, priority, and normalized
  diagnostic types shared by policies and execution.
- `alphus.policy` owns validated policy models and the built-in selector
  catalog. It does not import execution or gate implementations.
- `alphus.execution` owns rule dispatch, normalized results, profile planning,
  native command execution, explicit fix plans, and exit status.
- `alphus.config` and `alphus.cli` are the stable public configuration and
  command boundaries at the package root.
- `alphus_stub_quality` contains only the audit helpers copied into the Python
  3.10 target environment.

Import checker implementations from their owning `alphus.gates.<theme>`
package and shared mechanics from `alphus.support`. Former root module
forwarders have been removed. For example, replace `alphus.numeric_literals`
with `alphus.gates.review.numeric_literals`, `alphus.python_style` with
`alphus.gates.source.python_style`, and `alphus.repository_layout` with
`alphus.gates.repository.repository_layout`. The `alphus` package still exports
its documented core configuration, finding, inventory, and checker functions.

The internal import paths changed with this layout:

| Former path | Owning path |
| --- | --- |
| `alphus.config_architecture` | `alphus.policy.architecture` |
| `alphus.config_base` | `alphus.policy.base` |
| `alphus.config_orchestration` | `alphus.policy.orchestration` |
| `alphus.config_repository` | `alphus.policy.repository` |
| `alphus.config_review` | `alphus.policy.review` |
| `alphus.config_sources` | `alphus.policy.sources` |
| `alphus.rule_catalog` | `alphus.policy.catalog` |
| `alphus.findings` | `alphus.contracts.findings` |
| `alphus.rule_execution` | `alphus.execution.dispatch` |
| `alphus.rule_results` | `alphus.execution.results` |
| `alphus.orchestration` | `alphus.execution.orchestration` |

The `alphus.config` model and loader imports and the `alphus.cli` command entry
point remain at the package root.

Node and npm are optional. A repository that configures no Node-based command
does not need `package.json`, Node.js, or npm. Consumers may keep established
commands in another launcher, such as `npm run check`, while delegating the
actual profile to `alphus`.

## Policy and checker boundaries

Use TOML for consumer-owned file patterns, exclusions, limits, package edges,
and command steps. Validate it into named models before execution. Keep
language semantics in versioned checker code rather than executable snippets
in policy. A command may declare a file inventory and use `{files}` as one
complete argv item; the runner expands that item into separate
repository-relative arguments. Empty scopes pass without starting the command.

Each checker receives an explicit root, validated rule policy, and selected
files. It returns typed findings or a typed report; it does not print, start
processes, or discover a checkout from the current directory or module path.
Policy models are grouped under `alphus.policy` by source scanning,
architecture, repository metadata, and orchestration. `alphus.config`
re-exports the public models and TOML loader.
`alphus.policy.catalog` records each built-in rule's required policy field and
JSON output shape. Policy validation and profile diagnostic decoding share
that catalog. Theme packages own their runner mappings;
`alphus.execution.dispatch` composes the built-in checker dispatch, and
`alphus.execution.results` validates each result against its declared shape
while normalizing diagnostics. The package tests require
both registries to cover every public rule selector. The CLI retains rendering
adapters because some older rules have distinct direct-command output formats.
`RuleEvaluation` keeps the checker output, normalized diagnostics, and threshold
decision together before rendering. Direct CLI modes serialize that result to
their established text or JSON formats; profiles consume its diagnostics
directly, without parsing the CLI's own output.
Selected command steps can separately declare a file-scoped `fix_argv`.
The [fix plan](FIXES.md) lists those commands without running them; applying
fixes requires explicit step names and remains separate from profile checks.
The Python structure rule rejects uppercase module constants initialized
with mutable list, dict, or set values. Constant lookup tables use a read-only
`Mapping` view, while fixed sequences and membership sets use tuples and
`frozenset`. Lowercase module caches remain explicit mutable state.

The package-boundary rule also validates console and GUI script entry-point
reference syntax in project metadata, so malformed targets fail the self-check
before an editable or wheel installation reaches the build backend. It does not
import those targets or claim that they exist at runtime.
Module-role policies can name forbidden module-level assignments separately
from functions and classes. The assignment scanner follows module-level
control-flow branches and stops at function, class, and lambda scopes, so a
provider alias cannot hide in a conditional or be confused with a local name.
The CLI owns rendering, subprocess calls, report-only behavior, and exit
status. Structured findings carry typed severity and provenance; profile
thresholds decide whether an Alphus rule finding fails the run. Native command
output is retained verbatim and nonzero exits remain failures. Use argument
arrays for native tools, and keep their working directories within the
configured repository root. Consumers can configure
Markdown link and formatting tools as ordinary command steps without adding
repository-specific code to the package.

For a coordinated consumer example that assigns Markdown graph checks to
mdrepo, Markdown lint and fixes to rumdl, TOML formatting to Taplo, JSON
formatting to Prettier, and Python lint, typing, and tests to their native
tools, see [consumer quality profiles](CONSUMER-PROFILES.md).
This keeps upstream rule ownership intact while Alphus aggregates profile
status.

The [extension and diagnostics proposal](EXTENSIBILITY.md) records how
categories, findings, and future third-party hooks could evolve while current
selectors remain stable.

The default profile runs when `alphus` is invoked in a repository with
`quality-gates.toml`; `--profile` selects a different profile. Review command
steps before running a policy from a repository that is not trusted, because
those steps execute the configured programs.

## Static source-scanner resolution

`ImportAliases(modules, symbols)` remains valid. Both maps remain read-only; they
now contain surviving module bindings rather than imports gathered from every
nested scope. The optional keyword-only `resolution` context stores read-only
expression resolutions for the original AST. A stored `None` is an explicitly
unresolved binding and never falls back to the module maps. For an independently
parsed expression, `canonical_expression_name` still expands the module maps;
that compatibility path cannot prove lexical binding or execution order.

The call and reference scanners resolve import aliases at each syntax occurrence.
Nested imports stay in their scope; function/lambda parameters and function-local
bindings shadow enclosing names. Assignments, deletes, reimports, loop/with/match
bindings and explicit attribute writes invalidate the affected alias. Store
syntax is not reported as a reference. Comprehension targets stay local, and
methods skip class locals for unqualified lexical lookup. Deferred function
bodies use only stable imports from enclosing scopes, suppressing uncertain
bindings that are reassigned elsewhere in that scope.

Control-flow joins retain a binding only when alternatives agree. Loops and
exception paths may leave names unresolved; the scanner does not prove branch
reachability, iteration counts, exceptions or invocation order. Star imports and
relative imports cannot establish a canonical absolute target. Explicit
`global`/`nonlocal` reads can use a stable enclosing import; writes are handled
within the scanned body but are not propagated through callers.

Stored callable references are still reported at the original imported name,
without tracing their later assigned aliases. The registry scanner separately
recognizes the returned decorator from a proven factory call and invalidates it
on rebinding. Only top-level decorated functions are returned by that API.

These are import-origin checks, not Python execution proofs. They do not follow
arbitrary assignments, return values, `getattr`, `exec`, monkeypatching, dynamic
imports, external state changes or interprocedural writes. Deferred generator
execution and other timing-sensitive cases may be suppressed conservatively;
absence of a finding does not prove that a runtime call cannot reach the target.

The contextual resolutions belong to the original AST snapshot. Recompute
`import_aliases` after changing AST nodes; identities retained in the context do
not track subsequent edits. The lexical model covers ordinary module, function,
class and comprehension scopes. Python 3.12 type-parameter/annotation scopes and
`type` aliases are not modeled; results for those constructs are not complete
binding analysis.

## Migration and verification

Migrate one checker at a time. Keep the consumer's command name as an adapter
until the old and new implementations return the same normalized findings for
the same repository snapshot. Do not add baselines or path suppressions just
to hide existing findings.

Keep two verification layers:

- Generic package tests use small temporary Git repositories with no
  consumer-specific names, paths, or package layout. Cover accepted and
  rejected inputs, invalid policy, and stable finding locations.
- Consumer tests verify that its policy selects the intended files and rules,
  its wrappers retain their public commands and output modes, and its
  normalized findings match the previous gate sequence.

Build and install the wheel outside the source checkout, then run it against a
generic fixture. A Python-only profile must work without Node or npm. Native
tool dependencies belong to the consumer's development setup, not to the
`alphus` runtime dependencies.

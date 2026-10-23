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

Alphus has two gate shapes. A portable rule inspects selected repository files
and returns Alphus findings. A workflow gate coordinates tools and environments
and enters a profile as a command step, with its exit status and native output
retained by the orchestrator. The installed stub-package verifier is a workflow
gate implemented in `alphus.gates.stubs`; it builds and installs a consumer
wheel, runs typing fixtures, and checks runtime compatibility. Its console
commands ship in the same `alphus` distribution. The separate
`alphus_stub_quality` import package holds only Python 3.10-compatible audit
helpers copied into the isolated target environment, plus legacy import
adapters. This runtime boundary is why the helper package is separate; it is
not a second distribution or a second quality framework.
Keep language-specific workflow gates under `alphus.gates.<language>` in the
same distribution while they share a release cycle and dependency set.
Independent namespace distributions would add installation and compatibility
coordination; introduce them only when a language gate needs its own release
cycle or substantial optional dependencies. The core profile runner remains
language neutral.

## Package map

- `alphus.support` owns shared file inventory, contained-file/JSON access, and
  AST name resolution. These utilities do not emit findings or register rules.
- `alphus.gates.review` owns numeric-literal, test-quality, and input-contract
  checkers. Its `runners.py` binds their selectors to validated policies.
- `alphus.gates.source` owns portable source and launcher checks for Python,
  JavaScript, and JSON. Its `runners.py` binds these selectors to validated
  policies. Language-specific analysis remains inside each checker.
- `alphus.gates.stubs` owns the installed stub-package workflow and fixture
  controller.
- `alphus.config*`, `alphus.rule_catalog`, `alphus.rule_execution`, and
  `alphus.rule_results` own validated policy, selector catalog, runner
  composition, and normalized results.
- `alphus.cli` and `alphus.orchestration` own text/JSON presentation, profile
  planning, native command execution, and exit status.
- `alphus_stub_quality` contains small audit helpers copied into the Python
  3.10 target environment.

Existing root imports such as `alphus.numeric_literals`, `alphus.python_style`,
and `alphus.source_scanning` remain compatibility modules. New code in a gate
theme imports shared mechanics from `alphus.support` directly. Repository and
general hygiene checkers still live at the package root and can move by theme
without changing their selectors or public result shapes.

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
Policy models are grouped by source scanning, architecture, repository
metadata, and orchestration in separate modules. `alphus.config` re-exports
those models as the compatibility import surface.
`alphus.rule_catalog` records each built-in rule's required policy field and
JSON output shape. Policy validation and profile diagnostic decoding share
that catalog. Theme packages own their runner mappings;
`alphus.rule_execution` composes the built-in checker dispatch, and
`alphus.rule_results` validates each result against its declared shape while
normalizing diagnostics. The package tests require
both registries to cover every public rule selector. The CLI retains rendering
adapters because some older rules have distinct direct-command output formats.
`RuleEvaluation` keeps the checker output, normalized diagnostics, and threshold
decision together before rendering. Direct CLI modes serialize that result to
their established text or JSON formats; profiles consume its diagnostics
directly, without parsing the CLI's own output.
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
mdrepo, Markdown formatting to rumdl, and Python lint, typing, and tests to
their native tools, see [consumer quality profiles](CONSUMER-PROFILES.md).
This keeps upstream rule ownership intact while Alphus aggregates profile
status.

The [extension and diagnostics proposal](EXTENSIBILITY.md) records how
categories, findings, and future third-party hooks could evolve while current
selectors remain stable.

Profiles execute only when explicitly selected with `--run`. Review command
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

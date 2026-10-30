# Python CLI policy

Python command analysis lives in `alphus.gates.languages.python.cli_policy`;
`alphus.gates.languages.javascript.cli_policy` discovers JavaScript CLI
endpoints. The source-level adapter in `alphus.gates.source.cli_policy`
applies the configured source inventory and combines both languages’
findings. Shared finding types live in `alphus.contracts.cli_policy`.

The `cli` check covers command wiring and machine-output contracts. It checks
that each recognized Typer command exposes the configured JSON and verbose
options, reaches a configured JSON serializer, and uses the selected CLI
framework. Options and serializers are resolved within each command and its
reachable local helpers; another command's option or an unused helper cannot
satisfy the check.

The Python analyzer targets Typer command wiring and optional Rich presentation;
it is not a framework-neutral CLI smell detector.

Presentation is a separate project policy. Alphus does not infer that every
consumer must use Rich or expose a plain/Rich selector. An absent preference
does not create a presentation finding. When a project adopts a renderer or a
style selector, it can enforce that choice or roll it out as an advisory:

```toml
[checks.cli.python]
renderer_enforcement = "advisory" # off, advisory, or enforce
rich_package = "rich"
rich_calls = ["Console", "print"]

output_style_enforcement = "enforce" # off, advisory, or enforce
style_option = "--output-style"
rich_output = "rich"
plain_output = "plain"
```

`renderer_enforcement` applies only when a `rich_package` and its `rich_calls`
are configured. `output_style_enforcement` checks the selected `style_option`
and its accepted plain/Rich values. Advisory findings have warning severity;
they do not fail a run whose failure threshold is `error`, and can be promoted
by an orchestration profile that selects a `warning` threshold.

For compatibility, a legacy policy with explicit `rich_package` and
`rich_calls` migrates to renderer enforcement. A legacy policy with explicit
`output_option`, `rich_output`, or `plain_output` migrates to style enforcement;
`output_option` maps to the new `style_option` field. If those selector fields
were only implicit model defaults, style enforcement migrates to `off`. New
configurations should use `style_option` and set the enforcement mode directly.
The root `quality-gates.toml` opts Alphus itself into its current Rich renderer
and `--output` format selector explicitly.

The static check resolves explicit Typer option declarations and inferred
options from parameter defaults. It recognizes style values declared with
`Literal`, including `Literal` aliases wrapped in `Annotated`. It does not
evaluate enums, Click choices, or runtime validators. A path or file parameter
named `--output` is not treated as a style selector merely because its name or
an unrelated string matches. These checks do not replace runtime tests of the
actual output bytes or rendering behavior.

Renderer evidence is command scoped. The analyzer follows reachable local
helpers and uniquely resolved imports within the source inventory it was given.
It recognizes import aliases, Rich `Console` parameters with a Rich type
annotation, local and module-level `Console` instances, and conditional module
blocks used for optional imports and command registration. Import traversal is
limited to four imported-function hops and 256 reachable functions. This is a
syntax-based call graph, not whole-program or dataflow inference: it starts at
each recognized command, follows same-module function names and imports that
resolve to exactly one function in the declared source inventory, and treats
both sides of a conditional as possible. It does not execute imports or
evaluate branch feasibility.

The local helper walk has a 256-function work budget per command. This fixed
heuristic ceiling bounds analysis work; it is not a calibrated CLI policy
threshold. If additional unvisited reachable functions remain after the budget
is used, renderer evidence is inconclusive; already-visited queued functions
are discarded without making the result inconclusive.

Alphus reports `could not verify Rich output` when an imported call cannot be
resolved to one in-scope function (for example, it is outside the inventory,
ambiguous, unparseable, or not a module-level function) and the call visibly
receives a Rich `Console`. It reports the same status when that visible
provenance reaches the four-hop import bound, or when the 256-function bound
leaves pending work. A same-module helper that receives a visible Rich
`Console` in an untyped parameter and calls a configured renderer method is also
unresolved: the checker does not infer the runtime type passed through that
parameter. Those cases carry `evidence = "unresolved"`, use info severity, and
start with `[presentation:inconclusive]`. They remain visible in human and
JSON output but do not fail a rule, including when the selected threshold is
`info`. A renderer proven absent remains `evidence = "missing"` and follows
the configured enforce/advisory severity. Other unsupported constructs are
not guaranteed to produce an unknown finding. One dynamic-import form is
recognized conservatively: assigning
`importlib.import_module("rich.console").Console` to a local name and calling a
configured renderer method on an instance of that name produces unresolved
evidence; Alphus does not execute the import. Other dynamic-import forms,
reflection, runtime monkey-patching, indirect console flow through containers,
and general control-flow behavior may remain unanalyzed.

This distinction matters for tools with first-run fallbacks. A CLI can keep a
standard-library command path available before optional Typer and Rich
dependencies are installed, then use those packages for registered commands
when present. The CLI policy evaluates the registered command path without
making optional packages a prerequisite for static analysis.

## Diagnostic and JSON compatibility

Machine/CLI contract findings use
`alphus/python/none/correctness/cli-contract-violation`. Presentation findings
use `alphus/python/none/style/cli-presentation-policy`, with `error` severity
for enforcement and `warning` severity for advisory rollout. Older releases
grouped presentation messages under the contract ID; consumers migrating
stored diagnostics can map those former presentation findings to the style ID.

The direct `--rule cli --json` payload remains a JSON array of strings. New
presentation entries start with `[presentation:error]` or
`[presentation:warning]`; inconclusive entries start with
`[presentation:inconclusive]`, while contract strings remain unprefixed.
Inconclusive entries normalize to info diagnostics and stay nonfatal when the
legacy string array is evaluated at any severity threshold. Findings now
include endpoint and command context, so string contents can change even
though the JSON container stays a list. Legacy message arrays without a
presentation prefix continue to normalize to the contract ID. Consumers that
persist diagnostics should use the normalized diagnostic records and the exact
IDs above instead of treating message text as a stable identifier.

## Regression coverage

Synthetic source fixtures cover imported serializers and renderers, typed
local helpers, module-level renderer instances, conditional Typer registration,
and optional-dependency fallbacks. Positive and negative controls distinguish
an output-file destination from an output-style selector and ensure unused
helpers or unrelated serializers do not satisfy a command contract. This
coverage exercises the configured Python/Typer model; it does not claim support
for other CLI frameworks or stand in for consumer CI.

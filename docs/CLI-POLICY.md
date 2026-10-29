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

This distinction matters for tools with first-run fallbacks. TITAN's
`scripts/build_standard.py` and `scripts/setup_titan.py` keep a standard-library
command path available before optional Typer and Rich dependencies are
installed. Their registered Typer commands use the richer presentation once
those dependencies exist. The CLI policy evaluates that registered command
path; it does not make installing Rich or Typer a prerequisite for the
standard-library bootstrap path.

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

## TITAN comparison

The focused comparison ran `python -m alphus --root <TITAN checkout> --rule cli
--json` against one TITAN worktree at
`0fac470cac009ee2aaa318d8d327d6013c781495`. The worktree already contained
local edits; its `git status --porcelain -uall` SHA-256 was
`f78fa29acfd6a803c068774193714eec7ffd8bbf2a80ed704eed2961645a9000` before and
after both read-only rule invocations. The baseline used the archived Alphus
`b4b6055a6ae0286912b461cd2b4262b3318c5a0c` environment and exited 1 with three
messages: two requests for an explicit `--output` human mode and one request to
support both configured Rich and plain styles. The first candidate run reported
21 messages. Source review classified 17 as analyzer false positives: one
imported Doctor serializer, twelve Rich renderer cases (typed helpers,
module-level consoles, or imported shared renderers), and four conditional
Typer `--json`/`--verbose` registrations. Four additional messages concerned
the deliberate standard-library bootstrap paths described above; they are
policy-scope decisions rather than reasons to install optional dependencies.

The synthetic regression inventory maps all 17 cases and all four bootstrap
cases to focused source fixtures in `tests/fixtures/cli_policy/titan/`. The map
in `tests/gates/source/test_cli_policy_engine.py` records each TITAN source
path, synthetic fixture endpoint, fixture file, and finding category. Its
bootstrap check blocks imports of Typer and Rich while analyzing the fallback
fixtures, so passing the static check does not depend on either optional
package being installed. Existing true-negative fixtures continue to ensure
an unused Rich helper, an unrelated serializer, or a file-output option cannot
satisfy a command's policy.

The wheel built from commit
`36f176effa79c76089777ee5a85c9525d574fbb6` (SHA-256
`1d13c1b20d5baa07b2bd16d442b98a2c8256a3b3da4b2986b3bab91545558c66`) ran the
same rule against that TITAN checkout under Python 3.12 and returned `[]` with
exit 0. The wheel itself was imported from its installed artifact, matching the
syntax used in TITAN's current sources. An initial Python 3.11 attempt stopped
at TITAN's PEP 695 `type` alias during AST parsing, before findings could be
evaluated; that attempt is not consumer evidence. No unresolved-renderer
message was reported for this inventory. The TITAN worktree status fingerprint
was `f78fa29acfd6a803c068774193714eec7ffd8bbf2a80ed704eed2961645a9000` both
before and after the read-only comparison.

A negative control used a temporary copy of TITAN's quality policy with its
required JSON option changed to a deliberately absent flag. The candidate
exited 1 and reported the missing option for 47 recognized commands. The
original TITAN policy and checkout were not changed.

The wheel-backed self-profile passed all 26 steps with 0 failures, including
1,083 package tests passed and 1 skipped. Both provisional review rollouts
passed with no findings. The wheel was built using the already installed build
tools and installed into a temporary target; the self-profile and consumer
controls imported that artifact. A prior attempt to use the CI wrapper's
editable-install phase could not fetch `setuptools>=68` in this network-
restricted environment.

Alphus passing its own profile does not establish acceptance by TITAN: Alphus's
self-profile only checks the rules and source inventory selected by Alphus's
own configuration. The consumer comparison must be run against TITAN's policy
and recorded separately. This section records the observed trial; it is not a
claim that other TITAN profiles or its complete CI passed.

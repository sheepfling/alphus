# Future extensions, categories, and diagnostics

This document records Alphus's diagnostic-tag contract and future extension
design. It does not add a plugin loader or change which checks run.

## Current contracts

Each portable checker receives an explicit repository root, validated policy,
and selected files. Direct rule results keep the frozen `Finding` record with
a canonical rule ID, repository-relative path, optional line, message, and
severity. Profile aggregation adapts Alphus-owned results into a named
`Diagnostic` carrying source, the same rule ID, path, line, message, and
severity. Source helpers may return a line and message before the checker adds
its rule ID and path. Native command steps keep their own output and exit
codes; Alphus retains their raw output and reports execution status without
converting native tool output into Alphus findings.

### Rule-tag contract

Every Alphus-owned finding uses this fixed identifier shape:

    alphus/<scope>/<framework>/<category>/<complaint>

Use lowercase kebab-case for each segment. The scope is a language, data format,
any for a cross-language check, or repository for repository-wide rules.
Use none when no framework applies; use a registered framework name such as
pydantic or fastapi when a finding is framework-specific. Add framework names
to the `Framework` enum in `alphus.contracts.rule_tags`. Lint and format
tools are producers, not frameworks. Add languages to `Scope` and complaint
categories to `Category` in the same module. The final segment names the
specific complaint and stays independent of message wording.

Examples:

- alphus/python/none/style/line-too-long
- alphus/python/pydantic/validation/dump-revalidation
- alphus/javascript/none/security/manual-output-escaping
- alphus/repository/none/architecture/edge-forbidden

`RuleTag.parse()` exposes scope, framework, category, and complaint as
validated fields. Construct owned IDs with `rule_tag(Scope.PYTHON,
Framework.NONE, Category.STYLE, "line-too-long")`. The self-profile's Python
structure gate flags complete raw tag literals and literal tag dimensions in
`src/alphus/**`. Profile JSON includes `finding_rollups`: scope totals,
category totals, and category/complaint totals. These aggregate normalized
Alphus diagnostics across languages, with severity counts for each group.

Diagnostic.source identifies the producer and is kept separate from the
tag. Human output prints an Alphus tag once; it does not repeat alphus as a
second prefix. External command output and native tool rule codes remain
owned by those tools and are not rewritten into Alphus tags. Add new built-in
findings with rule_tag(...) and extend the controlled scope/category
vocabulary deliberately. Category labels classify findings; they do not yet
select or enable groups of checks in policy.

TOML selects current rules and ordered profiles. It contains consumer paths,
thresholds, and command arguments, not executable Python callbacks. The
profile `failure_threshold` currently defaults to `error`, and a rule step may
override the severity of its findings. These are narrow threshold controls;
they do not add category-wide selectors or an independent enforcement-state
model. Alphus does not currently discover third-party rule packages or expose
pytest-style hooks.

## Proposed category selection model

The broader categories below remain a proposal for navigation and selection.
They are separate from the controlled finding-tag categories:

| Category | Candidate scope |
| --- | --- |
| Architecture and ownership | Package boundaries, module roles, shared utilities |
| Types and data contracts | Runtime types, JSON structure, possible stub or API audits |
| Dependencies and packaging | Dependency locks, build and distribution checks |
| CLI and execution | CLI contracts, script policy, path discovery, output escaping |
| Source hygiene and layout | Python style, file size, line length, repository layout |
| Documentation and traceability | Documentation checks and adapters to existing tools |

The list is an organizing proposal, not a one-to-one rule registry. Some
current selectors combine related concerns, and new documentation checks may
belong to their native tools. A future migration should identify each rule's
owner and category before exposing category-wide switches.

## Proposed diagnostic contract

Keep a diagnostic distinct from a rule, category, profile, and enforcement
setting. Profile output now has an internal normalized `Diagnostic`; the
existing `Finding` record remains the direct-rule compatibility baseline while
individual checkers migrate. Any broader public diagnostic contract should
preserve stable IDs, locations, and JSON field names. The current severity
threshold is a compatibility control for failure levels, not the final
enforcement model. Severity retains `info`, `warning`, and `error`, with spaced
internal ranks to leave room for future levels. A rule step may assign an
independent `priority` (`low`, `normal`, `high`, or `urgent`) to its diagnostics;
priority is reported but does not change the failure threshold. A future
category configuration should distinguish these from enforcement (`enforced`,
`advisory`, or `disabled`).

An orchestration step may set `rollout = "provisional"` while it is being
evaluated. Provisional steps run and retain their pass or fail status and
diagnostics, but their failures do not fail the overall profile. Profile
summaries count provisional outcomes separately; the default is `mainline`.

The current `alphus --plan` command prints resolved profile order, steps,
file matches, rollout, and fixability before execution. A file-scoped command
with no matching files now reports `not_applicable` instead of `passed` in
human and JSON output. Broader execution states still need a typed contract:
`not run` for disabled or unselected checks, and `not applicable` for built-in
rules whose prerequisites are absent. Category and rule overrides should be
added only with a clear resolved plan and unchanged default selection.

## Future extension hooks

### Add a built-in theme today

The `alphus.gates.review`, `source`, `repository`, and `hygiene` packages
are working examples. Put checker implementations under `alphus.gates.<theme>`
and put reusable parsing or file
access in `alphus.support` only when more than one gate needs it. A portable
checker receives an explicit root, selected files, and its validated policy;
it returns findings or a typed report. A workflow gate such as the stub
verifier runs through a command step instead.

For a new built-in rule, first define its problem contract: evidence,
counterexamples, false-positive boundary, and non-goals. Decide which parts are
source-language independent. Add a language frontend only to translate that
language's syntax into normalized evidence for the shared rule; keep the
selector's supported language scope tied to implemented frontends.

The current built-in registry migration has several coordinated declarations:
`QualityRuleName` is the static selector type, `RULE_SPECS` owns primary policy
and output metadata, `CheckPolicies` validates rule settings, and each theme
registers its typed runner. `alphus.execution.dispatch` composes the runner
maps. Keep these declarations complete without adding another selector list.
The target is for one typed rule specification to provide shared metadata and
drive configuration validation, dispatch, result adaptation, rendering, and
plan descriptions where layer boundaries allow it. Static typing may still
require a declared selector type; validate that boundary against the runtime
registry rather than maintaining a separate expected inventory.

Use shared constants and contracts for stable names, tags, severity, rollout,
and result states. Add an execution adapter only when a rule genuinely needs a
distinct input or output shape, and keep it registered rather than adding a
new selector branch in the CLI. Import each implementation from its owning
theme package; removed root module forwarders are not extension points.

### Package layout for additional languages

Group built-in checks by their actual dependency and policy boundaries. A
Python-specific checker can live in an ordinary `alphus` subpackage, while
repository-wide and data-format checks remain separate from any one language.
Keep the core inventory, orchestration, diagnostics, and rule IDs stable during
such moves. The stub workflow's controller and fixture runner live under
`alphus.gates.stubs`. The sibling `alphus_stub_quality` import package contains
the small audit helpers that must run under a Python 3.10 target interpreter;
it is shipped in the same Alphus distribution, not installed separately.

Possible future rules include JSONC/JSONL parsing and additional numeric
catalog realms. Define syntax, authority, precision, and source-context
semantics before adding catalog entries; stable values should remain checked
in rather than depending on a consumer's installed scientific package. Git
inventory failures also need a typed operational error contract before
introducing recovery policy.

Python namespace packages become useful if independently installed and
versioned distributions need to share one import namespace. They are not needed
to organize modules inside the current distribution. If third-party gate
packages become necessary, discover them through an explicit, versioned entry
point contract rather than by scanning a namespace for imports. C++ and
JavaScript tools can continue as native command steps until Alphus owns a
language-specific check that warrants Python code.

### Shared rule semantics across source languages

Keep the rule contract and the source-language parser as separate concerns.
Shared policy, file inventory, findings, and profile execution can apply to
many languages, while parsing and deciding which syntax counts as evidence
remain language-specific. Do not label a rule language-neutral just because
its policy or output model is shared.

The numeric catalogs demonstrate this boundary. Their Python frontend uses
the Python AST to extract normalized observations (line, value, syntax
context, arithmetic operation, canonical call name, and keyword argument).
The shared operation vocabulary covers arithmetic, bitwise, shift, and matrix
multiplication operators. A future frontend can add language-specific
operations, such as elementwise operators, when their semantics can be
preserved during normalization. The matcher applies realm-specific entries
with source provenance and context constraints, then creates the Alphus finding
with both the recommended API and its source. Conversion catalogs can match
normalized multiplication and division forms while excluding powers. SciPy's
constants database also provides a discovery path for additional chemistry
constants; curated entries are checked in so they do not change with an
installed dependency version.
Atomic weights and compound-specific properties need keyed data catalogs with
element or compound identity and, where relevant, measurement conditions. The
current catalogs still analyze Python only. Configured extensions do not imply
support for another grammar. A future frontend can be added when a second
language is in scope, with its own parser and explicit handling of declarations,
assertions, and other intentional contexts. It should feed the shared matcher
only where those observations have the same meaning.

Keep findings scoped to the language that was analyzed so rollups retain that
information. Use `any` only when the evidence and rule semantics are truly
independent of source syntax. Extension lists describe file selection; they
must not advertise parser support by themselves. A selected file without a
matching frontend must be rejected or reported as not applicable, never
silently treated as clean. Start with internal, rule-owned frontends; add a
public registry or plugin contract only when real consumers need independent
analyzers.

### Hook contract

The internal `RuleSpec` catalog gives every built-in selector one primary
policy field, output shape, and text-renderer key; summary metadata lives with
that contract. A matching runner table holds concrete checker dispatch. The
next step is to migrate older rule outputs to common findings, then attach
selector-group metadata and a typed checker callable to each specification.
Those groups are distinct from diagnostic-tag categories. Keep the current
CLI selectors as adapters while that contract is exercised across existing
rules.

Only after consumers need third-party checks should Alphus expose a versioned
plugin API, potentially through an entry-point group and pytest-style hook
specifications. The API would need explicit loading policy, deterministic
ordering, duplicate-name rejection, typed configuration, and the same finding
contract as built-in checks. Loading a plugin executes Python code, so a policy
file should not silently import arbitrary modules. Native tools should remain
available as command steps without requiring a Python plugin.

Fixability is separate from diagnostic severity, remediation priority, and
gate rollout. Command steps can already declare an explicit, file-scoped
`fix_argv`; see [fix plans](FIXES.md). Built-in rule fixers need typed edit
proposals with stale-content and conflict checks before they should be exposed
through the same apply workflow.

## Migration sequence

1. Define each new rule's problem contract, evidence, counterexamples, and
   false-positive boundary before choosing a parser or language.
2. Consolidate selector metadata and shared vocabulary in the typed rule
   registry. Keep static type declarations synchronized with that registry and
   avoid new parallel selector inventories.
3. Keep source-language parsing in explicit frontends and share only normalized
   observations whose meaning is consistent across those languages. Use a
   second frontend to validate this boundary before exposing it as an API.
4. Extend the existing `--plan` and file-scoped `not_applicable` result to
   built-in prerequisites, disabled checks, and explicit `not run` outcomes.
   Build plan and report entries from the resolved execution profile.
5. Migrate checkers to the shared rule specification one at a time, comparing
   normalized findings and JSON output with the existing contracts.
6. Design and version third-party hooks only when an actual consumer requires
   them; test ordering, collisions, configuration failures, and diagnostics
   before release.

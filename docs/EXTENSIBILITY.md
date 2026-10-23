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
to the controlled set in alphus.contracts.rule_tags. Lint and format tools are
producers, not frameworks. The category comes from the controlled
list in alphus.contracts.rule_tags; the final segment names the specific
complaint and stays independent of message wording.

Examples:

- alphus/python/none/style/line-too-long
- alphus/python/pydantic/validation/dump-revalidation
- alphus/javascript/none/security/manual-output-escaping
- alphus/repository/none/architecture/edge-forbidden

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

For a new built-in selector, add its policy model under `alphus.policy`,
add the selector to `alphus.policy.base.QualityRuleName` and its policy field
to `alphus.policy.catalog.RULE_SPECS`, register its runner in the theme package,
and compose that mapping in `alphus.execution.dispatch`. Add an output adapter
in `alphus.execution.results` only if it has a new shape. Add direct CLI and profile
tests, then select the gate in a consumer profile. The registry completeness
test catches missing selectors, and Alphus's `check` profile exercises the
rule and native tooling together. Import each implementation from its owning
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

Possible future rules include JSONC/JSONL parsing and broader numeric
constant recognition. Define those formats and precision policies explicitly
before adding dependencies such as SciPy. Git inventory failures also need
a typed operational error contract before introducing recovery policy.

Python namespace packages become useful if independently installed and
versioned distributions need to share one import namespace. They are not needed
to organize modules inside the current distribution. If third-party gate
packages become necessary, discover them through an explicit, versioned entry
point contract rather than by scanning a namespace for imports. C++ and
JavaScript tools can continue as native command steps until Alphus owns a
language-specific check that warrants Python code.

### Hook contract

The internal `RuleSpec` catalog now gives every built-in selector one primary
policy field and output shape; a matching runner table holds concrete checker
dispatch. The next step is to migrate older rule outputs to common findings,
then attach selector-group metadata and a typed checker callable to each
specification. Those groups are distinct from diagnostic-tag categories. Keep
the current CLI selectors as adapters while that contract is exercised across
existing rules.

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

1. Keep the built-in selector catalog complete while mapping current rules to
   categories without changing defaults.
2. Extend the existing `--plan` and file-scoped `not_applicable` result to
   built-in prerequisites, disabled checks, and explicit `not run` outcomes.
3. Migrate checkers to the shared rule specification one at a time, comparing
   normalized findings and JSON output with the existing contracts.
4. Design and version third-party hooks only when an actual consumer requires
   them; test ordering, collisions, configuration failures, and diagnostics
   before release.

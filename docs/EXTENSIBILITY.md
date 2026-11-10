# Future extensions, categories, and diagnostics

This document records Alphus's diagnostic-tag contract and future extension
design. It does not add a plugin loader or change which checks run.

Current built-in feature-owned registration and its bounded 0.0.3 compatibility
evidence are described in the
[built-in check architecture](BUILTIN-CHECK-ARCHITECTURE.md).
Use that page as the single design entry point; this guide remains focused on
diagnostic and extension contracts.

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

No one of language, framework, or category is the universal parent of every
rule. A selector is the stable execution/configuration handle; concern and
category describe the reviewed problem; language/framework describe provider
applicability; detector method and fuzziness describe how evidence is produced.
Keep implementation packages with their actual language, framework, or shared
runtime dependencies. A shared concern may have several language-specific
providers, each with explicit limits; a matching concern name does not imply
that every provider supports every language.

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
model. Alphus supports explicitly enabled third-party rule packages through a
small versioned API; it does not automatically load installed plugins or
expose a general hook system.

## Check discovery and domain recommendations

First-party built-ins declare `ALPHUS_CHECK`, `ALPHUS_MORPHOLOGY`, and
`ALPHUS_FEATURE` beside their provider in `src/alphus/gates`. The build backend
statically discovers these typed declarations and generates the installed
entry-point metadata plus runtime `FeatureDefinition`, `RuleSpec`, strict
policy, selector, and dispatch views. `RULE_SPECS` is a generated runtime view,
not a second authoring registry. The catalog records a short summary, supported
surfaces, optional domain tags, policy section, and whether a file inventory is
required. Inspect it with
`alphus --catalog`; use `alphus --catalog --json` for machine-readable output.
The catalog describes all built-in rules and rules from enabled plugins.
Installed but disabled plugin IDs appear without importing their packages or
revealing rule metadata. Consumer-defined native command steps are visible in
the configured profiles and in `alphus --plan` output.

Domain tags are advisory hints for an agent, not automatic applicability
claims. Before recommending a rule, compare its supported surface and limits
with the repository's languages, dependencies, and actual workload. The
agent should suggest a consumer-owned rule step and required `[checks.*]`
policy, explain the match, and identify domain requirements that no available
check covers. It must not enable a rule or change a default profile merely
because a tag matched.

When a check emits a finding, use its concise message and any available
rule-specific guidance to assess the observation against repository purpose
and constraints. Recommend a sound correction when one fits; otherwise record
an evidence-based exception and call out a rule or guidance gap. A clean scan
is not the goal by itself. The current catalog does not link longer per-rule
guides, so that discoverability remains follow-on work.

For example, a Python simulation, earth-science, or trajectory-analysis
project may find `numeric-literals` and `scipy-constants` relevant. They can
flag configured exact constants in arithmetic, but they do not validate
physical models, dimensional consistency, coordinate reference systems,
trajectory integrators, or conservation laws. `input-contracts` may fit code
that mutates Python collection inputs, and `test-quality` may fit its tests;
neither supplies those missing domain semantics. State that gap instead of
treating a generic check as domain validation.

An agent can propose a separate profile and leave the current default alone:

```toml
[checks.numeric_literals]
extensions = [".py"]
exclude = []
math_constants = true

[checks.scipy_constants]
extensions = [".py"]
exclude = []
physical_constants = true
unit_conversions = true
inverse_conversions = true

[[orchestration.steps]]
kind = "rule"
name = "Numeric review"
rule = "numeric-literals"

[[orchestration.steps]]
kind = "rule"
name = "SciPy constants review"
rule = "scipy-constants"

[[orchestration.profiles]]
name = "science-review"
steps = ["Numeric review", "SciPy constants review"]
```

The root `[files]` inventory still controls which files can be inspected.
Run the proposed profile explicitly with
`alphus --run --profile science-review` after reviewing its scope.

Keep domain tags narrowly justified and open to new areas; do not add a tag
simply to make a rule appear relevant. Static discovery is deterministic and
does not import gate modules. The selected entry point is loaded only after
explicit selection; declarations do not activate a check or select it in a
profile.

## Third-party rule packages (API v1)

Third-party rules are ordinary Python distributions. They advertise one
registration function through the `alphus.rules.v1` entry-point group; their
distribution can install its own dependencies and import package without
adding modules under Alphus's import namespace. Namespace packages are not
needed for this model. Plugins use the standard [PyPA entry-point
metadata](https://packaging.python.org/en/latest/specifications/entry-points/),
the same discovery mechanism described in [pytest's plugin
guide](https://docs.pytest.org/en/latest/how-to/writing_plugins.html), with a
narrow rule registration contract instead of pytest's hook lifecycle. See the
[PyPA plugin guide](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/)
for the trade-offs between entry points and namespace packages.

The entry-point name is the plugin ID. Both plugin IDs and rule IDs are
lowercase slugs. Alphus exposes selectors as `plugin-id:rule-id`, rejects
duplicate names, and checks the plugin's declared API version before
registering a rule. A plugin factory returns a `RulePlugin`:

```toml
[project.entry-points."alphus.rules.v1"]
docs = "my_docs_rules:register"
```

```python
from collections.abc import Sequence
from pathlib import Path

from alphus.contracts.model import StrictModel
from alphus.plugins import PluginFinding, PluginRuleSpec, RulePlugin


class HeadingPolicy(StrictModel):
    extensions: tuple[str, ...] = (".md",)


def check_headings(
    root: Path, files: Sequence[Path], policy: HeadingPolicy
) -> tuple[PluginFinding, ...]:
    # `files` contains repository-relative paths from the configured inventory.
    return ()


def register() -> RulePlugin:
    return RulePlugin(
        name="docs",
        rules=(
            PluginRuleSpec(
                name="heading-check",
                config_model=HeadingPolicy,
                check=check_headings,
                summary="Checks headings in selected Markdown documents.",
                applies_to=("markdown",),
                domains=("documentation-publishing",),
            ),
        ),
    )
```

The settings model must be strict, immutable, and reject unknown fields. Plugin
configuration is a JSON-compatible TOML table and is validated against that
model before a selected rule runs. Checkers receive the repository root,
selected repository-relative files, and validated settings. They return
`PluginFinding` records; Alphus adds the plugin source and selector namespace,
then applies the normal severity threshold and profile reporting. Finding
paths must be repository-relative, lines are one-based, and local finding IDs
are lowercase slugs.

Installation does not activate a plugin. Add its ID to consumer policy and
add its selector to a profile:

```toml
[plugins]
enabled = ["docs"]

[plugins.rules."docs:heading-check"]
extensions = [".md"]

[[orchestration.steps]]
kind = "rule"
name = "Documentation headings"
rule = "docs:heading-check"

[[orchestration.profiles]]
name = "docs-review"
steps = ["Documentation headings"]
```

Loading an enabled entry point executes its Python factory. The allowlist is
therefore an explicit trust decision; disabled entry points are only listed by
package metadata and are not imported. `alphus --catalog --json` shows rules
from enabled plugins and their domain hints. It also lists installed but
disabled plugin IDs without trying to inspect their rule metadata. An agent can
recommend an installed plugin, but enabling it and selecting its rule remain
consumer policy changes.

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
with no matching files reports `not_applicable` instead of `passed` in human
and JSON output. Shared native intents add typed disabled, unselected,
unsupported, and failure-kind results; other built-in rules retain their
existing prerequisite behavior. Category and rule overrides should be added
only with a clear resolved plan and unchanged default selection. See the
[shared intent guide](SHARED-QUALITY-INTENTS.md) for this bounded contract.

## Future extension hooks

### Add a built-in check today

Use a feature-local module under the owning shape or language package. Add a
strict policy model only when the check needs one, then declare its existing
selector and output shape in `ALPHUS_CHECK`, its claim and evidence in
`ALPHUS_MORPHOLOGY`, and a typed synchronous runner in `ALPHUS_FEATURE`.
Choose `FindingBuiltinFeature`, `CompositeFindingBuiltinFeature`,
`MessageBuiltinFeature`, `SharedUtilitiesBuiltinFeature`, or
`CyclomaticBuiltinFeature` to match the output shape.
`PythonStyleBuiltinFeature` is reserved for the existing `python-style`
selector's legacy category-map wire format; it is not a template or registry
for new `*-style` checks. A new style check should have a feature-owned
declaration and ordinarily return `list[Finding]` through
`FindingBuiltinFeature`. Each form narrows the
runner result type and primary policy type; the lazy loader returns a disjoint
union. A typed form also declares a policy resolver; its return type must
match the runner policy parameter and declared policy model. Dispatch
narrows the selected form before adapting to the existing output contract.
Static discovery checks the form/output-shape pairing. The build derives
catalog/config/dispatch views and the wheel entry point; do not edit generated
views, `RULE_SPECS`, `QualityRuleName`, or `pyproject.toml` for an individual
selector. The source declaration must use the supported static form: the
feature object links the local declarations and a local runner. Use a small
feature-local adapter if the implementation needs composed or imported setup.
Do not import analyzer-only dependencies merely to inspect the catalog.

Keep `Finding.message` concise: describe what was observed and include an
immediate correction only when it is safe and clear. Longer rationale,
examples, and exceptions belong in discoverable documentation, not every
finding. A future guidance link should be derived from the full stable rule ID
so rule owners can add pages without editing a central index. The path
convention and catalog link are not implemented yet. Alphus can recommend a
project instruction change for a person to review; it must not write or inject
project `AGENTS.md` content automatically.

For a typed form, pair a policy resolver that returns the declared strict
model with a runner that accepts that same policy type. Pyright checks the
resolver/runner pair; runtime registration checks both annotations against the
`FeatureDefinition.policy_model`, and dispatch checks the resolved value before
calling the runner. The model generates the matching strict config field.
Ordinary typed runners cannot read unrelated config fields; a composite opts
into aggregate config through `CompositeFindingBuiltinFeature`, with its primary
policy still typed explicitly.

The common finding adapter is appropriate for ordinary checks. Cyclomatic
analysis retains its `CyclomaticRuleOperations` and `CyclomaticReport`; a
consumer-owned native build remains a `CommandRunStep`. Do not coerce those
different results into findings. Preserve existing output contracts when
adding a feature.

Put tests under the corresponding `tests/gates/...` shape/language path when
practical, with further tests allowed for generated catalog, config, CLI,
profile, and installed-wheel behavior. For a registration change, cover strict
unknown-field rejection, direct and profile output, ordered reporting, and
lazy loading of an unselected provider. Selection in a consumer profile is a
separate explicit policy decision; registration alone never enables it.

### Package layout for additional languages

Group built-in checks by their actual dependency and policy boundaries.
Language-specific parsing and analysis belongs under
`alphus.gates.languages.<language>`; shared inventory, selector dispatch, and
policy binding belong under `alphus.gates.source`. Repository-wide and
workflow checks remain in their own gate themes. A new format such as JSONC
can have its own language package without adding its parser to Python-source
analysis. Keep the core inventory, orchestration, diagnostics, and rule IDs
stable during these moves. The stub workflow's controller and fixture runner
live under `alphus.gates.stubs`. The sibling `alphus_stub_quality` import
package contains the small audit helpers that must run under a Python 3.10
target interpreter; it is shipped in the same Alphus distribution, not
installed separately.

Possible future rules include JSONC/JSONL parsing and broader numeric
constant recognition. Define those formats and precision policies explicitly
before adding dependencies such as SciPy. Git inventory failures also need
a typed operational error contract before introducing recovery policy.

Python namespace packages become useful if independently installed and
versioned distributions need to share one import namespace. They are not
needed for third-party Alphus rules: those use the versioned entry-point
contract described above and keep their own import package. JavaScript
projects can continue to use consumer-owned native command steps. Alphus now
includes the C++ quality workflow described in
[C++ quality gates](CPP-QUALITY.md); its engines keep their JSON reports and
run through the existing command-step contract rather than introducing a
second rule registry.

### Rule contract

The generated built-in `RuleSpec` view records policy field, output shape,
discovery summary, supported surfaces, and advisory domain tags. The immutable
`alphus.execution.dispatch.BUILTIN_RULES` runtime registry joins those records
with selected feature entry points. No built-in selector remains on a legacy
registration path. Existing
output shapes remain adapted through `alphus.execution.results`; they are not
changed to a common wire format by registration migration. Domain suggestions
remain separate from diagnostic-tag categories.

The v1 plugin boundary is intentionally limited to rule registration and
synchronous check callbacks. It does not add lifecycle hooks, automatic
discovery imports, or category-wide activation. Native tools remain available
as command steps without requiring a Python plugin. Keep plugin metadata,
runner dispatch, and normalized output in immutable registries, and add
conformance coverage before introducing another API version.

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
4. Keep third-party rules on API v1 until an actual consumer needs a new
   capability; test entry-point ordering, collisions, typed configuration,
   and normalized diagnostics with separately packaged conformance fixtures.

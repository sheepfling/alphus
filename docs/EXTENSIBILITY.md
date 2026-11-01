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
model. Alphus supports explicitly enabled third-party rule packages through a
small versioned API; it does not automatically load installed plugins or
expose a general hook system.

## Check discovery and domain recommendations

`alphus.policy.catalog.RULE_SPECS` is the source of truth for built-in check
discovery. Every selector records a short summary, the source or framework
surfaces it supports, an optional set of domain tags, its policy section, and
whether it needs a file inventory. Inspect the complete catalog with
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

When adding a built-in selector, add complete discovery metadata to its
`RuleSpec`. Keep domain tags narrowly justified and open to new areas; do not
add a tag simply to make a rule appear relevant. The existing catalog
completeness check ensures every public selector has a spec and runner.

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

### Add a built-in theme today

The `alphus.gates.review`, `source`, `python`, `repository`, `vcs`, and `hygiene` packages
are working examples. Put checker implementations under `alphus.gates.<theme>`
and put reusable parsing or file
access in `alphus.support` only when more than one gate needs it. A portable
checker receives an explicit root, selected files, and its validated policy;
it returns findings or a typed report. A workflow gate such as the stub
verifier runs through a command step instead.

For a new built-in selector, add its policy model under `alphus.policy`,
add the selector to `alphus.policy.base.QualityRuleName` and its policy field
to `alphus.policy.catalog.RULE_SPECS` with a summary, supported surfaces, and
justified domain tags, register its runner in the theme package,
and compose that mapping in `alphus.execution.dispatch`. Add an output adapter
in `alphus.execution.results` only if it has a new shape. Add direct CLI and profile
tests, then select the gate in a consumer profile. The registry completeness
test catches missing selectors, and Alphus's `check` profile exercises the
rule and native tooling together. Import each implementation from its owning
theme package; removed root module forwarders are not extension points.

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

The built-in `RuleSpec` catalog records policy field, output shape, discovery
summary, supported surfaces, and advisory domain tags. The immutable
`alphus.execution.dispatch.BUILTIN_RULES` registry joins those records with
theme-owned checker functions and fails early if their selectors differ.
Older built-in output shapes remain adapted through
`alphus.execution.results` while they migrate to common diagnostics. Domain
suggestions remain separate from diagnostic-tag categories.

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

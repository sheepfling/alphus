# Built-in check architecture and migration plan

This is the design entry point for the built-in check re-architecture planned
for Alphus 0.0.3. It defines the ownership boundaries, proposed registration
flow, compatibility proof, migration slices, and deferred work. The existing
check behavior is the compatibility baseline; this document does not itself
change runtime behavior.

The [machine-readable inventory](architecture/builtin-check-inventory.json)
records the current built-in selector, strict policy field, directly observed
runner policy references, runner, output shape, and shared direct/profile
surfaces. The [pinned registry baseline](architecture/builtin-check-baseline-c880093.json)
records these registration contracts at main commit
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`. These are audit views, not another
source of truth or runtime registry. The generator checks the baseline for
contract drift through its paired test and must be checked whenever source
contracts change.

The current inventory's policy references are deliberately named
`policy_inputs_observed`: it combines the primary `RuleSpec` field with direct
`config.checks.<field>` references in the literal runner binding or mapped
local runner function. It does not follow imported helper calls, aliases, or
indirect config flow and therefore is not a complete effective-input graph.
The package-boundaries composite is a verified example, not proof that every
check's dependencies are fully captured. Complete dependency declarations
belong in the future feature definition and need dedicated validation.

## Release boundary and status vocabulary

Alphus 0.0.3 is a structure and compatibility release: the same checks and
consumer-visible behavior with clearer ownership, fewer duplicate
registrations, and a less fragile review path. Alphus 0.0.4 is the planned
feature release for new detectors, new language coverage, round-two Bacflow,
and local-model-assisted execution. Persistent result caching, automatic
repository setup, and history/index migrations remain separately scoped until
their contracts and need are established.

The inventory test verifies the committed baseline by regenerating it from
the pinned source commit, and compares the current registration fields to that
baseline. This is an objective registration-contract check, not a wheel
behavior differential. The full pinned-wheel equivalence protocol below is a
prerequisite for broad migration of the remaining selectors. One isolated
vertical slice may use its own pinned direct/profile differential cases and
slice-specific lazy-import proof; that limited exception does not establish
equivalence for other selectors.

This document distinguishes four kinds of statement:

- **Current behavior** is verified in the named source modules and inventory.
- **Design** is the proposed target and is not implemented by this document.
- **Migration proof** is a required test or measured comparison, not an
  assertion that it has already passed.
- **Open decision** is called out explicitly below and must not be resolved by
  silently changing consumer behavior.

PR #100 remains an open draft. It began with the six-check morphology
metadata pilot and now has two feature-owned runtime slices: `file-size` and
`line-length`. Each local `ALPHUS_CHECK` literal statically generates
morphology metadata, typed `FeatureDefinition`, `RuleSpec`, strict policy
field, selector type, inventory entry, and lazy runner thunk. The established
`RuleEvaluation` and CLI result adapters remain shared, so adding a feature
still uses the existing output contract. The other 60 baseline selectors
remain on legacy registration paths; these two slices do not complete issue
#87 or establish full selector equivalence.

## Current package ownership and dependency direction

The current public and internal responsibilities are:

- **Consumer configuration and CLI** — `alphus.config`, `alphus.cli` own
  strict TOML models, direct selectors, profile invocation, renderers, and
  exit status.
- **Built-in selector and policy validation** — `alphus.policy.base` and
  `alphus.policy.orchestration` expose `QualityRuleName`, `CheckPolicies`, and
  `require_rule`. For migrated features, selector and strict policy contracts
  derive from generated views; legacy selectors and policy fields remain
  explicitly declared in their current source modules.
- **Rule metadata and catalog** — `alphus.policy.catalog` owns `RuleSpec`,
  `RULE_SPECS`, and `RuleOutputShape`.
- **Feature implementations** — `alphus.gates.<theme>` and
  `alphus.gates.languages.<language>` own checker functions and theme runner
  maps.
- **Runtime dispatch and third-party boundary** —
  `alphus.execution.dispatch` and `alphus.plugins` own `BuiltinRuleBinding`,
  generated runner dispatch, and plugin API v1.
- **Output normalization and evaluation** — `alphus.execution.results` owns
  `RuleOutput`, `diagnostics_from_output`, and `RuleEvaluation`.
- **Profile planning, commands, and work scheduling** —
  `alphus.policy.orchestration`, `alphus.execution`, and
  `alphus.execution.scheduler` own `RuleRunStep`, `CommandRunStep`,
  `WorkUnit`, and `WorkOutcome`.
- **Findings and shared diagnostics** — `alphus.contracts` owns `Finding`,
  `Diagnostic`, `RuleTag`, severity, and remediation priority.

Keep the dependency direction one-way: contracts and policy types do not import
feature implementations; feature implementations depend on their policy and
shared support; generated registration binds policy metadata to lazy feature
entry points; execution plans and dispatches selected checks; CLI and
serialization sit at the outer boundary. The plugin API remains a separate
explicit trust boundary and is not scanned as built-in source.

Do not move directories as a prerequisite. Existing locations already reflect
useful ownership: `gates/repository`, `gates/source`, `gates/hygiene`,
`gates/review`, `gates/markdown`, `gates/vcs`, and language-specific packages.
Move an implementation only when a tested ownership boundary makes the move
clearer. Keep tests near their mirrored source area where practical, such as
`tests/gates/repository` for `src/alphus/gates/repository`.

## Vocabulary and independent axes

- A **concern** is the subject being reviewed, such as source size,
  output-escaping risk, or function complexity. It is a grouping concept, not
  automatically a selector or a finding ID.
- A **provider** is an analyzer implementation with stated language and
  semantic capabilities. A concern can have multiple providers whose
  limitations differ.
- **Evidence** is the typed observation a provider returns, together with the
  inspected scope and provenance needed to interpret it.
- An **assessment** interprets that evidence under the check's configured
  policy and produces existing findings, diagnostics, or a structured report.
- A **configured gate** is a selected rule or native command step with
  consumer-owned severity, priority, rollout, threshold, and scope settings.
- **Orchestration work** is the scheduler's unit of execution, resource claims,
  dependencies, and outcome collection. It is not another check identity.

Claim strength, detection method, backend, repeatability, and rule-level
evaluation maturity are separate. A deterministic heuristic remains a
heuristic. A native tool may provide an exact threshold result or an
approximate metric. Repeatability describes only whether the same declared
inputs (including versions and environment assumptions) yield the same
evidence on repeated runs, and which assumptions make that claim valid. A
native result can be deterministic under pinned inputs; a model result can be
reproducibly replayed while its claim remains uncertain. Backend identity and
whether a result is advisory or enforcement-relevant belong on separate axes.
Do not encode unsupported numeric confidence. Rule-level evaluation maturity
is separate from a particular finding's confidence (if any), and both are
separate from consumer severity and blocking policy.

The target vocabulary has three small independent metadata contracts, separate
from `FeatureDefinition` registration:

- `ClaimDescriptor(kind, strength, wording)` records what is claimed and how
  directly the evidence supports it. Use qualitative values such as
  `direct`, `qualified`, or `suggestive`, never a numeric confidence score.
- `ProviderDescriptor(method, backend, capabilities)` records how evidence is
  produced, the concrete tool/provider identity when one exists, and its
  language and semantic limits. `method` and `backend` are distinct fields.
- `RepeatabilityContract(guarantee, declared_inputs)` states whether evidence
  repeats for identical declared inputs and which versions, configuration,
  and environment assumptions are part of those inputs.

For example, `positional-semantic-overrides` is a qualified claim from a
Python AST provider that can be deterministic for the same source and policy.
`cyclomatic-complexity` is a direct threshold claim about a selected backend's
metric, with backend identity and version recorded separately; repeatability
depends on those versions and effective options. The six-check pilot's single
`mechanisms` enum is transitional and must not be copied as though its values
were one orthogonal axis. The 0.0.3 registration slice may leave the pilot
metadata untouched while establishing these separate target fields; new
model execution remains out of scope until 0.0.4.

Morphology may record the concern, bounded claim, claim kind, mechanism,
scope, evidence kinds, language/format coverage, and rule-level evaluation
maturity. It must not absorb severity, remediation priority, rollout,
applicability, selection, or actual run coverage. These dimensions describe
different things and change for different reasons.

## Small typed runtime surface

Use a small set of immutable, named domain contracts. Prefer evolving current
types where they already cover the role; do not add parallel abstractions
without a consumer.

1. **`FeatureDefinition[PolicyT, EvidenceT, OutputT]`** associates one
   existing selector with its strict policy type/field, summary and
   applicability metadata, declared effective inputs, provider binding,
   assessment adapter, and output adapter. The declaration is literal and
   statically inspectable; executable objects are generated or lazily
   resolved at runtime.
2. **`ResolvedCheckInputs[PolicyT]`** carries validated policy and effective
   options, repository inventory, selected scope, available provider choices,
   and relevant environment identity. It says what is resolved, not that work
   ran.
3. **`PlannedWorkUnit[EvidenceT]`** binds a feature's typed operation to
   existing generic scheduling claims such as locks, slots, ordering, timeout,
   and budget. Adapter code translates it to `WorkUnit`; the scheduler need
   not know about selectors, languages, or findings. Existing `after` edges
   remain ordering dependencies: a failed predecessor does not suppress a
   later selected step. Success-gating dependencies require a separate design.
4. **`EvaluationResult[OutputT]`** records status, typed output/evidence,
   diagnostics, provenance, and explicit scope counts. It distinguishes
   selected, applicable, analyzed, excluded/skipped, partial, failed, and
   finding counts. JSON is produced only at process and public serialization
   boundaries.

Not every scheduled task is a finding-producing check, and forcing every
operation into one `Check` type would lose useful contracts. The current
surfaces already separate several roles:

- **Discover and plan:** `ProfilePlan` and `alphus --plan` resolve explicit
  selection and selected inventory; a plan makes no claim that execution ran.
- **File analysis:** `file-size` and `line-length` share validated policy,
  paths, provenance and a findings adapter, while keeping their distinct
  physical-byte, line-count and codepoint evidence.
- **Composite analysis:** `package-boundaries` plus graph, version-sync and
  callable-registry policies use one selected gate and ordered finding
  reduction while retaining multiple effective policies and engine-owned
  evidence.
- **Native polyglot analysis:** `cyclomatic-complexity` shares scheduling,
  scope and reporting while retaining Ruff, ESLint and Lizard metrics,
  availability and coverage.
- **Effectful command:** the `latexmk` step in
  `examples/documents/pdf-structural-check.toml` uses existing
  `CommandRunStep` and scheduler outcomes; it writes artifacts such as
  `build/report.pdf` and passes native exit status to later validators.

The small common execution contract is selection, resolved inputs, work
scheduling, provenance and a typed outcome adapter. Rule analysis can adapt to
existing `RuleEvaluation`; cyclomatic reports retain their backend-aware
result; commands retain process status, captured output and effectful build
artifacts. Plan output remains a plan. Do not make command steps pretend to be
read-only providers or convert every result to findings. Existing `after`
relationships order steps only; they do not suppress a step after predecessor
failure.

This answers “do all tasks fit one form?” at the orchestration boundary, not
by forcing one domain result shape on them. Planning resolves selection and
applicability but performs no analysis. File analyzers return file-scoped
evidence adapted to findings. Composite analyzers consume several effective
policies and may return merged findings plus diagnostics. Native polyglot
providers retain backend-specific metrics and availability. Commands report
process outcome and declared artifacts. The scheduler can schedule all of
these through `WorkUnit`/`WorkOutcome`; typed role-specific adapters preserve
their meanings. A new universal `TaskResult` payload or a finding wrapper for
commands would erase information without improving scheduling.

Concern, language, provider, determinism, cacheability and effects are
independent axes. A line-length concern can use a shared Python analyzer;
cyclomatic complexity maps to different language-specific native providers;
a PDF build command is an effectful operation rather than a source analyzer.
Determinism describes repeated evidence for the same declared source, policy,
tool versions and environment. Cacheability additionally requires a complete
input/dependency identity and no unaccounted effects; deterministic output
alone does not make an operation safe to skip. Effect declarations are not yet
a general feature-owned contract, and persistent result reuse remains outside
0.0.3. These differences are inventoried and planned explicitly, not hidden in
one morphology enum.

Keep applicability separate from provider capability: a provider may support
a language in general while a particular repository inventory or configured
scope has no applicable files. Keep tool and subtool identity separate from
language, and evidence strength separate from repeatability. For example,
three cyclomatic providers can be repeatable under pinned versions while
reporting different supported syntax and metric semantics. “Universal
concern” means the consumer intent can span languages; it does not make the
current provider universal.

### Concern scope is not provider coverage

A concern can apply across languages while a provider covers only one language
or tool. A shared concern never implies a universal detector or equivalent
semantics:

- `cyclomatic-complexity` names a language-independent metric concern. Current
  providers are Ruff for Python, ESLint for JavaScript and Lizard for C++;
  their metrics, versions, unsupported cases and coverage remain distinct.
- `scipy-constants` names a physical-constant concern, but the current provider
  scans configured Python arithmetic for selected SciPy constants. This does
  not claim equivalent C++, JavaScript or other-language coverage.
- `line-length` is a text-level concern with configured extensions and
  codepoint measurements; it does not require language parsing.
- `benchmark-docs` is a prose-risk concern with deterministic lexical
  matching. Its method can repeat for fixed inputs while its claim remains
  heuristic and its false-positive limits remain explicit.

When an existing concern gains another language or subtool provider, record
that provider and its syntax, metric, version, availability, applicability and
coverage under the owning concern. Keep the selector stable when the consumer
intent and output contract remain the same; the provider plan chooses a
supported implementation only for explicitly selected work. A new provider
must not create a duplicate selector, auto-enable a profile step, or upgrade
claim strength. Current cyclomatic bindings already live with the metric
policy and backend plans rather than in a second selector list. Broader
provider-declaration generation is a later migration seam; 0.0.3 preserves
these bindings and adds no language or detector support.

The concrete extension point today is `CyclomaticBackendBinding` in
`policy/metrics.py`. A new backend for the existing cyclomatic concern adds a
typed binding there, a planned backend/capability mapping and execution/result
adapter in `gates/source/cyclomatic_complexity.py`, plus backend-specific
fixtures. It reuses the `cyclomatic-complexity` selector, policy and profile
step; it must not add a second selector or silently change selected language
coverage. This is not yet one-declaration registration: several exhaustive
matches in that feature module must learn the new variant. Keep this cost
visible in 0.0.3 evidence. If repeated migrations show that those matches
drift, the next scoped improvement is a provider descriptor colocated with the
typed backend contract and a single validated dispatch path, not another
global provider registry.

Evidence should be a typed union of existing or feature-owned result models,
not a recursive `JsonObject` alias. The current `Finding`, `Diagnostic`,
`CyclomaticReport`, `RuleEvaluation`, and native report models should be
reused or adapted where they already express the contract. Preserve specialized
cyclomatic and shared-utilities reports rather than forcing them through a
broad common payload. Any richer internal `EvaluationResult` must adapt to
existing public output, status, ordering, and exit behavior during 0.0.3; it
must not silently add public semantics. A result adapter preserves established
JSON/text shapes and legacy IDs.

## Feature-owned registration and imports

The intended flow is:

```text
feature-owned static declaration
       │  AST-only validation; no feature imports during discovery
       ▼
generated typed selector, strict-config view, RuleSpec/catalog,
lazy runner binding, result adapter, and docs index
       │
       ▼
validated consumer config + explicit profile/direct selection
       ▼
resolved inputs → planned work → provider evidence → assessment
       ▼
typed evaluation → existing render/report/history boundaries
```

Each generated view is derived from the same declaration; none becomes an
independent list. Generation rejects duplicate or missing selectors,
policy/runner/result bindings, invalid output contracts, stale files, and
unsafe source paths. Discovery must not execute feature or consumer code.
Generated per-selector thunks use explicit static import paths so importing
the catalog or parsing config does not initialize every checker or optional
backend. Only an explicitly selected rule imports its implementation. A
registration never selects or enables a check: consumer profile steps remain
the selection source, and strict config continues to reject invalid or
unknown fields.

Preserve TOML section and field names, `QualityRuleName` selectors, existing
`RuleTag` finding IDs, gate IDs, profile step names, output formats, ordering,
exit status, and threshold behavior. Built-in discovery stays first-party and
static. Third-party entry points remain explicitly allowlisted under plugin
API v1.

## Developer experience: add a check once

A feature declaration belongs beside its behavior and points to the
feature's existing strict policy model without moving policy ownership into
the checker package. `file-size` lives in
`src/alphus/gates/hygiene/file_size.py`; `FileSizePolicy` remains in
`src/alphus/policy/sources.py`. The second migration uses the same path for
`line-length` and `LineLengthPolicy`:

```python
ALPHUS_CHECK = (
    ("selector", "line-length"),
    ("policy_field", "line_length"),
    ("policy_model", "alphus.policy.sources.LineLengthPolicy"),
    ("output_shape", "findings"),
    ("runner_module", "alphus.gates.hygiene.line_length"),
    ("runner_name", "check_line_length"),
    # Additional literal pairs declare morphology, claim and evidence.
)
```

The deterministic AST reader discovers this literal without importing feature
or plugin code. It validates the policy class, selector, policy field, runner,
finding tags, paths and duplicate ownership. It generates the immutable
`FeatureDefinition` catalog, morphology view, `RuleSpec`, strict
`GeneratedFeaturePolicies` base fields, `QualityRuleName` literal and lazy
runner thunk. `CheckPolicies` and the public `QualityRuleName` import path stay
unchanged. Unknown or malformed declarations fail generation with the source
path and offending reference. Result adaptation still uses the existing
`RuleEvaluation` and output-shape path.

At runtime, consumers continue to provide the same `[checks.line_length]`
policy and select `line-length` directly or in a profile. Catalog inspection
and config validation do not import the checker. Dispatch imports only the
selected provider; registration never adds a profile step. The package-level
`check_line_length` compatibility export resolves lazily on explicit access.

This static complaint rule is intentionally narrow: each migrated file check
declares complaint slugs whose `rule_tag()` calls are literal in that same
feature module. It proves a simple one-selector/one-owner case; it is not a
general rule for shared emitters. Existing numeric checks use the shared
`gates/review/numeric_catalog.py` engine, which constructs tags from policy
specifications, and some adapters own tags outside the selector module. Do not
copy those tags into every feature or weaken static validation to accept
unresolved strings.

The numeric family now exercises the explicit shared-contract case. Its
`ALPHUS_COMPLAINT_CONTRACTS` literal lives beside the shared emitter in
`gates/review/numeric_catalog.py`. `numeric-literals` and `scipy-constants`
reference the same `numeric-inline` contract rather than copying complaint
strings. That contract lists each permitted emitter and its exact existing
`RuleTag` IDs; the runtime matcher resolves from the same literal using the
configured `constant` or `conversion` kind. Static discovery validates the
contract and derives each selector's morphology tags without importing the
emitter. The IDs remain `alphus/python/none/style/inline-*` and
`alphus/python/scipy/style/inline-*`; strict policy, selection, messages and
reports are unchanged. A separate contract covers the existing generic C++
numeric-matcher adapter test, without adding a C++ selector or provider.

Repeated IDs are accepted across selectors only when one named contract owns
the ID and explicitly permits both emitters. Uncontracted duplicate IDs,
undeclared emitters, unknown contracts, malformed tags and conflicting
contract ownership fail generation. Tests cover the permitted shared case and
the rejected neighbors. This establishes a bounded pattern for dynamic/shared
emitters; it does not migrate the numeric selectors' selector/config/runner
registration or imply all existing shared checkers fit this contract.

Likewise, the current `FeatureDefinition.policy_field` and single
`runner_module` describe a selector's primary compatibility binding, not its
complete effective-input graph or provider graph. `package-boundaries` uses
`PackageBoundaryPolicy` together with architecture-graph, version-sync and
callable-registry inputs; its history digest currently has a separate known
input gap. Do not infer that graph from one primary field or change legacy
history cohorts during registration work. A composite migration needs a typed
effective-input aggregate (or explicit, validated policy-input references)
and a feature-level router that can plan multiple providers while retaining
the primary `RuleSpec.policy_field` and public selector. The shape should be
proved against the existing composite before it becomes a general API.

### Human-facing smell names and stable finding IDs

Rick's example `types.opaque-return` is a useful human-facing name: a category
plus a smell, with language and provider recorded separately. It should be a
display/grouping alias over morphology metadata, not a replacement for a
current wire ID or a selector. Current findings use canonical IDs of the form
`alphus/<scope>/<framework>/<category>/<complaint>`; selectors, history,
profiles and consumers may depend on them. Preserve these IDs and outputs
through 0.0.3, even when the scope component is language-specific.

For 0.0.4 naming design, compare a short alias such as `types.opaque-return`
with the existing `typing` category vocabulary and explicit aliases attached
to one or more stable IDs. Reject accidental alias collisions. If the same
human concept intentionally spans languages, group the variants under one
concern while retaining distinct stable IDs and documented provider limits;
do not assume that identical words or thresholds imply identical semantics.
Whether aliases are only presentation labels or selectable public identifiers
is an unresolved 0.0.4 decision. No new naming scheme is active runtime
behavior in this 0.0.3 work.

At runtime a consumer still opts in by writing `[checks.file_size]` and
selecting `file-size` directly or naming it in a profile. Catalog inspection
and config validation do not import its checker. Dispatch resolves only the
selected provider, passes the existing validated policy and inventory, and
adapts its findings to the existing `RuleEvaluation` and CLI outputs. A
registration never activates a profile step. A selected provider failure uses
the existing operational-error path; discovery and generation errors stop the
build with the declaration path and offending reference.

The feature has three views that must not be collapsed into one label:

- **Concern and claim:** configured file-size limits, with the bounded claim
  and evidence type documented by the checker.
- **Provider:** `check_file_size` in the shared Alphus Python implementation.
  A cross-language concern such as cyclomatic complexity instead maps Python
  to Ruff, JavaScript to ESLint, and C++ to Lizard, each with its own syntax,
  metric limits, version, and coverage.
- **Repeatability:** same declared source, policy, tool version, and supported
  environment assumptions produce the same evidence. This does not make a
  heuristic exact or equate the languages' semantics.

For a new implementation, place behavior tests beside the owning source
package under the matching `tests/` path (for example,
`tests/gates/hygiene/`). Add contract tests for generated config, dispatch,
result adaptation, and the installed wheel under mirrored `tests/policy/`,
`tests/execution/`, and `tests/` package paths. Keep shared scheduler behavior
generic; do not add selectors, plugins, or language backends to scheduler code.

### How we will measure the improvement

Before the two runtime slices, each selector duplicated its registration
across `QualityRuleName`, `CheckPolicies`, `RULE_SPECS`, a theme runner map and
dispatch. For `file-size` and `line-length`, the declaration now derives the
selector type, strict policy field, catalog metadata and lazy dispatch view;
manual catalog and theme-runner entries have been removed. Their existing
policy models, checker bodies, result adaptation and CLI reporting remain
owned by the current modules. A new feature still needs its policy model,
checker body, declaration, focused tests and user documentation, but no
selector, config, catalog or runner list edit for these generated surfaces.
Measure registration edits and review effort from the next migrations rather
than claiming a time reduction from the design alone.

Do not claim a time reduction from the design alone. For the first three
migrated checks, record the commit diff, the count of manually edited
registration locations, generator output, and elapsed implementation/review
time. Also count human corrections: accepted review comments that require a
code, documentation, or test change, with categories for ownership/duplicate
registration, config/selection/dispatch compatibility, static discovery and
lazy imports, independent taxonomy axes, evidence and coverage, effective
policy inputs, immutable typed contracts, fixture/path isolation, and mirrored
test/self-review quality. Record repeated-category comments across changes,
not only the total comment count, so the review loop reveals recurring failure
families. Set a baseline from this morphology pilot and the immediately
preceding backflow reviews; do not infer improvement from fewer comments when
review scope or reviewer time changed. The numeric baseline is not yet
reconstructed: PR #98's GitHub review reported no findings, while morphology
corrections were delivered in the parent review conversation. Do not treat the
absence of PR comments as zero corrections; classify those conversation notes
before evaluating the first migration.

For every accepted correction, search analogous declarations, selectors,
runners, adapters, config fields, and fixtures before closing it. Add a
positive regression and a legitimate-neighbor case where the category has a
meaningful boundary. Keep the checklist and category definitions stable across
the first three migrations, then compare repeated-category corrections and
registration locations against the baseline. The objective is zero
hand-maintained central selector, config, catalog, or runner enumerations for a
new check; the migration itself remains a bounded, reviewed change. The full
exit criterion still requires all current selectors to derive from the same
declarations and the pinned-wheel proof to pass.

The six-check morphology pilot proves metadata discovery. The `file-size`
and `line-length` slices additionally derive strict policy fields, selector
typing, `RuleSpec` and lazy runnable dispatch while retaining existing result
adaptation and reporting. Focused tests exercise both providers and strict
configuration. The pinned wheel report below remains the evidence boundary;
these slices do not prove all 62 selectors or complete issue #87.

## Existing-check mappings

These examples exercise different shapes that the design must support. The
full current selector/config/runner/output inventory is generated separately
so this narrative is not another selector registry.

### File-local exact check: `file-size`

The current policy is `FileSizePolicy` in `alphus.policy.sources`; the
feature is in `alphus.gates.hygiene` and returns existing findings under the
`FINDINGS` result shape. Its claim concerns configured physical file-size
limits. Inventory and file-level evidence can be shared, but the declared
byte/line counting rules remain this feature's assessment contract. Empty or
excluded file scope must not be reported as a complete scan of other files.

### Deterministic heuristic: `benchmark-docs`

The policy is `BenchmarkDocPolicy` in `alphus.policy.review`; the checker
examines configured Markdown prose and emits risk findings. Deterministic
lexical matching does not make its semantic claim exact. Its evidence should
identify the inspected sections and matched patterns; the check's documented
false-positive/false-negative limits remain attached to its claim. Its
consumer severity and rollout remain independent.

### Deterministic semantic heuristic: `positional-semantic-overrides`

The policy is `PositionalSemanticOverridePolicy`; the current implementation
is `alphus.gates.review.positional_semantic_overrides`. It examines configured
Python paths for literal positional branches and hard-coded text assignments
to configured semantic fields. Its own claim says a match is a review
candidate, not proof of a defect. Evidence is limited to recognized Python AST
branches, configured field names, and assignment locations; dynamic behavior
outside those patterns is unknown. The rule can be deterministic for the same
source and policy without turning its semantic risk claim into an exact
finding.

### Composite cross-file check: `package-boundaries`

The primary policy is `PackageBoundaryPolicy` in
`alphus.policy.architecture`. The current runner in
`alphus.gates.repository.runners` may also consult `ArchitectureGraphCheckPolicy`,
`VersionSyncPolicy`, and `CallableRegistryPolicy`. The assessment combines
findings from these engines under the existing selector, so resolved inputs
must expose these effective policy dependencies. Their evidence remains
owned by their respective engines; registration must not erase that
provenance or fabricate one universal semantic model.

### Native polyglot check: `cyclomatic-complexity`

The strict `CyclomaticComplexityPolicy` selects explicit Python/Ruff,
JavaScript/ESLint, and C++/Lizard bindings with exact versions and per-language
options. Existing `CyclomaticPlan`, `CyclomaticBackendPlan`, backend results,
coverage outcomes, and `CyclomaticReport` preserve native semantics and
provenance. Keep backend selection and unsupported/missing-tool outcomes
explicit. A common complexity concern does not imply equal parsing, counting,
or coverage guarantees across the three languages.

## Applicability, recommendations and reporting

Catalog applicability and domain labels are guidance, not evidence that a
check ran. A recommendation should explain why a check appears applicable,
whether its provider is available, whether required config is present, and
whether it is selected. Recommendation must not silently enable a check or
claim execution.

Every report should distinguish the counts for selected, applicable,
analyzed, excluded/skipped, partial, failed, and findings. Define the
denominator for each count. Zero findings means only that successfully
analyzed scope produced no findings; it is not a pass for unsupported,
excluded, empty, unselected, or failed scope.

## Compatibility and differential verification

Before restructuring, pin a reference wheel from the agreed baseline and
build candidate wheels from each migration commit. Run both against identical
source trees, policies, native tool versions, plugin fixtures, environments,
and repository state. Compare:

- all existing selectors, strict config acceptance/rejection, profile
  selection and direct `--rule` execution;
- selected versus actually analyzed scope, including empty, excluded,
  unsupported, partial, missing-backend, and operational-error cases;
- serial and parallel profile paths, including ordered reduction, locks,
  budgets, timeouts, and native command steps;
- plugin API v1 conformance and explicit enablement behavior;
- result schema, IDs, messages, severity/priority, output ordering, exit
  codes, CLI text/JSON and profile reporting;
- installed-wheel invocation outside the source checkout, proving the wheel
  rather than the editable tree is imported.

Exclude only predeclared volatile fields such as timings and temporary
absolute paths. Do not refresh snapshots, suppress self-review findings, or
weaken thresholds to conceal a difference. An unexplained behavior difference
blocks the refactor slice.

## First pinned-wheel differential result

The runnable harness is [scripts/differential_wheels.py](../scripts/differential_wheels.py)
with its scenario manifest and fixtures under
[tests/differential](../tests/differential). It builds wheels from full commit
SHAs, installs each wheel into a separate virtual environment, verifies that
`alphus/__init__.py` is owned by the installed distribution and matches the
wheel `RECORD`, and checks that fixtures remain unchanged. Its report records
source commits, wheel hashes, fixture commits and hashes, the manifest and
harness hashes, package versions, and the declared output normalization. It
freezes each fixture once for both runs, compares fixture hashes and Git
commits, and checks that the manifest and harness stay unchanged through the
run. Exact temporary paths are replaced with stable placeholders in the evidence.

The latest comparison used reference
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` and candidate
`b4d2d346478986abe1875613c6f051eb7ae7b69b`. The catalog was identical at 62
selectors. All 23 manifested scenarios produced no differences. They
behaviorally exercised 10 built-in selectors and one API-v1 plugin selector;
52 built-in selectors remain without behavior-level wheel evidence. Cases cover
strict invalid-config rejection, direct JSON and plain output, profile selection,
serial/parallel profile output, exact findings and locations, shared numeric
complaints from `numeric-literals` and `scipy-constants`, a composite
package-boundaries check over package, architecture graph, version-sync and
callable-registry policy, and Python Ruff, JavaScript ESLint, and C++ Lizard
providers. The plugin scenarios verify discovery without importing the plugin,
strict rejection of unenabled settings, and explicit profile activation with a
reported finding. Provider cases cover missing tools, an unsupported Ruff
version, and partial coverage from an empty JavaScript scope plus an analyzed
Python file. Lizard was pinned to 1.24.2 in both wheel environments.

The comparison is representative, not full equivalence. The report defers the
legacy package-boundaries history digest, plan-level unsupported-capability
details, invalid plugin return values and duplicate entry points at wheel level,
and built-in optional-provider import tracing. Unit tests cover some plugin
edge cases. The current differential manifest also has no effectful command or
build scenario; its PDF build example is an architecture probe, not wheel-level
equivalence evidence. Scheduler and command semantics remain unchanged in this
slice. The two wheel virtual environments share the same system-site dependency
layer, so the run is matched but not hermetic. Both source-archive wheels report
version `0.0.0`; source commits and wheel hashes identify the artifacts. That
report alone did not justify a runtime registration migration.

The latest machine-readable run is available in the
[latest behavior and selector-matrix report][differential-report].
It records the frozen fixture snapshot identities, manifest and harness hashes,
plugin source/wheel hashes, per-scenario native dependencies, selected and
analyzed file counts, and separate built-in/plugin coverage. Its generated
matrix also invoked all 26 selectors with configured policies and verified
strict missing-policy rejection for the other 36. These checks exercise
selection/config contracts; they do not count as semantic behavior coverage.

[differential-report]: architecture/builtin-check-wheel-differential-c880093-b4d2d34-numeric-contract.json
Reproduce it with:

```sh
PATH="$PWD/node_modules/.bin:$PATH" .venv/bin/python scripts/differential_wheels.py \
  --root . \
  --baseline c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e \
  --candidate b4d2d346478986abe1875613c6f051eb7ae7b69b \
  --output docs/architecture/builtin-check-wheel-differential-c880093-b4d2d34-numeric-contract.json
```

## Runtime registration slices: `file-size` and `line-length`

Commit `22698843ad2ceca12f4b65567cd3cf5cf1340bf2` moves file-size behavior to
`src/alphus/gates/hygiene/file_size.py` and removes its duplicate entries from
the central `RuleSpec` and hygiene runner maps. Its adjacent `ALPHUS_CHECK`
literal feeds generated feature metadata, the `RuleSpec`, inventory and a
lazy generated dispatch thunk. Strict `CheckPolicies.file_size` validation and
the `QualityRuleName` selector remain in their shared contracts. This removes
two hand-maintained runtime registration entries for this selector; it does
not yet make strict config or selector typing feature-owned.

The corrected candidate commit
`ab0d4ff9c40672943a8690a20b2773efbb9b1c3f` was compared with the pinned
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` wheel. The [file-size differential
report][file-size-differential] recorded equal 62-selector catalogs and no
differences across its 21 manifested scenarios. Nine built-in selectors had
behavior-level evidence, including file-size direct JSON/plain output and
profile-plan plus serial/parallel execution. The 26 direct selector
invocations and 36 strict missing-policy rejections verify selection/config
contracts; they are not semantic coverage for all 62 checks. The existing
subprocess regression also verifies that importing dispatch leaves the
file-size implementation unloaded until that selector is run.

The first differential attempt caught a catalog-summary change for
file-size. The declaration was corrected to preserve the exact mainline
summary. The line-length migration also derives strict config and selector
contracts. Its [pinned line-length differential report][line-length-differential] records
equal catalogs and no differences across 22 scenarios, including direct
line-length output and profile serial/parallel execution. Nine of the 62
selectors have behavior-level evidence; the remaining 53 still lack it. The
26 configured direct invocations and 36 strict missing-policy rejections are
selection/config evidence, not semantic coverage. Installed-wheel validation
on the line-length candidate passed 27 self-profile checks and 2,432 tests
(43 skipped). Neither slice proves full equivalence or completes #87.

[file-size-differential]: architecture/builtin-check-wheel-differential-c880093-ab0d4ff-file-size.json
[line-length-differential]: architecture/builtin-check-wheel-differential-c880093-0daeab6-line-length.json

## Performance and cache boundary

Measure startup/import time, inventory construction, parsing, native tool
startup, execution, result validation, and reduction separately. For 0.0.3,
safe opportunities are lazy selected-rule imports and sharing immutable
in-run inventory or parsed inputs only when their dependencies are explicit
and their semantics match a fresh run. Use native incremental modes where
they already exist. Do not persistently skip a check based on a cached result.

A future cache needs distinct file-local, selected-set, dependency-graph,
repository/history, and runtime-artifact scopes. Its identity must account
for content, additions/deletions and membership, dependency edges, effective
policy, analyzer/native-tool/model versions, configuration, and declared
environment inputs. Unknown dependencies require broader reruns. Cached or
partial evidence must never be presented as complete coverage. Future cache
identity is separate from legacy history cohort identity and archive schema.

## Package-boundaries history identity: separate disposition

There is a source-backed gap in the current legacy profile digest. The
package-boundaries runner reads package-boundaries policy and can additionally
run architecture-graph, version-sync, and callable-registry checks. The
current `gate_manifest_entry` hashes only the primary `RuleSpec.policy_field`,
common file policy, and gate settings. Changes to those additional effective
policies can therefore leave the recorded gate digest unchanged.

Track this as a separately reviewed history-identity correctness fix. Do not
silently fold it into the structural migration, rewrite existing cohorts, or
change archive semantics as part of 0.0.3. Add explicit tests for each
effective input and decide version/compatibility behavior before changing the
digest. Feature declarations may record effective-input dependencies for
future caches without changing the legacy history digest.

## Ordered migration slices

1. **Inventory and reference baseline.** Generate the source-derived
   selector/config/runner/output inventory; pin reference wheel and fixtures;
   check generated inventory freshness and completeness. No runtime behavior
   changes.
2. **Typed registration contract.** Define the constrained declaration
   fields, AST-only validation, generator diagnostics, and generated artifact
   boundaries. Preserve the morphology pilot as one consumer of the model.
3. **Bounded feature-owned vertical slices (`file-size`, `line-length`).**
   These derive strict policy fields, selector typing, `RuleSpec`, inventory
   and lazy dispatch while keeping existing config names, result adaptation,
   and reporting behavior. Their direct/profile differential and unselected
   provider tests establish only these slices.
4. **Migrate remaining built-ins by owner package.** Move registration data,
   not semantics. Generate selector typing, strict check fields, `RuleSpec`,
   runner/result bindings, catalog and docs views. Retain per-feature
   implementations and tests near `src/` ownership.
5. **Lazy execution and measured in-run reuse.** Make only behavior-preserving
   import and reuse changes; publish phase timings and differential evidence.
6. **Close compatibility and documentation.** Require all current selectors
   in generated inventory, no stale generated views, exact behavior diffs,
   self-profile and wheel validations before the refactor release.

History identity correction, persistent cache, automatic setup, history/index
migrations, new detector behavior, new language providers, local model
execution, and round-two Bacflow are not hidden substeps of this sequence.

## 0.0.4 backlog and unresolved decisions

The planned 0.0.4 boundary contains new detectors, new language/semantic
providers, local-model-assisted execution, and round-two Bacflow. Provider,
evidence, repeatability, provenance, lazy binding, and dependency declarations
from 0.0.3 are extension seams only; 0.0.3 should not ship dormant AI or cache
frameworks.

Two decisions remain for review:

1. **History digest correction timing:** decide whether the separately scoped
   package-boundaries digest fix must ship before 0.0.3 or can follow. In
   either case, preserve legacy archive interpretation and make any digest
   transition explicit.
2. **Migration completeness:** the recommended 0.0.3 exit is generated
   registration for every existing built-in selector, delivered in small
   reviewed slices. A partial generated catalog would leave the multi-registry
   addition problem unsolved and should not be called complete.

Until resolved, do not change digest/archive meaning or claim full #87
acceptance. PR #100 remains a draft containing the six-check morphology pilot
and the bounded `file-size` runtime registration slice.

# Built-in check architecture and migration plan

This is the design entry point for the built-in check re-architecture planned
for Alphus 0.0.3. It defines the ownership boundaries, proposed registration
flow, compatibility proof, migration slices, and deferred work. The existing
check behavior is the compatibility baseline; this document does not itself
change runtime behavior.

Generate the current machine-readable selector and runner inventory on demand:

```sh
.venv/bin/python -m scripts.generate_builtin_inventory --root . \
  --output /tmp/alphus-builtin-inventory.json
```

The inventory is an audit view, not another source of truth or runtime
registry. Its test compares current source-derived contracts directly with the
pinned `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` source archive. Generated JSON
reports stay in the caller's temporary output path rather than being committed
as duplicate architecture data.

The current inventory's policy references are deliberately named
`policy_inputs_observed`: it combines the primary `RuleSpec` field with direct
`config.checks.<field>` references in the literal runner binding or mapped
local runner function. It does not follow imported helper calls, aliases, or
indirect config flow and therefore is not a complete effective-input graph.
The package-boundaries composite is a verified example, not proof that every
check's dependencies are fully captured. Complete dependency declarations
belong in the future feature definition and need dedicated validation.

## Registration design review

Rick identified tuple-pair `ALPHUS_CHECK` declarations as opaque and the
built-in path as parallel to the existing plugin registry. The current
candidate replaces that tuple format for twenty feature-owned checks with
immutable `FeatureDefinition` and `RuleMorphology` values plus a typed
`BuiltinFeature` execution object. A PEP 517 build
backend statically reads those declarations and writes standard
`alphus.builtin_checks.v1` metadata into ignored build output. Runtime lookup
uses `importlib.metadata` against Alphus-named distributions and selects the
entry-point catalog matching generated feature definitions. It imports only the
selected feature object on demand. Its object owns direct typed
runner references and the cyclomatic-specific operations contract. Entry-point
metadata targets `ALPHUS_FEATURE`; selector and policy metadata no longer store
runner module/function strings, and policy models are class objects derived
from `StrictModel`. The loader rejects asynchronous providers and checks the
result annotation against the declared output shape before dispatch. The
third-party `alphus.rules.v1` contract remains separate and allowlisted. This is
still a partial migration: the remaining selectors use legacy maps. The history and
trade-offs are recorded in the [check registry spike](architecture/check-registry-spike.md).

## Release boundary and status vocabulary

Alphus 0.0.3 is a structure and compatibility release: the same checks and
consumer-visible behavior with clearer ownership, fewer duplicate
registrations, and a less fragile review path. Alphus 0.0.4 is the planned
feature release for new detectors, new language coverage, round-two Bacflow,
and local-model-assisted execution. Persistent result caching, automatic
repository setup, and history/index migrations remain separately scoped until
their contracts and need are established.

The inventory test generates both current and pinned-baseline inventories into
temporary files directly from their source trees, then compares registration
contracts. No generated JSON baseline is committed. This is an objective
registration-contract check, not a wheel behavior differential. The full
pinned-wheel equivalence protocol below is a prerequisite for broad migration
of the remaining selectors. One isolated
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
metadata pilot and now has twenty-four selectors moved onto feature-owned
generated runtime views:
`file-size`, `line-length`, `package-boundaries`, `repository-layout`,
`dependency-locks`, `documentation-config`, `cyclomatic-complexity`,
`output-escaping`, `comment-markers`, `numeric-literals`, `scipy-constants`,
`module-roles`, `markdown-shell-fences`, `git-ignores`, `git-attributes`,
`git-history`, `json-structure`, `path-discovery`, `document-style`,
`benchmark-docs`, `test-quality`, `input-contracts`, `pydantic-practices`, and
`sqlalchemy-practices`. Each local
`ALPHUS_CHECK` declaration statically generates
morphology metadata, typed `FeatureDefinition`, `RuleSpec`, strict policy
field, selector type, and inventory entry. Each feature module exposes one
typed `ALPHUS_FEATURE` object with a direct callback for lazy execution. The established
`RuleEvaluation` and CLI result adapters remain shared, so adding a feature
still uses the existing output contract. The other 38 baseline selectors
remain on legacy registration paths; these slices do not complete issue #87
or establish full selector equivalence. These declarations are now
typed `FeatureDefinition(...)` calls paired with immutable
`RuleMorphology(...)` values rather than the former tuple-pair `ALPHUS_CHECK`
format. Static discovery validates them without importing gate implementations.
The PEP 517 backend generates installed-wheel entry-point metadata without a
per-check `pyproject.toml` edit. Aggregate policy/config/dispatch views are
ignored build artifacts rather than checked-in shared files, so independent
feature branches do not edit the same generated outputs. Runtime entry points
target the typed feature object; the remaining 40 selectors still use legacy
registration maps.

The latest source-discovery slice moves `json-structure` and `path-discovery`
into feature-owned registration. Their typed declarations own the existing
strict policy model, metadata, complaint contracts and callbacks; language
analyzers remain separate Python and JavaScript providers. The legacy
`RULE_SPECS`, generated policy fields and source-runner entries were removed
for these selectors. Direct and profile tests assert existing finding IDs,
locations, selection and report order, and reject an unknown policy field.
This adds no new detector behavior.

For candidate `5987a183dee35c948ae771d852c2be4a458953b9`, the pinned wheel
comparison against `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` compared 55
manifested scenarios with zero differences. The reference and candidate
catalogs both contain 62 selectors; direct dispatch coverage is 26 selectors
and strict missing-policy rejection covers 36. Behavior-level scenarios now
exercise 21 distinct selectors. This is evidence for those manifested
scenarios, not complete 62-selector equivalence. The report is reproducible
with `scripts/differential_wheels.py` and is kept outside the repository at
`/tmp/alphus-morphology-source-discovery-5987a18.json`.

The next slice migrates `document-style` and `benchmark-docs`. Their typed
feature declarations replace tuple morphology; policy models, selectors,
catalog metadata and runners now derive from their owning analyzers. The
style-preference check retains its Markdown/LaTeX/HTML applicability and the
benchmark check retains its bounded Markdown risk claim. Direct tests preserve
finding IDs, severity, paths and locations; wheel scenarios also exercise
strict config rejection and ordered serial/parallel profile reporting.
Candidate `d26a8fe19f5039ff8cad5e16dcaf2097981cdf84` matched the pinned
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` wheel across 58 manifested
scenarios with no differences. The catalogs remain 62 selectors; 22 have
behavior-level scenarios. The report is at
`/tmp/alphus-morphology-document-review-d26a8fe.json`; the result does not
establish full selector equivalence.

The preceding review slice migrated `test-quality` and `input-contracts`. They
are Python-specific bounded heuristics that return existing structured
findings, but cover different concerns and strict policy models. Feature-owned
named complaint contracts now provide the stable IDs, including the
`manual-schema-validation` ID shared by two input-contract analysis paths.
The checker policies and finding messages are unchanged. Direct and profile
wheel scenarios assert the existing findings; separate invalid-policy fixtures
prove unknown fields are still rejected. At the earlier candidate
`c603b1eaf0f9ea5ab53b7f8b1c86a14f55bee70f` matched baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` across 62 scenarios with zero
differences. Both catalogs contain 62 selectors; direct invocation covers 26,
strict missing-policy rejection 36, and behavior scenarios exercise 22
selectors. The 40 remaining selectors still lack behavior-level evidence.
Report: `/tmp/alphus-morphology-python-review-c603b1e.json`.

The current morphology slice moved the Pydantic and SQLAlchemy framework
source checks into feature-owned declarations. They share the synchronous
finding runner contract and generated strict selector/config/reporting views;
their analyzers, optional rule policies, and named complaint contracts remain
owned by their respective framework modules. Direct and profile differential
fixtures assert stable IDs, messages and locations, while invalid-policy
fixtures prove strict rejection is unchanged.

Candidate `0c31a41b61a006ccff08d611fcec23100c403443` matched pinned baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` across all 68 manifested scenarios
with no differences. Both installed wheels exposed the same 62-selector catalog;
24 selectors have behavior scenarios, 26 have direct invocations, and 36 have
strict missing-policy rejection cases. The remaining 38 selectors are not yet
behaviorally exercised. The exact report is
`/tmp/alphus-morphology-framework-practices-0c31a41.json`; it is local
evidence, not a committed generated catalog.

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

The current twenty-four-selector flow is:

```text
typed, feature-owned FeatureDefinition and RuleMorphology
       │  build hook statically reads declarations and writes standard metadata
       ▼
standard built-in entry point; runtime registry loads the selected runner
       ▼
ignored generated selector/config/catalog/dispatch source views
       │
       ▼
validated consumer config + explicit profile/direct selection
       ▼
resolved inputs → planned work → provider evidence → assessment
       ▼
typed evaluation → existing render/report/history boundaries
```

Each generated view is derived from the same declaration; none becomes an
independent authored list. Build-time discovery scans only the first-party
registration-module filenames and does not execute feature, consumer or plugin
code. Runtime discovery reads only the installed Alphus distribution and
rejects duplicate selector names before loading a selected runner. Catalog and
config inspection do not import the migrated checker modules. A registration
never selects or enables a check: consumer profile steps remain the selection
source, and strict config continues to reject invalid or unknown fields. This
production path currently covers twenty-four selectors; the other 38 still
use legacy theme maps. The five aggregate views are no longer tracked: the
build regenerates them as ignored source files for each worktree, and
`MANIFEST.in` includes them in source archives. Separate feature branches
therefore do not commit or merge the same generated output. A checkout must run
the editable-install/build bootstrap before importing runtime modules or
running source tests; `AGENTS.md` already requires that editable install.

Preserve TOML section and field names, `QualityRuleName` selectors, existing
`RuleTag` finding IDs, gate IDs, profile step names, output formats, ordering,
exit status, and threshold behavior. Built-in discovery stays first-party and
static. Third-party entry points remain explicitly allowlisted under plugin
API v1.

## Developer experience: add a check once

A migrated feature currently declares typed metadata beside its behavior. It
references the existing strict policy model without moving policy ownership
into the checker package. `file-size` lives in
`src/alphus/gates/hygiene/file_size.py`; `FileSizePolicy` remains in
`src/alphus/policy/sources.py`. Its declaration has this shape:

```python
from alphus.plugins.builtin import BuiltinFeature
from alphus.policy.feature_definition import FeatureDefinition
from alphus.policy.sources import LineLengthPolicy

ALPHUS_CHECK: Final = FeatureDefinition(
    selector="line-length",
    policy_field="line_length",
    policy_model=LineLengthPolicy,
    output_shape="findings",
    summary="Checks configured source lines against a maximum length.",
    applies_to=("python",),
    domains=(),
    requires_files=True,
)

ALPHUS_FEATURE: Final = BuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=check_line_length,
)
```

The PEP 517 backend statically reads feature declarations and writes standard
`alphus.builtin_checks.v1` metadata under the ignored `.registry-build/`
directory. The runtime registry indexes entry points from Alphus-named
distributions whose selector set matches the generated feature catalog,
rejects duplicate selectors, and imports a runner only after explicit
selection. Adding one of the twenty migrated checks did not
require editing a central runner map or the `pyproject.toml` entry-point table.
The PEP 517 build also regenerates aggregate policy/config/dispatch views as
ignored source files and includes them in wheels and source archives. Those
outputs no longer appear in feature-branch diffs, so independent additions do
not collide on generated files. The bootstrap requirement is that each
worktree build or editable install regenerate the views before source imports.
The wheel entry point names the feature object, which owns direct typed runner
references. The loader validates that the selected runner is synchronous and
returns the result required by the feature's output shape.

At runtime, consumers continue to provide the same `[checks.line_length]`
policy and select `line-length` directly or in a profile. Catalog inspection
and config validation do not import the checker. Dispatch imports only the
selected provider; registration never adds a profile step. The package-level
`check_line_length` compatibility export resolves lazily on explicit access.

Static complaint validation supports both local literal tags and shared named
contracts. These use immutable `ComplaintContract` and `ComplaintEntry`
records carrying actual `RuleTag` values, not positional string pairs. Static
discovery parses those calls without importing the emitter.

The numeric family now exercises the explicit shared-contract case. Its
`ALPHUS_COMPLAINT_CONTRACTS` declaration lives beside the shared emitter in
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
the rejected neighbors. This establishes a bounded pattern for dynamic/shared emitters; the paired
numeric selector/config/runner registration now consumes it without changing
the existing matcher, IDs, diagnostics or selection behavior.

### Paired numeric registration: `numeric-literals` and `scipy-constants`

Both selectors declare their policy model, strict config field, catalog summary,
applicability, domains, shared complaint-contract name and lazy runner beside
the existing checker. Generated views provide the strict `CheckPolicies`
fields, selector types, `RuleSpec`, morphology, inventory and dispatch thunks.
The central review runner no longer imports these two providers during catalog
or CLI startup. Typed adapters require the existing policies and call the
unchanged checkers; matching, output IDs, messages, severities and selection
semantics are preserved.

The declaration also owns each check's stable CLI display name and its
configured source-scan inventory mode. Generated metadata feeds the existing
file-selection and plain-rendering paths, removing these selectors from the
CLI's legacy source-scan and review-label lists. Legacy selectors still use
those fallbacks until their own migration.

Tests cover generated strict fields, unknown-field rejection, shared complaint
IDs, direct and profile reporting, configured source selection, stable plain
labels, and that selecting one provider leaves the other unloaded. The
[paired numeric wheel differential]
[numeric-registration-differential] compares the pinned mainline wheel with
candidate `409c06d` across 40 manifested scenarios. The 62-selector catalog
and registration contract match, direct/profile outputs and invalid-config
behavior match, and no differences were reported. Numeric selectors already
had direct behavior evidence before this slice, so this adds profile and strict
config evidence but does not increase the behaviorally exercised count. The
follow-up [numeric CLI metadata differential]
[numeric-cli-metadata-differential] records the declaration-owned source-scan
mode and plain labels across 42 scenarios with no differences, while retaining
the same 62-selector catalog. The new cases assert both legacy numeric labels
verbatim; the remaining 48 selectors still lack behavior-level evidence.

`FeatureDefinition.policy_field` remains the primary compatibility binding.
Feature declarations can also name validated `policy_inputs`; the
package-boundaries slice declares its primary package policy plus the existing
architecture-graph, version-sync and callable-registry fields. A feature-owned
router composes those configured providers while `RuleSpec.policy_field`, the
public selector and strict TOML names remain unchanged. This is one proven
composite, not yet a generic provider-graph API. Its history digest still has
a separate known input gap. Do not change legacy history cohorts during
registration work.

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

The six-check morphology pilot proves metadata discovery. Eighteen selectors
now use feature-owned runtime registration: generated views derive strict policy
fields, selector typing, `RuleSpec`, inventory and lazy dispatch while sharing
the existing result adaptation and reporting. The slices cover file-local
checks, a composite, bounded heuristics, native polyglot analysis, distinct
language-specific readers for a shared concern, and two selectors sharing one
complaint contract. Pinned wheel reports remain the evidence boundary; these
slices do not prove all 62 selectors or complete issue #87.

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

The feature-owned declaration in `gates/source/cyclomatic_complexity.py` now
generates the existing `cyclomatic_complexity` strict policy field, selector,
`RuleSpec`, audit inventory entry, and lazy runner thunk. Its
`run_cyclomatic_rule` adapter retains the established report path and calls the
same native engine. The former central catalog entry, source-runner binding,
and hand-authored `CheckPolicies` field were removed. Direct selection, profile
steps, TOML names and report adaptation stay the same.

The preceding slice moved `CyclomaticPlan`, backend plans, results, metrics
and `CyclomaticReport` into the lightweight `contracts.cyclomatic` module; the
engine continues to re-export those names for import compatibility. The direct
runner and CLI keep their selected-path loading behavior. The parallel profile
adapter now resolves its planning, backend-failure, reduction, and reporting
operations from a typed `CyclomaticRuleOperations` contract selected by the
registered `cyclomatic-report` result shape. This removes the parallel module's
separate function-name/import list while keeping the native analyzer unloaded
until that specialized result path is requested. Subprocess coverage verifies
that importing the CLI, dispatcher and generic worker does not import the
native analyzer. Differential wheel scenarios and the full package suite cover
selected Python/Ruff, JavaScript/ESLint, and C++/Lizard behavior, including
report, failure, unsupported and coverage outcomes.

The backend's effective options are represented internally as named
`CyclomaticOption` records. The report adapter deliberately keeps the existing
two-item JSON arrays for wire compatibility; the tuples named in review were
internal contract records on older revisions and no longer form the Python
model.

Pinned cyclomatic differential evidence compares reference
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with candidate
`04b4e0378b2f24edf9f1ddacefec18c85d409c38`. All 30 manifested scenarios matched;
the 62-selector catalogs and registration contracts were equal. The matrix
exercised Python/Ruff, JavaScript/ESLint, C++/Lizard, missing and mismatched
backends, and partial coverage. Thirteen built-in selectors had behavior-level
differential evidence, leaving 49 baseline selectors without that evidence.
This proves the cyclomatic registration slice against manifested scenarios,
not full 62-selector equivalence. Re-run the wheel harness with `--output`
directed to a temporary file to inspect its detailed comparison record.

### Cross-language bounded heuristic: `output-escaping`

`output-escaping` now owns an `ALPHUS_CHECK` declaration and a static
complaint contract in `gates/source/output_escaping.py`. The contract binds
one human concern to the existing Python and JavaScript `RuleTag` identities;
the runtime adapter selects the tag by the provider's language scope. This
avoids duplicate ID declarations while retaining distinct language-specific
implementations and findings.

The declaration generates the existing strict `checks.output_escaping`
policy field, selector, `RuleSpec`, inventory entry, morphology metadata and
lazy runner thunk. `SourceScanPolicy`, its TOML keys, the checker implementation,
plain output and result adaptation remain unchanged. The `alphus` root-package
export is resolved lazily to preserve its public import path while keeping both
language providers unloaded during ordinary CLI startup.

The wheel matrix exercises strict unknown-field rejection, Python and
JavaScript findings with their original scoped IDs, and direct plus profile
result adaptation. Pinned output-escaping differential evidence compares
baseline `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with candidate
`322f27a67f23aa9de917881590c030585a2c1cc9`; all 33 manifested scenarios
matched with zero differences, and both 62-selector catalogs and registration
contracts were equal. Direct and profile scenarios verified both scoped
finding IDs, and invalid configuration rejected an unknown policy field.
Thirteen selectors had behavior-level differential evidence, leaving 49
without that evidence. This does not prove full selector equivalence. The slice
adds no languages, detection behavior or severity changes.

### Shared concern, distinct comment readers: `comment-markers`

`comment-markers` now owns the strict `CommentMarkerPolicy` binding, catalog
entry, selector, morphology and lazy runner through its declaration in
`gates/hygiene/comment_markers.py`. The existing Python tokenizer, TOML string-aware
reader and bounded slash-comment readers are unchanged. They share the
temporary-work-marker concern and public finding ID, but their parsing limits
remain distinct; the JavaScript, C-family and Java readers are bounded lexical
scanners rather than language parsers. This migration adds no detector or
language behavior. The legacy selector summary and applicability labels remain
unchanged, while the feature's language/format metadata describes the accepted
configured suffix families.

The direct and profile wheel scenarios check findings from Python, JavaScript,
the shared C-family scanner via a `.cpp` fixture, Java and TOML, including
marker-like strings that must not become findings. They assert the Python
tokenizer-failure complaint ID as well. The
strict-config scenario rejects an unknown `comment_markers` field, and a
subprocess regression verifies an unselected run does not import the checker.
The installed-wheel report [comment-markers
differential][comment-markers-differential] compares baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with candidate
`5d1a6f5b81d7beebb5437677b897603eb42ce7ec`. All 36 manifested scenarios match;
the reference and candidate catalogs and registration contracts remain equal
at 62 selectors. Fourteen selectors now have behavior-level evidence, leaving
48 without it. This is representative evidence, not full selector equivalence.

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
run. Scenario-declared synthetic files are path-validated, bounded, materialized
only inside the frozen snapshot, and included in its tree hash; malformed source
can therefore be tested without placing invalid code in the repository. Exact
temporary paths are replaced with stable placeholders in the evidence.

The initial comparison used reference
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

The latest differential run compared baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with candidate
`ad45db3cdb52d4a3f9141782d3b06c057c904f23`. It recorded frozen fixture
identities, manifest and harness hashes, plugin source and wheel hashes,
per-scenario native dependencies, selected/analyzed file counts, and separate
built-in/plugin coverage. Its generated matrix invoked all 26 selectors with
configured policies and verified strict missing-policy rejection for the other
36. These checks exercise selection/config contracts; they do not count as
semantic behavior coverage. Reproduce the detailed record outside the repo:

```sh
PATH="$PWD/node_modules/.bin:$PATH" .venv/bin/python scripts/differential_wheels.py \
  --root . \
  --baseline c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e \
  --candidate ad45db3cdb52d4a3f9141782d3b06c057c904f23 \
  --output /tmp/alphus-morphology-wheel-differential.json
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
contracts. Its pinned line-length differential run recorded equal catalogs
and no differences across 22 scenarios, including direct
line-length output and profile serial/parallel execution. Nine of the 62
selectors have behavior-level evidence; the remaining 53 still lack it. The
26 configured direct invocations and 36 strict missing-policy rejections are
selection/config evidence, not semantic coverage. Installed-wheel validation
on the line-length candidate passed 27 self-profile checks and 2,432 tests
(43 skipped). Neither slice proves full equivalence or completes #87.

## Composite registration slice: `package-boundaries`

`package-boundaries` now owns one static `ALPHUS_CHECK` declaration beside its
runner. The declaration supplies the selector, primary policy, four effective
policy inputs, output contract and lazy runner binding. Generated views provide
the feature definition, catalog `RuleSpec`, strict primary `CheckPolicies`
field, selector literal, morphology view and dispatch thunk. The secondary
policy fields remain in their existing strict models because they are also
used elsewhere; the declaration names them explicitly rather than copying
their schemas.

The existing composite emits findings from package-boundary, architecture
graph, version-sync and callable-registry engines. Their stable RuleTags are
owned by one statically parsed complaint contract in
`gates/repository/composite_contracts.py`; all four engines resolve through
that contract. The router imports optional providers only when their policy is
configured, and generated dispatch imports the feature runner only when this
selector is selected. The scheduler's `after` dependencies remain ordering
only. No public IDs, configuration keys, finding adapters, selection rules,
report shape or enforcement thresholds change.

Regression coverage checks strict policy parsing, direct dispatch, profile
dispatch and that an unselected composite leaves its checker modules unloaded.
The differential matrix exercises both direct JSON findings and an explicitly
selected profile step with all four policy inputs. This extends compatibility
evidence for one difficult composite; the remaining legacy selectors and
effectful command/build paths still require behavior-level coverage.

The pinned composite differential run compares
reference `c880093` with candidate `87f01a0190191ed62f5657e2fd623cca21ea1fdd`.
All 24 manifested scenarios match; both catalogs contain the same 62 selectors,
and the composite direct and profile scenarios have identical fixture hashes,
exit behavior, findings and order. Ten built-in selectors have behavior-level
differential evidence, leaving 52 baseline selectors without that evidence.
The provider import trace is also exercised by the installed-wheel self-profile
test, while remaining a separate non-serialized capability in the comparison
report.

## Repository layout registration slice: `repository-layout`

`repository-layout` now declares its feature metadata beside
`check_repository_layout` in `gates/repository/repository_layout.py`. That
declaration generates its `RuleSpec`, strict `CheckPolicies.repository_layout`
field, selector type, morphology catalog, audit inventory and lazy dispatch
thunk. The theme runner no longer imports or lists this checker, and the
existing `RepositoryLayoutPolicy`, TOML field name, tracked-file inventory,
finding IDs, human renderer and result adapter remain intact.

Focused tests exercise strict config rejection, typed direct dispatch, the
stable `path-required` finding, profile selection with the existing severity
override, and the fact that an unselected run does not import the feature
module. The pinned wheel matrix now contains direct and profile cases for this
selector; a final matched-fixture differential report is still pending and
must be recorded before claiming slice equivalence.

The change moves one selector out of the repository theme map and legacy
catalog entry without changing package-boundaries' independent composite
inputs. It provides a second repository-package migration case and does not
imply that other repository checks share this feature shape.

The repository-layout wheel differential compares reference
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with candidate
`4f63bfe6d73f2e2f7cb5fc992ce272ef96f17874`. All 26 manifested scenarios
match, both catalogs contain the same 62 selectors, and direct plus profile
repository-layout runs preserve finding IDs, order and exit behavior. Eleven
selectors now have behavior-level differential evidence; 51 baseline
selectors still lack it. Selection/config rows and catalog parity do not count
as semantic evidence for those remaining selectors.

## Dependency-lock registration slice: `dependency-locks`

`dependency-locks` now owns its `ALPHUS_CHECK` declaration and typed runner in
`gates/repository/dependency_locks.py`. Static generation provides its
`RuleSpec`, strict `CheckPolicies.dependency_locks` field, selector type,
morphology, audit inventory and lazy dispatch. The repository theme map no
longer owns this runner. The policy schema, direct selector, finding IDs,
message text and output adaptation remain unchanged.

Focused tests check the generated definition, strict rejection of unknown
policy fields, a typed direct dispatch with the established unsatisfied-pin
finding, and an unselected-run subprocess proving the provider stays unloaded.
Pinned direct and profile scenarios also exercise its existing severity and
profile-step behavior.

The dependency-lock wheel differential compares the baseline at
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with
candidate `f6e3434ab164be102927bd537dc78c3dddb792a4`. All 28 manifested
scenarios match and both installed-wheel catalogs contain the same 62
selectors. Twelve selectors now have behavior-level evidence; 50 still lack
it. Catalog and strict-config checks cover registration shape, not those
selectors' execution semantics.

## Documentation-config registration slice: `documentation-config`

`documentation-config` now owns its declaration and strict policy binding in
`gates/repository/documentation_config.py`. The static generator derives its
`RuleSpec`, `CheckPolicies.documentation_config` field, selector type,
morphology, audit inventory and lazy dispatch thunk. The repository runner map
no longer imports this checker. It still reads the Git-backed inventory and
uses the same bounded syntax/value subset; a heuristic match remains advisory,
with uncertain claims reported separately from conflicts.

Focused coverage checks the generated feature contract, strict rejection of
unknown settings, the established conflict finding ID/location/severity, and
that an unselected run does not import this checker. The pinned direct and
profile cases exercise a source default and contradictory Markdown claim,
including the warning-level profile result.

The documentation-config wheel differential compares main baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with source
candidate `6b41a039c995d8cb9ff3c8f71f1bdf52dae81583`. All 30 manifested
scenarios match, catalogs match at 62 selectors, and the registered check
preserves the conflict ID, location, severity, message, and profile behavior.
Thirteen selectors now have behavior-level evidence; 49 remain without it.

## Module-role registration slice: `module-roles`

`module-roles` now owns its `FeatureDefinition`, morphology, and typed runner
beside the existing analyzer in `src/alphus/gates/python/module_roles.py`. The
generated feature-policy base now supplies `CheckPolicies.module_roles`; the
legacy catalog entry and repository runner-map entry were removed. The
`ModuleRolePolicy` class, TOML field names, selector, finding IDs and messages,
ordering, and public JSON/profile behavior remain unchanged. The checker still
analyzes only paths named by its strict policy; this migration adds no source
discovery or new rule semantics.

The source-mirroring engine tests continue to cover the detailed AST cases. The
wheel matrix adds direct findings and stable IDs, explicit profile execution
with warning-threshold behavior compared serially and in parallel, and strict
rejection of an unknown policy field. Against pinned main
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, candidate
`ea3d412677f82580fd5f9f5960f8459b6a898872` produced identical catalogs at 62
selectors and no differences across 45 manifested scenarios. The exact wheels
had SHA-256 `278908f16ddc0f6595f8e2308e8ba7dfc121b6aac2637114b1a38b84e5cbd8f5`
and `b4f0bf32093a66d79ebf02c5e6afd99998a9f8cd1c6caca6c4639e29b7e48d85`
respectively. Fifteen selectors have behavior-level differential evidence;
47 still lack it. The other 26 direct selector dispatches and 36 strict
missing-policy rejections establish selection/config contracts, not semantic
equivalence. The run report was written outside the repository at
`/tmp/alphus-morphology-module-roles-ea3d412.json`.

### Static declaration reader cost and boundary

Feature additions use ordinary typed Python declarations, but build-time
discovery does not execute them. `scripts/generate_morphology_manifest.py`
statically recognizes module-level `ALPHUS_CHECK`, `ALPHUS_MORPHOLOGY`, and
`ALPHUS_FEATURE` assignments. Its supported forms are bounded: typed
constructors, literal strings/booleans/tuples, imported policy-model classes,
literal `RuleTag` calls, and an `ALPHUS_FEATURE` linking the local declarations
to one synchronous local runner. It rejects computed metadata, expanded
arguments, indirect providers, and arbitrary helper evaluation at build time.
This is a static reader for that contract, not a general Python interpreter.

The migration did not add expression handling to the reader. One feature
declaration and runner were added beside the check; the legacy catalog entry,
runner-map entry, and policy field were removed. Generated selector/config/
catalog/dispatch views and wheel metadata followed from the declaration. The
differential adds three behavior cases and a small fixture. The normal addition
still requires a local morphology declaration listing its stable complaint
tags, while avoiding central selector/config/runner edits.

The maintenance cost is real: the complete generator is currently 1,846 lines
and its focused tests are 803 lines; those totals include inventory, code
generation, filesystem boundaries, and safety validation in addition to
declaration parsing. Keep the accepted syntax documented and test every
extension with positive and rejected-neighbor cases. Do not grow an expression
evaluator for convenience. If production checks repeatedly require dynamic
declaration expressions, re-evaluate the source format and packaging boundary
as a design decision instead of approximating Python semantics incrementally.

The migration also exposed an editable-install metadata edge: source
`alphus.egg-info` can lag the installed editable distribution. Runtime lookup
now considers only Alphus-named distributions and selects a catalog whose
selector set exactly matches generated feature definitions. A stale source
metadata copy cannot shadow the current editable install; absence of a matching
catalog or conflicting matching distributions fails closed. This metadata
check imports no gate modules, and a selected feature remains lazy until run.

## Markdown shell-fence registration slice: `markdown-shell-fences`

`markdown-shell-fences` now owns its typed feature declaration and dispatcher
adapter beside the existing CommonMark-backed analyzer in
`src/alphus/gates/markdown/shell_fences.py`. The empty Markdown runner map, the
legacy catalog entry, and the handwritten `CheckPolicies` field were removed;
the generated feature-policy base now supplies the same strict policy type.
The public TOML key, selector, finding ID/message/location, informational
severity, result adapter, and `markdown-shell-review` profile behavior are
unchanged. The adapter still lets the checker select configured Markdown files
from Git inventory; registration did not execute shell text or broaden its
syntax evidence.

The existing source-mirroring tests under `tests/gates/markdown/` already
exercise the direct dispatcher path. The installed-wheel matrix adds a
configured source-scan fixture with a direct selector invocation and a profile
run in serial and parallel. Against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, candidate
`a39dcd3d1a6fdef39d345d7cb9b592972d1e8ff4` produced identical catalogs at 62
selectors and no differences across 47 scenarios. The exact wheel SHA-256
values were `9686d9217ee8de379a5e823ae90905d9648f31c60e877c7be44b682667f41fe5`
and `54d46acd540e0875e97c5187adf711811cd7441d83e355daa3f5a08de403782f`.
Nineteen selectors have behavior-level differential evidence; 43 still lack
it. The run report is `/tmp/alphus-morphology-markdown-shell-a39dcd3.json`.

This slice adds one declaration and one typed adapter beside the analyzer,
removes one catalog/policy/runner registration, and adds one fixture plus two
wheel scenarios. The analyzer module is already large, so this is not evidence
that registration ergonomics scale indefinitely inside monolithic gate files.
The static reader requires the declaration and synchronous adapter in the
same module as the implementation. For new features, prefer a small
feature-owned implementation module with its mirrored `tests/gates/...`

## Shared Git policy registration slice

The three repository Git selectors now each own a typed declaration and
runner adapter beside the checker in `src/alphus/gates/vcs/`. They share the
existing strict `GitRepositoryPolicy` under the existing TOML key
`checks.git`; the manifest generator coalesces declarations that use the same
policy field only when their model types match, and rejects conflicting model
types. This keeps the shared policy contract while removing the VCS runner map
and the three legacy catalog registrations. The declarations preserve the
baseline catalog summaries, applicability labels, empty domain list, public
selectors, and finding IDs. Their named complaint contracts remain shared by
all three emitters.

`tests/differential/fixtures/vcs-git/` provides one fixture with a real
generated-output contract, an effective Git attribute mismatch, and a tracked
generated history path. The wheel manifest invokes each selector directly and
runs all three in an explicitly selected profile with serial and parallel job
settings. Against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, candidate
`15a4333b3a7cc6a3fde6e8346868f79c9b36e114` retained identical 62-selector
catalogs and had no differences across all 51 manifested scenarios. The
registered-check profile result order, IDs, locations, message and exit
semantics matched. Reference and candidate wheel SHA-256 values were
`7329bced4573c9da2a5a5c683810676bc4f265fd25829399edcac147dad6d2c6` and
`424abfaefface6b72faacef7f8fbca75e2fd66212f15495cd813669020fa6cec`.
The harness records 19 behaviorally exercised selectors; 43 still lack
behavior-level evidence. The exact report is
`/tmp/alphus-morphology-git-vcs-15a4333.json`. This batch demonstrates shared
typed policy ownership across three feature registrations, not universal
equivalence for the remaining selector inventory.
module; when an existing implementation is oversized, split it only as a
separately reviewed behavior-preserving move.

## Static declaration design assessment

The current build reader is a constrained AST extractor rather than an
interpreter: it accepts typed declaration constructors with resolvable literal
fields, local synchronous runner names, static policy imports, and literal
complaint contracts. It never imports gate code at build time. That keeps the
feature authoring site typed and local while avoiding per-check edits to the
central entry-point table. It also creates a compatibility surface of its own:
the reader and its focused tests are large, declarations must fit the supported
static grammar, and their evolution needs positive and rejected-neighbor tests.

Conventional first-party entry points would eliminate this parser but require
each feature branch to edit shared packaging metadata, recreating the merge
conflict that this migration is meant to remove. Arbitrary import-time
registration would avoid parsing Python syntax but execute feature code during
discovery and complicate lazy loading and failure isolation. A second
feature-specific metadata language would merely move the parser burden. Keep
the current bounded reader for the 0.0.3 compatibility migration, do not add
expression evaluation, and treat repeated grammar friction as a decision point
for a future standard packaging mechanism. Measure the authoring footprint and
reader/test maintenance for the remaining shapes before declaring this the
permanent extension API.

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
and bounded runtime registration slices for thirty-one selectors documented
below.

## FastAPI review registration slice

`fastapi-practices` now owns `ALPHUS_CHECK`, its stable complaint contract,
morphology and typed `BuiltinFeature` adapter in
`gates/review/frameworks/fastapi_practices.py`. The adapter requires the existing
strict `FastApiPracticePolicy` and returns the established `list[Finding]`
contract. Its single policy includes the optional consumer application path;
when unset, the source AST provider does not import FastAPI or Starlette. When
set, the existing composite review loads the application and evaluates route
and OpenAPI evidence. Registration adds no new detector semantics.

The generated catalog preserves the original summary, applicability labels,
TOML field, selector, finding IDs and output shape. The legacy catalog entry,
runner entry, CLI label fallback and duplicate hand-maintained policy field were
removed. A source-mirroring registration test exercises strict config, direct
dispatch, the composite application path when the optional test extra is
available, and an unselected-provider import trace. Wheel scenarios cover
direct JSON, serial and parallel profile JSON, and invalid config. Against
reference `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, candidate
`f53f46cdecb33edf890fd4ad49092dfe17dc0fbf` produced identical 62-selector
catalogs and no differences across 71 scenarios. The three FastAPI scenarios
used identical fixture SHA-256 and Git identities in both installs; direct and
profile runs returned exit 0, strict invalid configuration returned exit 2, and
serial/parallel profiles matched. The reference/candidate wheel SHA-256 values
were
`94833f60a8acaeb2630bb8a0f1adb36be75dfcb6c948781c9696aa9cd0db284e` and
`36bce052f851bd3c9190056f93b9b5e9f215393f6154e7aff8aa208188673aa2`. The
report from that run was written to
`/tmp/alphus-morphology-fastapi-f53f46c.json`. At that candidate, 25 selectors
had behavior-level evidence and 37 lacked it; the later quaternion slice below
adds six selectors to the current evidence set. The
registered optional application/OpenAPI branch is covered by unit contracts;
the local registration test skips when the optional FastAPI test dependency is
absent. The wheel scenarios keep dependencies matched to the existing fixture
environment. The positive source fixture is excluded only from the self FastAPI
detector (with a reason); its wheel scenario asserts the warning and exact
source line, while Ruff, formatting and typing still inspect it.

The full local wheel self-quality run on `f53f46c` passed: 2,508 package tests,
27 profile checks, and the Markdown shell review; 44 tests were skipped and
four profile checks were provisional. No profile checks failed.

## Quaternion registration slice

The six configured Python quaternion checks now own their typed
`FeatureDefinition`, `RuleMorphology`, and `BuiltinFeature` in the checker
modules under `src/alphus/gates/review/numerical/quaternions/`. Each feature declares its
existing strict policy type and field, stable selector, finding output shape,
catalog description, and typed runner. Its morphology metadata records the
shared quaternion-operation concern, bounded-heuristic claim, Python scope,
evidence kinds, and synthetic-only evaluation maturity. The detectors remain
separate because each recognizes a different syntax shape and policy; this
does not claim that all quaternion implementations or other languages are
covered.

The legacy runner, catalog, CLI fallback and duplicate `CheckPolicies` fields
for these selectors were removed. Generated policy fields and entry points
continue to support strict TOML validation and lazy feature loading. Existing
catalog JSON is unchanged: `applies_to` still contains `python` and
`numerical`, with an empty `domains` list. The audit test derives its numerical
selector set from those catalog applicability labels instead of keeping a
second selector list. New direct JSON scenarios assert each finding ID and
detector evidence line; a profile scenario asserts the selected rule order and
all six findings, and an invalid-config scenario checks rejection of an
unknown setting.

The pinned-wheel comparison used baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` and candidate
`6e6ad89860d82019c13910062f9182aa3cbdfae3`. Its 79 scenarios produced
identical 62-selector catalogs and no differences. The reference and candidate
wheel SHA-256 values were
`8b2e87e83ca2edf6ad60f71bfd51a70560c976b5d603d9bba6d60768f3d867c6` and
`b4637522b6d374ff64e4842a0d6fb7c07ca98e0b6f3044b6013b4207551c9e08`.
The local report was written to `/tmp/alphus-morphology-differential-6e6ad89.json`
and was not checked into the repository. Its behavioral coverage is 31 of 62
selectors; 31 remain without behavior-level
scenario evidence. The dispatch matrix directly invoked 26 configured
selectors and checked strict missing-policy rejection for 36 others. This is
slice evidence, not full built-in equivalence.

The differential harness also now installs exact-pinned Python analyzer
packages into each temporary wheel environment, installs the pinned ESLint
package into one shared temporary npm prefix, and isolates native scenario
PATH while exposing Git and the required Node runtime. This closes a local
environment gap where global Ruff metadata did not provide a matching CLI and
ESLint was unavailable. The reports record the npm tool-tree digest and each
scenario's native isolation inputs. Existing selectors and native result
contracts remain unchanged.

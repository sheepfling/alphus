# Built-in check architecture and migration plan

This is the design entry point for the built-in check re-architecture planned
for Alphus 0.0.3. It defines the ownership boundaries, proposed registration
flow, compatibility proof, migration slices, and deferred work. The existing
check behavior is the compatibility baseline; this document does not itself
change runtime behavior.

## Current implementation snapshot

Use this section for live status. The detailed migration records below preserve
evidence from earlier commits; their selector counts describe those historical
heads and are not current inventory claims. The current PR branch has all 62
built-in selectors on feature-owned typed registration modules, one per
selector. The build backend derives the installed
`alphus.builtin_checks.v1` entry points and ignored
aggregate policy/config/dispatch views from those declarations; adding a
feature does not require editing `pyproject.toml`, a central selector map, or
tracked generated views.

The declaration path is typed Python, not tuple metadata: `ALPHUS_CHECK` is a
`FeatureDefinition`, `ALPHUS_MORPHOLOGY` is a `RuleMorphology`, and
`ALPHUS_FEATURE` is a typed feature form with a direct runner reference. Build
discovery parses a deliberately bounded subset of those actual Python
constructors without importing or executing gate modules. The constraint is
real: the feature object must directly link its local check, morphology and
synchronous local runner function. Computed declarations, imported runners,
or provider factories need a small local adapter or a separate design. Pyright
and runtime result-shape validation complement the static build check; the
build parser itself does not prove the runner's return annotation.

The registration package now provides immutable shape-specific forms with
narrow runner protocols: `FindingBuiltinFeature`,
`CompositeFindingBuiltinFeature`, `MessageBuiltinFeature`,
`PythonStyleBuiltinFeature`, `SharedUtilitiesBuiltinFeature`, and
`CyclomaticBuiltinFeature`. Their constructors require the corresponding return
type; each form also checks its declared shape. Static build discovery rejects
a typed constructor paired with a different `FeatureDefinition.output_shape`.
This binds the authoring declaration's output protocol to its output shape
without changing the shared dispatch boundary.

The loader now returns a disjoint union of the typed forms and the broad
legacy form, so execution narrows by registered form before widening to the
existing `RuleOutput` adapter. This avoids casts and keeps the result type
attached to the actual runner call. Ordinary typed runners take the stable root,
selected files, and resolved primary policy. Legacy
three-argument runners keep their original signature. Pyright checks each
concrete runner signature and result type; static
build discovery checks its result form against `FeatureDefinition.output_shape`,
and runtime loading checks the return annotation and value.

Primary policy binding is explicit for typed forms. Their generic resolver
returns a concrete policy type and ordinary typed runners receive only that
policy, not aggregate config. Pyright checks the runner/resolver pair; runtime
registration checks both annotations against `FeatureDefinition.policy_model`,
and dispatch verifies the resolved value before invocation. The concrete
policy class still derives the generated strict `CheckPolicies` field.
`CompositeFindingBuiltinFeature` is the explicit exception: it receives the
aggregate config for named secondary policies as well as the typed primary
policy. Its runner result stays typed as findings. Legacy three-argument
runners are unchanged.

The forms distinguish result and required operations, not analyzer claim
strength or backend. A future genuinely different input contract should add a
named shape only when an existing check needs it.

The representative shapes include file-local findings (`file-size`), a
composite finding check (`package-boundaries`), messages (`cli`), and the
native polyglot report (`cyclomatic-complexity`). Cyclomatic's operations
object is required by its form. All 62 built-ins use narrow typed feature
forms. `BuiltinFeature` remains a concrete broad-result compatibility form in
the registration union, but no current selector uses it. The narrow forms do
not inherit from it. Dynamic entry-point lookup returns a disjoint union.
A generated, ignored `builtin_registry.pyi` overload view maps each literal
selector to its feature form and primary policy type; dynamic strings retain
the full registration union.
The view is derived from the same feature-owned declarations during the
build, so it adds neither a second selector list nor a tracked merge-conflict
file.
Dispatch narrows the loaded form, then adapts its typed result to the existing
`RuleOutput`; public result adapters and wire behavior remain unchanged.

The lightweight `StyleFindings` contract now lives in `alphus.contracts`, so
CLI, registry, and result-adapter imports do not load the Python style analyzer.
`PythonStyleBuiltinFeature` can use that contract without importing the
analyzer for catalog or config inspection.

The 0.0.3 shapes currently fit without forcing one result type:

The current inventory exercises these distinct shapes:

- **File-local findings:** `file-size` and `line-length` use explicit feature
  runners and return the existing `Finding` output.
- **Heuristic or prose risk:** `python-style`, `benchmark-docs`, and
  `positional-semantic-overrides` keep concern and claim separate from their
  existing finding or typed category-mapping outputs.
- **Cross-file composite:** `package-boundaries` consumes secondary policy
  fields and preserves the existing ordered findings.
- **Native polyglot analysis:** `cyclomatic-complexity` keeps its backend
  plans, provenance, and `CyclomaticReport` in `CyclomaticRuleOperations`.
- **Effectful command/build:** configured `CommandRunStep`, including the PDF
  consumer profile, returns process/step results and artifacts. It is not
  auto-registered as a finding check.

So “everything fits a shape” is true at the orchestration boundary, where
selected work can be planned and scheduled, while role-specific outputs remain
typed. Commands are explicit consumer configuration; feature registration
does not discover or enable them. Plugin API v1 also remains a separate,
explicit trust boundary. No universal result payload or selector identity is
needed for those roles.

The 62 distinct registration modules and ignored generated aggregates remove
the shared registry/config/catalog/runner edit for a built-in registration.
They do not eliminate conflicts in genuinely shared policy models, analyzers,
CLI code, or common result adapters. The two-branch installed-wheel merge test
is an architecture fixture, not a production-contribution trial. Treat reduced
registration friction as a structural property, not as a measured reduction
in review time. Measure correction categories and registration edits in future
parallel contributions instead of inferring productivity from this migration.

The current scenario manifest has 154 entries: 147 behavioral scenarios, five
controls, and two planned-only entries. The package-boundaries history
identity includes all declared secondary policy inputs under identity version
2. That deliberate change starts a distinct cohort, so its history case is not
asserted equal to the baseline wheel. One planned-only case describes
unsupported native capabilities; the other checks profile planning. Neither
claims analyzer execution. The effectful command and plugin-failure cases
execute.

On exact head `1eabe25fcfb940c7674b77e1246b2cc3049e59ae`, four hosted workflows
passed and Alphus self-quality failed in its differential step. The duplicate
plugin-entry-point case correctly stopped during strict config loading, whose
public CLI diagnostic is generic stderr text, but the scenario expected JSON
and the internal registry reason. It now expects the public diagnostic and
checks that neither plugin module imported. A preflight reads installed
entry-point metadata and requires at least two `diff` entries without loading
providers, preventing a missing-plugin error from masquerading as duplicate
coverage. Unit tests assert the exact duplicate-name error. The earlier
unsupported-native-plan fixture was also corrected. A new exact-head
comparison is pending. On the current working
diff, the full self-profile passes (27 passed, zero
failed, four provisional), with 2,606 package tests passed and 44 skipped.
Ruff, formatting, strict Pyright (0 errors), imports, documentation line
length, focused manifest tests, and `git diff --check` also pass. An
unfiltered local pytest run separately had five environment failures: four
wheel/version tests could not fetch PyPI build dependencies, and one Ruff
fixture could not write its cache. Any future differential result proves
parity only for finite scenarios
designated for comparison, not every possible input. The versioned history
identity and planned-only entries are not baseline-equivalence claims. Older
candidate failures and partial comparisons remain historical evidence.

Older candidate failures and partial comparisons remain historical migration
evidence. The current local checks are listed above; hosted exact-head checks
for the corrected duplicate-entry scenario remain pending.

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
implementation replaces that tuple format for all 62 built-in selectors with
immutable `FeatureDefinition` and `RuleMorphology` values plus a narrow,
shape-specific typed execution object. The concrete `BuiltinFeature` class is
retained only as a broad-result compatibility fallback; it is not a base class.
A PEP 517 build backend statically reads those declarations and writes standard
`alphus.builtin_checks.v1` metadata into ignored build output. Runtime lookup
uses `importlib.metadata` against Alphus-named distributions and selects the
entry-point catalog matching generated feature definitions. It imports only the
selected feature object on demand. Its object owns direct typed
runner references and the cyclomatic-specific operations contract. Entry-point
metadata targets `ALPHUS_FEATURE`; selector and policy metadata no longer store
runner module/function strings, and policy models are class objects derived
from `StrictModel`. The loader rejects asynchronous providers and checks the
result annotation against the declared output shape before dispatch. The
third-party `alphus.rules.v1` contract remains separate and allowlisted. The
current registration state and bounded behavior-equivalence evidence are
summarized above. The prototype history and trade-offs are recorded in the
[check registry spike](architecture/check-registry-spike.md).

## Release boundary and status vocabulary

Alphus 0.0.3 is a structure and compatibility release: the same checks and
consumer-visible behavior with clearer ownership, fewer duplicate
registrations, and a less fragile review path. Alphus 0.0.4 is the planned
feature release for new detectors, new language coverage, round-two Bacflow,
and local-model-assisted execution. Persistent result caching, automatic
repository setup, and history/index migrations remain separately scoped until
their contracts and need are established.

The inventory test generates current and pinned-baseline inventories into
temporary files from their source trees, then compares registration contracts.
No generated JSON baseline is committed. This is an objective registration
check, not a wheel behavior comparison. The latest pinned wheel comparison did
not pass for the current 154-scenario manifest; see the current status above.
Prior comparisons apply only to their recorded earlier manifests and commits.

This document distinguishes four kinds of statement:

- **Current behavior** is verified in the named source modules and inventory.
- **Design** is the proposed target and is not implemented by this document.
- **Migration proof** is a required test or measured comparison, not an
  assertion that it has already passed.
- **Open decision** is called out explicitly below and must not be resolved by
  silently changing consumer behavior.

PR #100 remains an open draft. It began with the six-check morphology metadata
pilot and now has all 62 built-in selectors on feature-owned generated runtime
views. The statically discovered selector inventory is the source of truth; it
is deliberately not duplicated here as another selector list. Each local
`ALPHUS_CHECK` declaration statically generates morphology metadata, typed
`FeatureDefinition`, `RuleSpec`, strict policy field, selector type, and
inventory entry. Each feature module exposes one typed `ALPHUS_FEATURE` object
with a direct callback for lazy execution. The established `RuleEvaluation`
and CLI result adapters remain shared, so adding a feature still uses the
existing output contract. Registration migration is complete for the existing
selector set; behavior equivalence for the current manifest remains in
progress and is not exhaustive. These declarations are now typed
`FeatureDefinition(...)` calls
paired with immutable
`RuleMorphology(...)` values rather than the former tuple-pair `ALPHUS_CHECK`
format. Static discovery validates them without importing gate implementations.
The PEP 517 backend generates installed-wheel entry-point metadata without a
per-check `pyproject.toml` edit. Aggregate policy/config/dispatch views are
ignored build artifacts rather than checked-in shared files, so independent
feature branches do not edit the same generated outputs. Runtime entry points
target the typed feature object. Registration migration is complete for the
existing selector set; behavior equivalence remains in progress and finite.

### Review-comment dispositions

The six inline comments on the original pilot diff are still open GitHub
threads; the code and contributor documentation now have these dispositions:

- No generated JSON inventory is checked in. The inventory is produced on
  demand from current source and the pinned reference; comparison reports live
  in the caller's temporary directory or a workflow artifact.
- The wheel manifest models its immutable rows with the shared `StrictModel`,
  `Annotated` constraints, tuple fields, and direct `= ()` defaults for static
  empty values. Tests cover omitted defaults, JSON-array serialization, and
  rejection of explicit null. This does not claim Pydantic v2 assignment-form
  `Field` is deprecated.
- `scripts/__init__.py` makes `python -m scripts.generate_builtin_inventory`
  the supported invocation; there is no package-dependent import branch.
- Cyclomatic option pairs have the semantic `CyclomaticOption(name, value)`
  type internally. The existing public report serializer deliberately retains
  the two-element JSON arrays. Additional nested tuple-field coverage is
  tracked under [issue #48's review note](https://github.com/sheepfling/alphus/issues/48#issuecomment-6676590600).
- Parallel scheduling delegates cyclomatic-specific report operations through
  `cyclomatic_rule_operations()`, whose typed operations object is owned by
  the feature. The scheduler has no separate cyclomatic operation registry.
- Built-ins use feature-owned named declarations and typed execution forms;
  build-derived entry-point metadata and ignored aggregate views prevent
  per-feature edits to central authored registries or packaging tables.

These are implementation dispositions, not replies or resolutions of the
owner's GitHub threads. The Pydantic default-convention preference and broader
semantic guidance work remain tracked by
[issue #51](https://github.com/sheepfling/alphus/issues/51); they are distinct
from this compatibility-preserving manifest cleanup.

### Earlier candidate snapshots (historical; current status is above)

The source-discovery slice moved `json-structure` and `path-discovery`
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
  `require_rule`. All 62 built-in selector and strict policy contracts derive
  from feature-owned declarations into ignored generated views.
- **Rule metadata and catalog** — `alphus.policy.catalog` owns `RuleSpec`,
  `RULE_SPECS`, and `RuleOutputShape`.
- **Feature implementations** — `alphus.gates.<theme>` and
  `alphus.gates.languages.<language>` own checker functions and language
  adapters. Each built-in selector's typed registration sits beside its owner;
  shared analyzers remain language- or concern-specific.
- **Runtime dispatch and third-party boundary** —
  `alphus.execution.dispatch` and `alphus.plugins` own selected built-in
  dispatch and plugin API v1. The built-in entry-point catalog and third-party
  plugin registry remain distinct trust boundaries.
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

The feature-owned registration flow is:

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
production path covers all 62 selectors. The five aggregate views are no
longer tracked: the build regenerates them as ignored source files for each
worktree, and
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

A typed feature declaration pairs its existing strict policy model with a
feature-local resolver and a runner that accepts the same policy type. The
build statically verifies the resolver is local and synchronous; Pyright checks
the resolver/runner type pair. The runtime loader verifies both annotations
against the declaration's policy model, and dispatch verifies the resolved
object before calling the runner. For example, the `file-size` feature owns
these references:

```python
ALPHUS_FEATURE: Final = FindingBuiltinFeature(
    definition=ALPHUS_CHECK,
    morphology=ALPHUS_MORPHOLOGY,
    runner=run_file_size_feature,
    policy_resolver=resolve_file_size_policy,
)
```

`resolve_file_size_policy` returns `FileSizePolicy`; `run_file_size_feature`
accepts that same type and returns `list[Finding]`. The existing
`check_file_size(root, files, config)` adapter remains unchanged for direct
callers.
Typed selector overloads derive both form and primary policy type from this same
declaration. Ordinary typed runners receive only the resolved primary policy.
For `package-boundaries`, `CompositeFindingBuiltinFeature` additionally exposes
`QualityGateConfig` for secondary policy inputs; its primary policy remains
explicitly typed.

The PEP 517 backend statically reads feature declarations and writes standard
`alphus.builtin_checks.v1` metadata under the ignored `.registry-build/`
directory. The runtime registry indexes entry points from Alphus-named
distributions whose selector set matches the generated feature catalog,
rejects duplicate selectors, and imports a runner only after explicit
selection. Adding a feature-owned check does not require editing a central
runner map or the `pyproject.toml` entry-point table.

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
Composite `policy_inputs` may name the owning feature's field and any other
feature-owned or legacy `CheckPolicies` field. Static discovery validates them
against the combined generated strict-policy view, so a composite can consume
another feature's policy without adding that field to a central authored list.

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
file-selection and plain-rendering paths. All built-ins now use generated,
feature-owned registration views; established labels and inventory behavior
remain compatibility contracts.

Tests cover generated strict fields, unknown-field rejection, shared complaint
IDs, direct and profile reporting, configured source selection, stable plain
labels, and that selecting one provider leaves the other unloaded. The earlier
40-, 42-, and 149-scenario candidate reports are historical. Current exact-head
status is summarized at the start of this document; the 154-entry manifest is
finite and not exhaustive.

`FeatureDefinition.policy_field` remains the primary compatibility binding.
Feature declarations can also name validated `policy_inputs`; the
package-boundaries slice declares its primary package policy plus the existing
architecture-graph, version-sync and callable-registry fields. A feature-owned
router composes those configured providers while `RuleSpec.policy_field`, the
public selector and strict TOML names remain unchanged. This is one proven
composite, not yet a generic provider-graph API. Its history identity now
hashes all declared secondary policies using identity version 2. New composite
runs therefore form a distinct cohort; archived history records and the index
schema are unchanged, and single-policy digest identities remain byte-for-byte
compatible.

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

Do not claim a time reduction from the design alone. The original pilot and
backflow correction baseline has not yet been reconstructed. Future slices
should record the commit diff, manually edited registration locations,
generator output, and elapsed implementation/review time. Also count human
corrections: accepted review comments that require a
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
new check; the migration itself remains a bounded, reviewed change. The
registration criterion is met for the current 62 selectors. The current
manifested wheel comparison is in progress after correcting a strict-config
fixture failure. Human correction effort and behavior outside manifested
scenarios have not been measured or proven equivalent.

The six-check morphology pilot proved metadata discovery but did not complete
runtime registration. At the current head, all 62 built-ins use feature-owned
typed forms and generated runtime views. Previous 149-scenario comparison
results apply only to their earlier manifest and candidate. Current coverage
remains bounded and does not prove every possible input or complete issue #87.

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

## Historical migration and differential records

Candidate-by-candidate evidence below records its named commit and is not live
status; use the snapshot at the start of this document for current results.

### First pinned-wheel differential result

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

### Runtime registration slices: `file-size` and `line-length`

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

### Composite registration slice: `package-boundaries`

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

### Repository layout registration slice: `repository-layout`

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

### Dependency-lock registration slice: `dependency-locks`

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

### Documentation-config registration slice: `documentation-config`

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

### Module-role registration slice: `module-roles`

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

### Markdown shell-fence registration slice: `markdown-shell-fences`

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

### Shared Git policy registration slice

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

The legacy profile digest had a source-backed gap. The package-boundaries
runner reads its primary policy and can additionally run architecture-graph,
version-sync, and callable-registry checks. The former `gate_manifest_entry`
hashed only the primary `RuleSpec.policy_field`, common file policy, and gate
settings, so changes to those secondary effective policies could leave the
recorded digest unchanged.

The source-backed gap was resolved in a dedicated, versioned identity change.
For any built-in declaration with secondary `policy_inputs`, the digest payload
now carries an explicit policy-identity version and hashes every declared
secondary field by name, including an unset (`null`) value. The ordinary
single-policy digest payload is unchanged. Tests prove that each of the three
package-boundaries secondary policies changes its gate digest, while those
settings do not change an unrelated single-policy gate digest.

Existing v1-v4 JSON archives are not rewritten, and the history archive schema
and rebuildable SQLite index schema are unchanged. New package-boundaries runs
form a distinct policy cohort from historical runs because their digest now
represents the effective composite policy. This deliberate cohort boundary
prevents new runs from being pooled with legacy runs whose digest omitted those
inputs. No historical policy is inferred or backfilled.

## Ordered migration slices

This sequence records the original execution plan, not remaining registration
work. Inventory, typed registration and migration of the existing selectors
have been carried out. The last exact-head manifested comparison failed before
producing a report because the duplicate-entry-point scenario expected JSON
from a strict-config failure. The local harness now validates duplicate
metadata before checking the public CLI error. Additional
coverage for deferred capabilities and inputs not represented in the manifest
remains open; do not describe the finite result as exhaustive.

1. **Inventory and reference baseline — complete.** Source-derived inventories
   compare current declarations with the pinned baseline without committed JSON.
2. **Typed registration contract — complete for current built-ins.** The build
   statically validates feature-owned declarations and generates ignored package
   views and entry-point metadata.
3. **Representative typed slices — complete.** File-local, composite, message,
   heuristic, native polyglot, and specialized result forms have compatibility
   tests.
4. **Built-in registration migration — complete for all 62 selectors.**
   Existing checker bodies, strict config names, selection and result behavior
   remain the compatibility target.
5. **Differential validation — in progress for 154 manifested scenarios.** The
   unsupported-native-plan fixture is corrected. The exact-head run exposed
   an incorrect JSON expectation for duplicate entry-point config rejection;
   the revised preflight and public-output assertion await a new wheel run.
   The finite comparison will not imply arbitrary-input equivalence.
6. **Remaining 0.0.3 review — in progress.** Reconcile accepted feedback, keep
   contributor guidance current, and retain finite compatibility evidence.

Persistent cache, automatic setup, history/index schema migrations, new
detector behavior, new language providers, local-model execution, and
round-two Bacflow are not hidden substeps of this sequence. The separately
versioned composite history identity is documented above.

## 0.0.4 backlog and unresolved decisions

The planned 0.0.4 boundary contains new detectors, new language/semantic
providers, local-model-assisted execution, and round-two Bacflow. Provider,
evidence, repeatability, provenance, lazy binding, and dependency declarations
from 0.0.3 are extension seams only; 0.0.3 should not ship dormant AI or cache
frameworks.

The 0.0.4 advisory backlog includes [#51's](https://github.com/sheepfling/alphus/issues/51)
conservative Pydantic default guidance and [#48's fixed-position tuple
review](https://github.com/sheepfling/alphus/issues/48#issuecomment-6676590600). The current
differential manifest uses immutable tuple fields with direct `= ()` defaults
for static empty collections; Pydantic v2 supports both `Annotated` metadata
and `Field` forms, so this is not a deprecation claim. The cyclomatic
`CyclomaticOption(name, value)` record gives the internal slots meaning while
its adapter preserves the existing two-element JSON arrays.

One release-readiness question remains: whether the planned-only scenario and
four deferred capabilities block #87's exit. Keep this finite evidence distinct
from exhaustive equivalence. The corrected history digest has focused unit
coverage and is intentionally excluded from baseline equality because the new
versioned cohort cannot equal the legacy digest.

PR #100 remains draft. Registration is complete for the current 62 built-ins;
the issue's broader exit status remains subject to review of deferred compatibility
cases.

## Historical selector migration reports

The sections below retain candidate-specific details. Treat them as historical
records, not current registration status; the current snapshot is above.

### FastAPI review registration slice

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

### Quaternion registration slice

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

### Coordinate-frame registration slice

The three configured coordinate-frame checks now declare their typed policy,
existing selector and result shape, morphology, and direct runner in their
own checker modules: `ecef-enu-transform`, `ecef-ned-matrix-transform`, and
`ned-basis-vectors`. Their strict policy fields are generated into the
existing `[checks.*]` contract, while the source-scanning algorithms and
public finding IDs stay unchanged. The feature-owned concerns describe
coordinate transforms and local basis construction separately; all three
remain bounded Python syntax checks with advisory findings.

The differential fixture exercises the three direct selectors and their
ordered profile, and rejects an unknown policy key before execution. It
asserts each existing rule ID, path, and finding line. These scenarios add
behavior-level coverage for three additional selectors; together with the
previous 31, 34 of 62 selectors now have direct behavior scenarios. The
remaining 28 are not behaviorally covered by the pinned-wheel harness yet.
This is another bounded slice, not full issue #87 completion.

The pinned installed-wheel run compared baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` with candidate
`69115c6bd61d606dc850f660d50eb9370138715e`. All 84 manifested scenarios
matched, the 62-selector catalog and registration contract were identical,
and the report contains no differences. The reference and candidate wheel
SHA-256 values are
`0cf5247f46c38a5c4cc09a3b59b07f3dd3c3042c241f0dc71122c3094f110f90` and
`53a0b95c24b97287e4a52e1fa5949334e1063c5e73ed7e6a0c7afe7aa25ddc48`.
The auxiliary selector-dispatch matrix directly invoked 26 minimal
configured selectors and rejected missing strict policy for 36; those counts
are distinct from the 34 selectors with behavior scenarios. The full report
is `/tmp/alphus-morphology-differential-69115c6.json` and is not committed.

### Linear-algebra registration slice

Candidate `e12bf496473bf930471e15674871c51bf46b006f` moves four configured
Python numerical reviewers into feature-owned typed registrations:
`manual-matrix-kernels`, `manual-elimination`, `array-representation-churn`,
and `cholesky-recurrence`. Each checker module now owns its `FeatureDefinition`,
`RuleMorphology`, and typed `BuiltinFeature` runner. The generated strict
policy fields and selectors, catalog entries, and installed-wheel entry points
derive from those declarations. The old catalog rows, `CheckPolicies` fields,
theme runner cases, and CLI source-scan selector entries were removed. The
analyzers, policy models, finding IDs, messages, severity, selection behavior,
and result adaptation remain unchanged.

At candidate `e12bf496`, the pinned installed-wheel comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 90 manifested
scenarios with zero differences. Both wheels expose the same 62-selector
catalog and registration contract. Behavior scenarios exercise 38 selectors;
24 have no behavior-level scenario yet. The separate selector-dispatch matrix
has 62 rows, with 26 minimal direct invocations and 36 strict missing-policy
rejections. Reference and candidate wheel SHA-256 values are
`578a7848fa2b6d2d2f9bda95cbb137ad051df290be88e38268c8a344d3fa9ca9` and
`c3efbff7643eb22e2115589240f15d1c52c00d117711bba49071b24519ffd555`.
The report is `/tmp/alphus-morphology-linear-algebra-e12bf49.json`; it is
reproducible from the pinned commits and is intentionally not committed as a
large JSON dump.

The four new direct scenarios assert existing finding IDs and source lines;
the profile scenario asserts the existing ordered result shape, and a separate
invalid-config fixture proves strict rejection. The manual-elimination source
fixture intentionally exercises mutable matrix input, so the self-check policy
excludes only that exact fixture from unrelated concrete-input and argument-
mutation reviews. Ruff, formatting, typing, and the differential scenario still
inspect it. The installed-wheel self-check passed 27 profile checks with zero
failures and four provisional checks; its package suite passed 2,507 tests
(44 skipped). This extends, but does not complete, the 0.0.3 migration or full
62-selector equivalence proof.

### Python text-analysis registration slice

Commit `33cf71276544baa74a34770dc41ccfee0b9379ad` moves the configured
`dynamic-markdown` and `embedded-semantic-overrides` checks from the review
runner/catalog into typed feature declarations beside their analyzers. The
declarations retain the existing selector strings, policy models, config
fields, RuleTag IDs, summaries, applicability, finding results and severities.
The AST heuristics, policy models and findings were not changed. Their
generated strict policy fields, selector/catalog entries and lazy wheel
entry-points now come from these feature-owned declarations; the two duplicate
catalog and review-runner entries were removed. `ALPHUS_MORPHOLOGY` describes
the risk claims and bounded deterministic evidence without changing
enforcement. The existing review test paths remain adjacent to these checks.

The fixture contains both source patterns. Separate direct scenarios and an
ordered two-check profile assert the prior finding IDs and locations, while an
unknown field proves strict config rejection. The pinned wheel comparison with
baseline `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 94 manifested
scenarios with zero differences. Both catalogs retain 62 selectors; behavior
scenarios exercise 40, with 22 lacking a behavior scenario. Direct dispatch
covers 26 selectors and strict missing-policy rejection covers 36. The
baseline and candidate wheel SHA-256 values are
`2a6dce3df25568d4b64f65e1b427772dc9863c593e0976efd0c52f33261bb903` and
`e3d832ad82f36b16466767f474a98c36e373ffefebb2d76641b7f871a368660f`. The
report is `/tmp/alphus-morphology-review-text-33cf712.json`; it is reproducible
from the pinned commits and is not committed.

The installed-wheel CI at this tree passed 2,508 tests (44 skipped); the
self-profile passed 27 checks with no failures and four provisional passes.
This closes the direct/profile/config evidence for this paired slice only.
It does not establish behavior equivalence for the 22 legacy registration
selectors or complete the 0.0.3 rearchitecture.

### Shared-policy prose registration slice

Commit `6bc8a0cda4a82286e893f96f42b13a66337c481a` moves
`prose-as-control` and `rendered-value-reparsed` into typed feature-owned
registrations. They are distinct selectors with distinct concerns and finding
IDs; both intentionally consume the same existing `prose_as_control` policy
model and strict TOML section. The prose check still combines its two existing
analyzers in the same result order. The rendered-value analyzer remains a
separate selected check. Their policies, syntax analysis, finding messages,
severities, selection and result adapters are unchanged. The central catalog
and runner entries were removed, while the single shared strict policy field
is generated from the feature declarations.

The fixture exercises the prose comparison, configured lossy rewrite, and
rendered-output predicate. Direct scenarios check each selector; the profile
checks combined findings and step order; an unknown field remains rejected.
The pinned wheel comparison with baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 98 manifested scenarios
with zero differences. Both catalogs retain 62 selectors. Behavior scenarios
exercise 42 selectors, leaving 20 without behavior-level scenarios. Direct
dispatch covers 26 selectors; strict missing-policy rejection covers 36.
Reference and candidate wheel SHA-256 values are
`a82f5cc90c495763aba876cd48f8ef2213f3fd086746df1052a2016efcc7118a` and
`e955e6bfc7d910f29019010811ab83a66d045cdc212ad82152d9975c6d2d7090`. The
report is `/tmp/alphus-morphology-shared-prose-6bc8a0c.json` and is not
committed.

The installed-wheel CI passed 2,510 package tests (44 skipped); its self-profile
passed 27 checks with zero failures and four provisional passes. This is
evidence for the paired shared-policy migration, not complete selector or
issue #87 equivalence.

### Positional-review registration slice

Commit `c7023fa14a12d71784a7fcb2c0d666334fcfcf0d` moves
`positional-interfaces` and `positional-semantic-overrides` from the manual
catalog, `CheckPolicies`, and review-runner maps into typed feature-owned
declarations beside the analyzers. Both are configured Python AST checks with
the existing findings output shape, but their concerns, strict policies and
stable RuleTag IDs remain distinct. Generated policy fields and lazy wheel
entry points derive from those declarations. The checkers, messages, severity,
selection and enforcement behavior remain unchanged.

The installed-wheel scenarios cover both direct selectors, an ordered
serial/parallel profile and strict unknown-field rejection. The pinned
comparison against baseline `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`
matched all 110 manifested scenarios with zero differences. Both catalogs
have 62 selectors; behavior scenarios exercise 48, leaving 14 selectors
without behavior-level coverage. The separate selector-policy matrix has 26
configured direct invocations and 36 strict missing-policy rejections.
Reference and candidate wheel SHA-256 values are
`d2878e2781296fd9539374b3121470060536682d9840b28f92ebce4b75397108` and
`c44cf1cb6ccfbd548e7c9ef70e0ec68a348cde42e6d432dc8472742b6b9eb198`.
The report is `/tmp/alphus-morphology-positional-c7023fa.json` and is not
committed.

Installed-wheel self-quality passed 2,510 tests with 44 skipped; the
self-profile passed 27 checks with zero failures and four provisional passes.
This slice adds no detector behavior. The remaining 14 selectors without
behavior-level scenarios and the broader compatibility requirements mean this
does not complete issue #87.

### Paired review-pipeline registration slice

Commit `3c2019ebfbd93f00dea52eaec103f665d22c6893` moves the existing
`parallel-normalization` and `patch-cascade` Python AST checks into typed
feature-owned registrations beside their analyzers. Their concern, strict
policy model, morphology and finding identity remain distinct. The review
runner, catalog rows and handwritten `CheckPolicies` fields were removed for
these two selectors; generated registration retains existing config names,
selection, finding output and exit behavior.

The installed-wheel fixture has direct JSON scenarios for both checks, an
ordered profile exercised with one and two workers, and strict rejection of an
unknown policy field. The pinned comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 114 manifested
scenarios with zero differences. Both catalogs retain 62 selectors; behavior
scenarios exercise 50, leaving 12 without behavior-level evidence. Direct
dispatch covers 26 selectors and strict missing-policy rejection covers 36.
Reference and candidate wheel SHA-256 values are
`621bbb585fe7a70ad01716fc26f07ec1ec7fdf86acd67d855877b37d03477312` and
`b5185fb6c9f4f4128c51381a1895607af3cfe2f78119832b9bf2a9f0da8188cd`.
The local report is `/tmp/alphus-morphology-review-pipelines-3c2019e.json`;
it is not committed.

Installed-wheel self-quality passed 2,510 tests (44 skipped); the self-profile
passed all 27 checks with zero failures and four provisional passes. This is
incremental evidence, not full 62-selector equivalence or completion of issue
#87. The remaining 12 selectors without behavior-level cases include command,
native/backend and composite paths that still need dedicated evidence.

### Paired CI and artifact-flow registration slice

Commit `32595473db4f65c59d769442b340c8f138acbdfd` moves `ci-workflows` and
`run-artifacts` into feature-owned typed declarations. The first remains a
read-only analyzer of configured GitHub Actions/Azure workflow YAML and static
commands; the second remains an opt-in Python AST analyzer of configured
artifact and provenance paths. Each owns its morphology, strict policy model,
summary and typed runner beside the implementation. Manual catalog rows,
`CheckPolicies` fields and review-runner bindings were removed. YAML is analyzed
as static input; no workflow command is executed by these checks.

Installed-wheel scenarios assert both direct selectors, existing findings and
locations, ordered serial/parallel profile reporting, and strict unknown-field
rejection. The pinned comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 118 manifested scenarios
with zero differences. Both catalogs retain 62 selectors; behavior scenarios
exercise 52, leaving 10 without behavior-level evidence. Direct dispatch covers
26 selectors and strict missing-policy rejection covers 36. Reference and
candidate wheel SHA-256 values are
`1ce2335cae5754b12de38e1fb84524bafa90953b73225c782481068dc3d36515` and
`1ddfa386327938c577a10fa2c5216b5a6314afc56b4aa42f0be755e84dfe7d53`. The
report is `/tmp/alphus-morphology-ci-artifacts-3259547.json`, not committed.

Installed-wheel self-quality passed 2,510 tests (44 skipped); its self-profile
passed all 27 checks with zero failures and four provisional passes. Ten
selectors still use legacy registration. Ten selectors lack behavior-level
cases, including message-result, shared-utility and source-test shapes. The
harness also lacks a dedicated effectful command-step scenario. This is
incremental evidence, not full #87 equivalence.

# Rule morphology

The broader built-in ownership and registration design is documented in the
[built-in check architecture and migration plan](BUILTIN-CHECK-ARCHITECTURE.md).
This page remains the morphology vocabulary and pilot boundary.

Morphology describes a built-in rule's claim, detection mechanism, inspected
scope, evidence, and rule-level evaluation maturity. Claim kind (condition,
risk, or style preference) is independent of detection mechanism. Morphology
describes the rule itself; it does not describe a particular finding or run.

The six-check pilot's `mechanisms` vocabulary is transitional. `exact-rule`
describes claim/evidence strength, while `bounded-heuristic`, `native-tool`,
and `local-model-assisted` describe different detection or backend properties.
The [built-in check architecture](BUILTIN-CHECK-ARCHITECTURE.md) separates
claim strength, analyzer method, backend, repeatability, and advisory or
enforcement disposition before broad registration migration. Do not infer
repeatability from a pilot mechanism label.

Keep these fields separate from severity, remediation priority, provisional or
mainline rollout, per-finding confidence, applicability, selection, and actual
execution coverage. The same rule can be selected but inapplicable, partially
analyzed, or unable to start. None of those run outcomes can be inferred from
its morphology metadata.

Human-facing names such as `types.opaque-return` may be useful category-plus-
smell aliases, but 0.0.3 preserves the existing `alphus/<scope>/<framework>/
<category>/<complaint>` finding IDs and output fields. Whether aliases are
presentation-only or selectable identifiers, and how they resolve collisions,
remains a 0.0.4 design decision; see the architecture plan.

## Feature-owned declarations

A morphology-only module may contain a top-level `ALPHUS_MORPHOLOGY` literal;
a runtime-migrated feature uses `ALPHUS_CHECK` to declare morphology and
registration together. `generate_morphology_manifest.py` parses only literal
data with Python's AST parser. It does not import the module or execute check
code. It validates
selector syntax and uniqueness, resolves local complaint slugs against static
`rule_tag` calls in the owning module, and resolves shared `finding_contracts`
references against statically parsed `ComplaintContract` and `ComplaintEntry`
records in `ALPHUS_COMPLAINT_CONTRACTS`.
Shared finding IDs are accepted across selectors only when a named contract
owns them and lists each permitted emitter; uncontracted duplicate IDs remain
errors. Discovery rejects symlinked feature modules and a symlinked gates root.
Runtime metadata validates tuple inputs, typed rule tags, and lowercase
scope/evidence slugs.

The numeric family is the shared-emitter example: `numeric-literals` and
`scipy-constants` reference one contract in `gates/review/numeric_catalog.py`.
The same literal drives runtime tag resolution and generated morphology, so
framework-specific wire IDs remain exact while the shared concern is recorded
once. Both selectors now also derive their strict policy fields, selector
contracts, `RuleSpec`, inventory and lazy runners from their feature-owned
`ALPHUS_CHECK` declarations. The paired numeric declarations also own their CLI display
names and configured source-scan mode, removing two selector lists from the
CLI while preserving legacy fallbacks for unmigrated checks. Their existing
checkers and public behavior are unchanged. `FeatureDefinition` stores each
policy's `StrictModel` subclass directly, and each selected provider is owned
by a typed `BuiltinFeature` with direct runner and specialized-operation
references.

The original six-rule pilot is not a complete built-in registration
migration. Twenty-five selectors now use feature-owned runtime
declarations, while 37 remain on legacy selector/config/runner paths.
Generated declarations do not select or enable a check and do not change JSON results, finding IDs, gate IDs,
or enforcement.

## Pilot examples

- `file-size`: exact rule; selected files, physical line and byte counts, and
  initializer syntax; synthetic tests only.
- `source-test-coverage`: exact rule; declared source/test relationships and
  revision-matched execution evidence; synthetic tests only.
- `positional-semantic-overrides`: bounded heuristic; configured Python
  branches and semantic-field assignments; public samples reviewed.
- `benchmark-docs`: bounded heuristic for prose risk; lexical matches in
  selected Markdown sections; synthetic tests only.
- `document-style`: bounded heuristic for a style preference; heading patterns
  and format-specific locations; synthetic tests only.
- `cyclomatic-complexity`: native tool and exact threshold; selected Python,
  JavaScript, and C++ functions with tool identity; synthetic tests only.

The semantic-patchwork review remains advisory. Its public calibration did not
establish a production positive for semantic corruption, so
`public-sample-reviewed` does not mean measured precision or enforcement
readiness.

## Registration boundary and remaining work

The six-check morphology pilot is metadata discovery. Draft PR #100 now
has twenty-four feature-owned runtime selectors, including the package-boundaries
composite, polyglot cyclomatic and comment readers, paired shared-contract
numeric checks, document reviewers, and Python test-quality and input-contract
review. The Pydantic and SQLAlchemy Python framework reviewers now use the same
feature-owned registration/result shape while retaining separate policies and
analyzers. Each declaration generates morphology, `FeatureDefinition`, `RuleSpec`,
strict primary `CheckPolicies` field, selector literal, inventory entry and
lazy dispatch. Existing config names, output adaptation, reports, selection
and exit behavior remain the compatibility contract. Synthetic discovery
proves a new selector can be found without a central selector list; tests
cover strict fields, shared complaint ownership, composite dispatch and lazy
unselected providers.

This paired source-review slice moved `pydantic-practices` and
`sqlalchemy-practices` from the theme runner/catalog into declarations beside
their Python analyzers. Both return the existing finding result shape, while
the Pydantic validation heuristics and SQLAlchemy session/query analysis remain
feature-specific. Their complaint contracts preserve all existing RuleTag IDs;
strict policy fields, catalog summaries, lazy runner entry points and display
labels are generated from those declarations. The pinned wheel manifest now
includes direct, profile and unknown-policy cases for each selector.

This remains bounded: the other 38 baseline selectors use legacy registration
paths, and the current evidence is not full wheel equivalence. Candidate
`0c31a41b61a006ccff08d611fcec23100c403443` matched the pinned baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` across 68 manifested scenarios
with zero differences. Both catalogs contain the same 62 selectors; behavior
scenarios exercise 24 selectors, leaving 38 without behavior-level evidence.
Direct invocation covers 26 selectors and strict missing-policy rejection
covers 36. Report: `/tmp/alphus-morphology-framework-practices-0c31a41.json`.
Continue migration with direct/profile comparisons, lazy-provider checks, and
explicit missing/unsupported, partial, error, plugin/native and effectful-command
cases; this does not complete #87.

## Orthogonal policy and run evidence

Claim kind, concern, mechanism, inspected scope, evidence kind, and rule-level
evaluation maturity describe the rule. They do not describe severity,
remediation priority, per-finding confidence, effective policy inputs,
applicability, selection, or actual run coverage. Effective policy and backend
choices belong in validated config and execution provenance.

Future gate recommendations should state why a check applies and whether it is
available, configured, and selected. A recommendation must not imply that the
check ran or enable it. Future statistics should report explicit counts for
selected, applicable, analyzed, excluded/skipped, partial, failed, and findings;
zero findings only describes successfully analyzed scope.

History/index migration, repository doctor/init, and optional local-model
evaluation remain separate #87 phases.


The FastAPI review now has a feature-owned typed registration beside its source
checker. One configured policy drives both the bounded Python AST findings and
the optional application/OpenAPI contract review; the optional framework is
loaded only when the application setting is present. Its existing selector,
strict TOML field, catalog applicability/summary, finding IDs and result shape
remain unchanged. Its differential evidence is recorded in the [FastAPI
registration slice](BUILTIN-CHECK-ARCHITECTURE.md#fastapi-review-registration-slice).

The six Python quaternion checks have also moved to feature-owned typed
registrations. Their shared concern and bounded-heuristic mechanism are
described in morphology metadata, while each checker keeps its own configured
policy and syntax evidence. The migration preserves the existing catalog
applicability labels, selectors, strict TOML fields, finding IDs and result
shape. See the [quaternion registration
slice](BUILTIN-CHECK-ARCHITECTURE.md#quaternion-registration-slice) for the
exact files and pinned-wheel evidence.

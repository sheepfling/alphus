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
references against a statically parsed `ALPHUS_COMPLAINT_CONTRACTS` literal.
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
checkers and public behavior are unchanged.

The original six-rule pilot is not a complete built-in registration
migration. Eleven selectors now use feature-owned runtime declarations, while
51 remain on legacy selector/config/runner paths. Generated declarations do not
select or enable a check and do not change JSON results, finding IDs, gate IDs,
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
- `document-style`: exact rule for a style preference; heading patterns and
  format-specific locations; synthetic tests only.
- `cyclomatic-complexity`: native tool and exact threshold; selected Python,
  JavaScript, and C++ functions with tool identity; synthetic tests only.

The semantic-patchwork review remains advisory. Its public calibration did not
establish a production positive for semantic corruption, so
`public-sample-reviewed` does not mean measured precision or enforcement
readiness.

## Registration boundary and next tranche

The six-check morphology pilot is metadata discovery. Draft PR #100 now
has eleven feature-owned runtime selectors, including the package-boundaries
composite, polyglot cyclomatic and comment readers, output escaping, and the
paired shared-contract numeric checks. Each declaration generates morphology,
`FeatureDefinition`, `RuleSpec`, strict primary `CheckPolicies` field, selector
literal, inventory entry and lazy dispatch. Existing config names, output
adaptation, reports, selection and exit behavior remain the compatibility
contract. Synthetic discovery proves a new selector can be found without a
central selector list; tests cover strict fields, shared complaint ownership,
composite dispatch and lazy unselected providers.

This remains bounded: the other 51 baseline selectors use legacy registration
paths, and the current fourteen-selector differential evidence is not full wheel
equivalence. The [latest pinned report](
architecture/builtin-check-wheel-differential-c880093-409c06d-numeric-registration.json)
compares 40 scenarios with no differences and covers direct/profile numeric
results plus strict config rejection. Forty-eight baseline selectors still lack
behavior-level differential evidence. Continue migration with direct/profile
comparisons, lazy-provider checks, and explicit missing/unsupported, partial,
error, plugin/native and effectful-command cases; this does not complete #87.

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

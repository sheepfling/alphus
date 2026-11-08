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
migration. Fifty-seven selectors now use feature-owned runtime declarations,
while five remain on legacy selector/config/runner paths.
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

The six-check morphology pilot was metadata discovery. Draft PR #100 now
has fifty-six feature-owned runtime selectors, including the package-boundaries
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

The repeated numeric-limit advisory is feature-owned as well. Its source
module declares the strict `RepeatedNumericLimitPolicy`, Python source-scan
input mode, finding result shape, bounded-heuristic morphology and lazy runner.
The old catalog row, hand-written review-runner entry, legacy policy override,
and CLI source-scan selector entry were removed. The policy schema, selector,
RuleTag, locations, messages, severity and plain/profile output remain
unchanged. Installed-wheel differential scenarios cover direct JSON and plain
output, strict unknown-field rejection, and serial/parallel profile results.
This is a representative deterministic advisory shape; it adds no detector and
does not complete the remaining legacy migration.

This paired source-review slice moved `pydantic-practices` and
`sqlalchemy-practices` from the theme runner/catalog into declarations beside
their Python analyzers. Both return the existing finding result shape, while
the Pydantic validation heuristics and SQLAlchemy session/query analysis remain
feature-specific. Their complaint contracts preserve all existing RuleTag IDs;
strict policy fields, catalog summaries, lazy runner entry points and display
labels are generated from those declarations. The pinned wheel manifest now
includes direct, profile and unknown-policy cases for each selector.

At candidate `0c31a41`, 24 selectors had been migrated; that report is a
historical snapshot, not the current migration count. Candidate `33cf712`
migrated 40 of 62 baseline selectors. Candidate `6bc8a0c` migrates 42; 20
still use legacy registration paths, and the evidence is not full wheel
equivalence. The latest shared-policy prose slice matched 98 installed-wheel
scenarios with zero differences; it is described in the [architecture
document's shared-policy section](BUILTIN-CHECK-ARCHITECTURE.md#shared-policy-prose-registration-slice).
Candidate
`0c31a41b61a006ccff08d611fcec23100c403443` matched the pinned baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` across 68 manifested scenarios
with zero differences. Both catalogs contain the same 62 selectors; behavior
scenarios exercise 24 selectors, leaving 38 without behavior-level evidence.
Direct invocation covers 26 selectors and strict missing-policy rejection
covers 36. Report: `/tmp/alphus-morphology-framework-practices-0c31a41.json`.
Continue migration with direct/profile comparisons, lazy-provider checks, and
explicit missing/unsupported, partial, error, plugin/native and effectful-command
cases; this does not complete #87. The latest shared-policy prose slice and its
98-scenario installed-wheel result are recorded in the [architecture document's
shared-policy section](BUILTIN-CHECK-ARCHITECTURE.md#shared-policy-prose-registration-slice).

## Paired semantic-review registration slice

Commit `7388a58bef5bd522c9d94c5d142528ff0ce874c6` moves
`heuristic-total-consumption` and `unexplained-empty-results` to declarations
beside their existing Python analyzers. They remain separate bounded
heuristics with distinct policy models, selectors, RuleTag IDs, messages, and
findings. The feature-owned declarations provide typed registration and
morphology; the old review runner entries, catalog rows, and handwritten
`CheckPolicies` fields are removed. No detector semantics or default selection
changed.

The installed-wheel scenarios invoke each selector directly, exercise both in
profile order, and reject an unknown policy field before dispatch. The wheel
differential against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 102 manifested
scenarios with zero differences. Both catalogs contain the same 62 selectors;
behavior scenarios cover 44, leaving 18 without behavior-level cases. The
separate selector policy matrix has 26 configured direct invocations and 36
strict missing-policy rejections; those counts describe that matrix rather
than the direct CLI scenarios. Reference and candidate wheel SHA-256 values
are `156bea18e6d12647c9d765d60fd4938e6e8ea6bf86ab46e9ed0032dd8886afb5` and
`e610e62003bbefda5c172b512a522a1021c91096052ba5cca394649eb730a64e`. The
report is `/tmp/alphus-morphology-semantic-reviews-7388a58.json` and is not
committed.

Installed-wheel self-quality passed: 2,510 tests passed, 44 skipped; the
self-profile passed all 27 checks with no failures and four provisional
passes. This is incremental evidence, not full 62-selector equivalence or
completion of issue #87.

## Paired architecture-review registration slice

Commit `a161464f8e06a02a95c768f41dd01f3cf86f9f02` moves
`provenance-as-ownership` and `semantic-work-in-presentation` into typed
feature-owned registrations. They share the existing finding/result shape and
architecture category, while retaining distinct concerns, strict policy
models, configurations, RuleTag IDs, and claims. The first is a configured
path-ownership heuristic; the second checks co-location of four
consumer-declared operation roles. The former review runner entries, catalog
rows and handwritten `CheckPolicies` fields were removed. The detectors and
their findings were not changed.

The installed-wheel scenarios invoke each selector directly, run both in an
ordered profile, and reject an unknown field before dispatch. Against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, all 106 manifested scenarios
matched with zero differences and the 62-selector catalogs were equal.
Behavior scenarios cover 46 selectors, leaving 16 without behavior-level
scenarios. The separate selector-policy matrix has 26 configured direct
invocations and 36 strict missing-policy rejections. Reference and candidate
wheel SHA-256 values are
`2f983f1b760e56f7ddfe5e6677daf9da7b36693ff84003ce8cc08720bb3ed043` and
`3f5d48dd4b025422048c50d9a0b78fe09b43decc0042ed7d24802347e70e0367`. The
report is `/tmp/alphus-morphology-architecture-reviews-a161464.json` and is
not committed.

Installed-wheel self-quality passed: 2,510 tests passed, 44 skipped; the
self-profile passed 27 checks with no failures and four provisional passes.
This is incremental evidence, not full selector equivalence or completion of
issue #87.

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

The three configured coordinate-frame checks now use the same registration
shape: ECEF-to-ENU tuple formulas, ECEF-to-NED matrix formulas, and NED basis
vectors each own their policy model, morphology and typed runner beside the
checker. Their concerns and policy contracts remain distinct. Direct JSON
scenarios assert the stable finding IDs and source lines, a profile scenario
asserts ordered results, and an invalid-config scenario proves strict
validation. The [coordinate-frame registration slice](BUILTIN-CHECK-ARCHITECTURE.md#coordinate-frame-registration-slice)
records the compatibility result.

The four configured Python linear-algebra reviewers now use feature-owned
typed registration for their separate bounded AST shapes. Their current
selector count, pinned-wheel comparison, positive fixture treatment, and
remaining equivalence gap are documented in the [linear-algebra registration
slice](BUILTIN-CHECK-ARCHITECTURE.md#linear-algebra-registration-slice).

## Paired positional-review registration slice

Commit `c7023fa14a12d71784a7fcb2c0d666334fcfcf0d` moves
`positional-interfaces` and `positional-semantic-overrides` to typed
feature-owned registrations beside their Python AST analyzers. The checks keep
separate concerns, policies, and RuleTag identities: one flags adjacent
same-type primitive parameters; the other reviews configured position-based
assignments to semantic fields. Their messages, severity, scope, selector
names, config fields, and analyzer behavior remain unchanged. The legacy
catalog rows, manual policy fields, and review-runner bindings were removed.

The installed-wheel fixtures exercise direct selection for both checks, the
ordered profile in serial and parallel execution, existing finding IDs and
locations, and strict rejection of an unknown policy field. The pinned wheel
comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 110 manifested
scenarios with zero differences. Both catalogs retain the same 62 selectors;
behavior scenarios cover 48, leaving 14 without behavior-level coverage. The
separate selector-policy matrix covers 26 minimal direct invocations and 36
strict missing-policy rejections. Reference and candidate wheel SHA-256 values
are `d2878e2781296fd9539374b3121470060536682d9840b28f92ebce4b75397108` and
`c44cf1cb6ccfbd548e7c9ef70e0ec68a348cde42e6d432dc8472742b6b9eb198`. The
report is `/tmp/alphus-morphology-positional-c7023fa.json`; it is not
committed.

Installed-wheel self-quality passed: 2,510 tests, 44 skipped; its self-profile
passed all 27 checks with zero failures and four provisional passes. This is
incremental evidence only; 14 selectors still lack behavior-level differential
scenarios, and issue #87 is not complete.

## Paired review-pipeline registration slice

Commit `3c2019ebfbd93f00dea52eaec103f665d22c6893` moves
`parallel-normalization` and `patch-cascade` into typed feature-owned
declarations beside their existing Python analyzers. Both remain bounded
heuristics with separate strict policy models, RuleTag identities and claims.
The manual catalog rows, `CheckPolicies` fields, and review-runner bindings are
removed; configuration names, finding shapes and default selection remain
unchanged.

Installed-wheel scenarios cover each direct selector, their ordered serial and
parallel profile, and rejection of an unknown policy field. Comparison with
baseline `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 114 manifested
scenarios with zero differences. Both catalogs retain the same 62 selectors;
behavior scenarios now exercise 50, leaving 12 without behavior-level
coverage. The separate selector-policy matrix covers 26 configured direct
invocations and 36 strict missing-policy rejections. Reference and candidate
wheel SHA-256 values are
`621bbb585fe7a70ad01716fc26f07ec1ec7fdf86acd67d855877b37d03477312` and
`b5185fb6c9f4f4128c51381a1895607af3cfe2f78119832b9bf2a9f0da8188cd`.
The report is `/tmp/alphus-morphology-review-pipelines-3c2019e.json` and is not
committed.

Installed-wheel self-quality passed: 2,510 tests, 44 skipped; its self-profile
passed all 27 checks with zero failures and four provisional passes. This is
incremental evidence, not full 62-selector equivalence or completion of issue
#87.

## Paired CI and artifact-flow registration slice

Commit `32595473db4f65c59d769442b340c8f138acbdfd` moves `ci-workflows` and
`run-artifacts` into typed feature-owned registrations beside their existing
analyzers. The former reviews configured GitHub Actions/Azure YAML without
executing it; the latter checks caller-configured Python artifact/provenance
flows. They retain separate policies and finding IDs. Their central catalog,
policy-field and review-runner entries were removed without changing config,
selection or reporting contracts.

The installed-wheel scenarios cover each direct check, an ordered serial and
parallel profile, and unknown-field rejection. The pinned comparison against
baseline `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 118 manifested
scenarios with zero differences. Both catalogs retain 62 selectors; behavior
scenarios cover 52, leaving 10 without behavior-level cases. The separate
selector-policy matrix covers 26 configured direct invocations and 36 strict
missing-policy rejections. Reference and candidate wheel SHA-256 values are
`1ce2335cae5754b12de38e1fb84524bafa90953b73225c782481068dc3d36515` and
`1ddfa386327938c577a10fa2c5216b5a6314afc56b4aa42f0be755e84dfe7d53`.
The report is `/tmp/alphus-morphology-ci-artifacts-3259547.json` and is not
committed.

Installed-wheel self-quality passed 2,510 tests (44 skipped); all 27 self-
profile checks passed, with four provisional passes. This is incremental
evidence, not full selector equivalence or completion of issue #87.

## Paired message-result registration slice

Commits `e2d640e` and `ba13b18` migrate `runtime-types` and `script-policy`
into typed feature-owned registrations beside their existing analyzers. Both
use the existing `messages` runner/result shape. Their declared complaint IDs
drive the profile result adapter; direct invocation retains the legacy message
array and exit behavior. The generated strict policy fields and selector
contracts remain unchanged, and the manual catalog rows, `CheckPolicies`
fields, and source-runner bindings were removed. A lazy-load regression proves
that selecting `file-size` does not import either Python message provider.

Differential scenarios exercise direct JSON and plain output, serial/parallel
profile selection for both checks, unknown-field rejection for both policy
sections, and profile finding IDs.
The pinned installed-wheel comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 125 scenarios with zero
differences. Both catalogs retain the same 62 selectors; behavior scenarios
cover 54, leaving eight without behavior-level cases. The separate
selector-policy matrix covers 26 direct invocations and 36 strict
missing-policy rejections. Reference and candidate wheel SHA-256 values are
`45243dfdd61854bcbc59dfecb2e304f9aaf289beecc294ebd5b3c334031a4a62` and
`09a31509a125872d54e79ba78cc06171a0c8eff933a00c7e4a866c2590f2d639`. The
report is `/tmp/alphus-morphology-message-rules-7b2f045.json`; it is not
committed.

This comparison also caught and prevented a new `typing` domain tag from
changing the public catalog: the runtime-types declaration keeps the existing
empty catalog domain list. This slice preserves the 0.0.3 output and selection
contracts; it does not complete issue #87 or cover all remaining selectors.
Installed-wheel self-quality at implementation commit `b3c2967` passed 2,514
tests (44 skipped), with all 27 self-profile checks passing and four provisional
passes. Ruff, formatting, Pyright, package import checks, and the Markdown-shell
review passed as part of that run.

## Repeated numeric-limit registration slice

Commits `3c23a1624ea2588ceee01551216339ddf3ac8939`,
`83aa9cf93ab0340d1b61e4fca0018c5a74705473`, and
`79a425377b3e1d2f6a49a2256299450a076f448a` move
`repeated-numeric-limits` into a typed feature-owned registration beside its
existing analyzer. Its declaration owns the existing strict
`RepeatedNumericLimitPolicy`, configured-source-scan mode, findings result
shape, morphology and lazy runner. The old catalog row, hand-written review
runner, legacy policy override and CLI source-scan selector entry were removed.
The selector, TOML field, finding ID, locations, messages, severity, plain
output and profile behavior remain unchanged.

Differential cases cover direct JSON and plain output, strict rejection of an
unknown policy field, and serial/parallel profile results. The pinned
installed-wheel comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 129 manifested scenarios
with zero differences. The catalog remains 62 selectors; 55 have feature-owned
runtime declarations, and behavior scenarios exercise 55, leaving seven
without behavior-level evidence. The separate selector-policy matrix covers
26 configured direct invocations and 36 strict missing-policy rejections.
Reference and candidate wheel SHA-256 values are
`7e85428e80e2623617cb0fc37a29547f02213522da91a56f94974b4e96bf7472` and
`0bb1ab4c1487b9a619ad853e1ffcab298c5fc755529c1a6a8084e085aa14fd2f`. The
report is `/tmp/alphus-morphology-repeated-numeric-79a4253.json` and is not
committed. The corrected fixture also passes the repository self-profile's
Python lint step. This remains partial compatibility evidence, not completion
of issue #87.

## Suppression-reason registration slice

Commit `762d06eef3dcc4b665a17babf9b6531a93fb4dd6` moves
`suppression-reasons` into a feature-owned typed declaration beside its
existing analyzer. The declaration owns the strict policy model, finding
result shape, applicability, exact-rule morphology and lazy runner. The
duplicate catalog row, `CheckPolicies` field and review-runner binding were
removed. The TOML policy, selector, finding ID, paths, messages, direct result,
profile status and exit behavior remain unchanged. A registration probe
confirms catalog discovery does not import this analyzer until selected.

Differential cases cover direct JSON/plain output, strict unknown-field
rejection and serial/parallel profile results. The pinned installed-wheel
comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 133 manifested scenarios
with zero differences. The catalog remains 62 selectors; 56 have
feature-owned runtime declarations and behavior scenarios exercise 56, leaving
six legacy selectors without behavior-level coverage. The selector-policy
matrix still covers 26 configured direct invocations and 36 strict
missing-policy rejections. Reference and candidate wheel SHA-256 values are
`f5d5b611a8e9217220ce3e9dbdeaaba0c8cf62740a54b123a666454769fe27e3` and
`83cc194d9008b9d537f8f8d9eb76d2998f7f99b9409ec800e6b97e9d9291d53d`. The
report is `/tmp/alphus-morphology-suppression-762d06e.json`; it is not
committed. This remains partial evidence, not completion of issue #87.

## Source-test-coverage registration slice

Commit `fcbb5d474e51d10896e91df7d09e4b167fdf1cb3` moves
`source-test-coverage` to the same typed, feature-owned registration model.
Its declaration owns the existing strict `SourceTestCoveragePolicy`,
repository applicability, no-file-inventory requirement, finding result shape,
morphology and lazy runner. The duplicate catalog row, policy-field override
and hand-written review-runner binding were removed. The selector, TOML field,
catalog summary and domains, finding ID and empty/partial/stale evidence
behavior remain unchanged.

Differential cases exercise explicit direct selection with no top-level
`[files]` inventory, typed finding output, serial/parallel profile execution,
and rejection of an unknown policy field. Against pinned baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, the installed-wheel comparison
matched all 136 manifested scenarios with zero differences and confirmed
catalog equality across all 62 selectors. Fifty-seven selectors are now both
feature-owned and behaviorally exercised; five legacy selectors remain. The
selector-policy matrix covers 26 configured direct invocations and 36 strict
missing-policy rejections. Reference and candidate wheel SHA-256 values are
`c0c6b4fa5e4ac8082aeeba1e860c3bac3364c2f54813fc509117ebee20b9e94d` and
`068072c916986dcbefcb433e0c8735707dfa633052aef1d267c878f5a3935e3a`. The
report is `/tmp/alphus-morphology-source-test-coverage-fcbb5d4.json`; it is not
committed. The wheel CI passed 2,515 tests (44 skipped), with 27 self-profile
checks passing and four provisional passes; Ruff, formatting, Pyright, import
smoke, and Markdown-shell review also passed. This remains partial evidence,
not completion of issue #87.

## Source-family and typing-stub registration slice

Commit `1d9ddc5` moves `source-families` and
`typing-stub-suggestions` into typed feature-owned registrations beside their
existing analyzers. This removes the last manual review-runner table. The
source-family check keeps its cross-language filename-family heuristic and
existing warning result; typing-stub suggestions remain an advisory
package-metadata check with no analyzer backend. Both preserve their strict
policy fields, selectors, finding IDs, messages, applicability and output
adapters. Lazy-dispatch tests verify unselected providers are not imported.

The pinned installed-wheel comparison against baseline
`c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e` matched all 140 manifested
scenarios with zero differences. Both catalogs contain the same 62 selectors;
59 are feature-owned and behaviorally exercised, leaving three legacy
selectors. The selector-policy matrix covers 26 direct invocations and 36
strict missing-policy rejections. Reference and candidate wheel SHA-256 values
are `580bc6ae6b42620b7cea5c0df769b4a2290ac8c1f84e2219e6b327ded200f9a4` and
`0514bb5725f16d28c31337fa3431d66792e53e9e1aebfd469580f112d58dd953`. The
report is `/tmp/alphus-morphology-review-pair-34fd501.json`; it is not
committed. This remains partial compatibility evidence, not completion of
issue #87.

## Shared-utilities specialized-report registration slice

Commit `09186377482b917fb7cfaac70f5fb757b0c86186` moves
`shared-utilities` to a typed feature-owned registration. Its declaration owns
the configured-source scan mode, strict policy model, four stable complaint
IDs, specialized report shape, morphology and runner. The manual hygiene runner,
legacy catalog and policy-field registrations, and CLI source-scan selector
entry were removed. `SharedUtilitiesReport` now lives in `alphus.contracts`;
the original gate module re-exports it, preserving existing imports. The
profile result adapter obtains complaint IDs from the feature's morphology,
and the registry validates that its selected runner returns the typed report.

Differential scenarios cover the direct JSON report envelope, a finding-bearing
serial/parallel profile run, and unknown-field rejection. Against pinned
baseline `c880093f7ccb73c2af78ffb5c7de8c15d2b75b0e`, all 143 manifested
installed-wheel scenarios matched with zero differences and the catalogs
remained equal at 62 selectors. Sixty selectors are feature-owned and
behaviorally exercised; `cli` and `python-style` remain on legacy registration.
The selector-policy matrix covers 26 direct invocations and 36 strict
missing-policy rejections. Reference and candidate wheel SHA-256 values are
`f12710581a6bb35f628169fba66666af1ac70056b617bab617d4a323fbd1ee8b` and
`f98299bd73e9294ce6c3362931abccef579e32b2a70a04922451a5ca1bc36944`. The
report is `/tmp/alphus-morphology-shared-utilities-435afb8.json`; it is not
committed. Installed-wheel self-quality at documentation head
`122f92b0b833df39201f12440eef7593a96daea2` passed 2,519 tests (44 skipped),
all 27 self-profile checks with four provisional passes, Ruff, formatting,
Pyright, import smoke (212 modules), compatibility imports, and Markdown-shell
review. This remains partial evidence, not completion of issue #87.

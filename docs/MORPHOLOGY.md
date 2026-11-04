# Rule morphology

Morphology describes a built-in rule's claim, detection mechanism, inspected
scope, evidence, and rule-level evaluation maturity. Claim kind (condition,
risk, or style preference) is independent of detection mechanism. Morphology
describes the rule itself; it does not describe a particular finding or run.

Keep these fields separate from severity, remediation priority, provisional or
mainline rollout, per-finding confidence, applicability, selection, and actual
execution coverage. The same rule can be selected but inapplicable, partially
analyzed, or unable to start. None of those run outcomes can be inferred from
its morphology metadata.

## Feature-owned declarations

A feature module may contain a top-level `ALPHUS_MORPHOLOGY` literal. The
`generate_morphology_manifest.py` script parses only literal data with Python's
AST parser. It does not import the module or execute check code. It validates
selector syntax and uniqueness, matches declared complaint slugs to static
`rule_tag` calls in the owning module, requires exactly one matching tag per
complaint, rejects duplicate declarations, and generates the typed
`policy/_generated_morphology.py` view. Discovery rejects symlinked feature
modules and a symlinked gates root. Runtime metadata validates tuple inputs,
typed rule tags, and lowercase scope/evidence slugs.

This is a six-rule pilot, not a complete built-in registration migration. The
selector type, policy fields, runner adapters, output normalization, and CLI
catalog remain on their existing paths in this tranche. The generated
morphology view does not select or enable any check and does not change existing
JSON results, finding IDs, gate IDs, or enforcement.

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

This pilot proves safe discovery of a feature-owned declaration, including a
synthetic selector absent from any central selector list. It does not register
that synthetic check for execution. In the application, declarations still
attach only to selectors already present in the built-in catalog; typed config
fields, runner bindings, output normalization, and public docs remain
hand-maintained. The pilot therefore does not meet #87's end-to-end registration
acceptance.

The next bounded #87 tranche should derive the selector type, strict
`CheckPolicies` field contract, `RuleSpec`, runner binding, output validation,
and docs index from one trusted built-in declaration. A new test check should
exercise strict config validation, explicit selection, typed dispatch, result
validation/reporting, and installed-wheel execution. It should also prove that
registration does not select the check and that an unselected check does not
initialize its runner or optional backend. Keep third-party plugin discovery
behind its separate trust boundary.

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

# Rule morphology

Morphology describes a built-in rule's claim, detection mechanism, inspected
scope, evidence, and rule-level evaluation maturity. It describes the rule
itself; it does not describe a particular finding or a particular run.

Keep these fields separate from severity, remediation priority, provisional or
mainline rollout, per-finding confidence, applicability, selection, and actual
execution coverage. The same rule can be selected but inapplicable, partially
analyzed, or unable to start. None of those run outcomes can be inferred from
its morphology metadata.

## Feature-owned declarations

A feature module may contain a top-level `ALPHUS_MORPHOLOGY` literal. The
`generate_morphology_manifest.py` script parses only literal data with Python's
AST parser. It does not import the module or execute check code. It validates
selectors against the existing catalog, checks finding IDs against statically
visible `rule_tag` calls in the owning module, rejects duplicate declarations,
and generates the typed `policy/_generated_morphology.py` view.

This is a six-rule pilot, not a complete built-in registration migration. The
selector type, policy fields, runner adapters, output normalization, and CLI
catalog remain on their existing paths in this tranche. The generated
morphology view does not select or enable any check and does not change existing
JSON results, finding IDs, gate IDs, or enforcement.

## Pilot examples

| Selector | Mechanism | Scope and evidence | Evaluation maturity |
| --- | --- | --- | --- |
| `file-size` | Exact rule | Selected files; physical line and byte counts plus initializer syntax | Synthetic tests only |
| `source-test-coverage` | Exact rule | Declared source/test relationships and revision-matched execution evidence | Synthetic tests only |
| `positional-semantic-overrides` | Bounded heuristic | Configured Python branches and semantic-field assignments | Public samples reviewed |
| `benchmark-docs` | Prose risk | Bounded lexical matches in selected Markdown sections | Synthetic tests only |
| `document-style` | Style preference | Heading patterns and format-specific locations | Synthetic tests only |
| `cyclomatic-complexity` | Native tool and exact threshold | Selected Python, JavaScript, and C++ functions with tool identity | Synthetic tests only |

The semantic-patchwork review remains advisory. Its public calibration did not
establish a production positive for semantic corruption, so `public-sample-reviewed`
does not mean measured precision or enforcement readiness.

The next registration tranche should make declarations the source of truth for
all derived built-in views, while keeping plugin discovery behind a separate
trust boundary. History migration, repository doctor/init, and optional
local-model evaluation remain separate phases.

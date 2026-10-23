# Future extensions, categories, and diagnostics

This is a design proposal for Alphus. The current rules, selectors, and
consumer policies remain the supported interface; the proposal does not add a
plugin loader or change which checks run.

## Current contracts

Each portable checker receives an explicit repository root, validated policy,
and selected files. Direct rule results keep the frozen `Finding` record with
stable rule ID, repository-relative path, optional line, message, and severity.
Profile aggregation now adapts Alphus-owned rule results into a named
`Diagnostic` carrying source, rule ID, path, line, message, and severity; this
does not rewrite the direct-rule JSON contract. Source-level helpers may return
a named line and message before the checker adds its rule ID and path. Native
command steps keep their own output and exit codes; Alphus retains their raw
output and reports execution status without converting command text into
Alphus findings.

TOML selects current rules and ordered profiles. It contains consumer paths,
thresholds, and command arguments, not executable Python callbacks. The
profile `failure_threshold` currently defaults to `error`, and a rule step may
override the severity of its findings. These are narrow threshold controls;
they do not add category-wide selectors or an independent enforcement-state
model. Alphus does not currently discover third-party rule packages or expose
pytest-style hooks.

## Proposed category model

The six proposed categories are groupings for navigation and selection:

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

The fuller execution model should report `passed`, `failed`, `not applicable`,
and `not run` separately. A disabled, unselected, or inapplicable check must
not be presented as a successful check. Category and rule overrides should
resolve to a printed plan before execution, with existing behavior preserved
unless a consumer explicitly changes its configuration.

## Future extension hooks

### Package layout for additional languages

Group built-in checks by their actual dependency and policy boundaries. A
Python-specific checker can live in an ordinary `alphus` subpackage, while
repository-wide and data-format checks remain separate from any one language.
Keep the core inventory, orchestration, diagnostics, and rule IDs stable during
such moves. The current `alphus_stub_quality` package already isolates the
specialized stub workflow within the same distribution.

Python namespace packages become useful if independently installed and
versioned distributions need to share one import namespace. They are not needed
to organize modules inside the current distribution. If third-party gate
packages become necessary, discover them through an explicit, versioned entry
point contract rather than by scanning a namespace for imports. C++ and
JavaScript tools can continue as native command steps until Alphus owns a
language-specific check that warrants Python code.

### Hook contract

First establish an internal rule specification with a stable name, category,
validated policy model, and callable that returns the common findings. Keep
the current built-in registry and CLI selectors as adapters while that contract
is exercised across existing rules.

Only after consumers need third-party checks should Alphus expose a versioned
plugin API, potentially through an entry-point group and pytest-style hook
specifications. The API would need explicit loading policy, deterministic
ordering, duplicate-name rejection, typed configuration, and the same finding
contract as built-in checks. Loading a plugin executes Python code, so a policy
file should not silently import arbitrary modules. Native tools should remain
available as command steps without requiring a Python plugin.

## Migration sequence

1. Publish the category and diagnostic vocabulary, then map current selectors
   without changing defaults.
2. Add a resolved selection plan and explicit pass, fail, not-applicable, and
   not-run outcomes while preserving existing command behavior.
3. Migrate checkers to the shared rule specification one at a time, comparing
   normalized findings and JSON output with the existing contracts.
4. Design and version third-party hooks only when an actual consumer requires
   them; test ordering, collisions, configuration failures, and diagnostics
   before release.

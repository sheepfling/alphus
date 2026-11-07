# Typed check registry spike

The `scripts/` experiment compares registration shapes for the 0.0.3 morphology
work; it is fixture-only and does not drive production dispatch. Production
status and remaining registration limits are summarized in the
[built-in architecture plan](../BUILTIN-CHECK-ARCHITECTURE.md), the single
design entry point. This page preserves the experiment and its boundaries.

## Prototype and authoring path

The prototype lives in `scripts/typed_registry_spike.py` and
`scripts/registry_spike/`. The toy check follows this flow:

1. `toy_registration.py` owns one feature declaration. The independent
   `alpha_registration.py` owns a second declaration. Both use the shared
   typed constructor in `registration_support.py`; neither edits a central
   selector dictionary.
2. Each declaration returns `BuiltinCheckDefinition[Settings, Evidence,
   Output]`. Its typed provider factory lives in `provider_factory.py` and uses
   one direct, function-local import. The analyzer is imported only when the
   selected check executes, and Pyright checks its concrete provider return.
3. `CheckRegistry.discover()` sorts first-party entry points, loads metadata
   factories, rejects duplicate names before loading any factory, and combines
   built-in definitions with the existing explicitly enabled API v1 plugin
   bindings. Built-in discovery reads only the installed `alphus` distribution,
   not the process-wide entry-point group, so unrelated distributions cannot
   inject built-in metadata.
4. A selected entry resolves the already parsed policy through its declared
   settings callback, then runs through the shared `execute` interface. A
   mismatched settings model fails before analyzer loading. The toy returns
   `CyclomaticReport` unchanged, demonstrating that the registry does not
   turn specialized results into `PluginFinding` records. Typed authors
   retain the more specific `execute_typed` method before heterogeneous
   registry dispatch erases the result type to `object`.

The declaration reuses the existing `RuleMorphology` type. Complaint ownership
uses `ComplaintContract` and `ComplaintTag` records rather than unnamed
string-pair tuples. The production `ALPHUS_CHECK`,
`ALPHUS_COMPLAINT_CONTRACTS`, and some result metadata remain unchanged while
this design is reviewed.

## Rule-shape coverage and limits

The prototype tests the typed provider/result boundary only. It does not execute
these representative production shapes; the architecture plan records their
current owners and compatibility boundaries:

- **File-local checks:** `file-size` and `line-length` preserve strict per-check
  policy, selected paths, finding IDs, ordering, and the existing result adapter.
- **Bounded heuristics:** `scipy-constants`, `numeric-literals`, and
  `output-escaping` retain their evidence limits, stable IDs, and language-aware
  providers.
- **Cross-file composite:** `package-boundaries` keeps four effective policy
  inputs, engine provenance, explicit selection, and its current findings.
- **Native polyglot analysis:** `cyclomatic-complexity` retains its specialized
  `CyclomaticReport` and Python/Ruff, JavaScript/ESLint, and C++/Lizard results.
- **Effectful orchestration:** `CommandRunStep` keeps process/step results,
  commands, ordering, locks, budgets, and failure handling. It is not a
  finding check.

The toy's `CyclomaticReport` type is a convenient specialized result, but the
toy provider does not invoke a native tool. Therefore it is not evidence for
polyglot planning, subprocess behavior, or effectful command registration.
The production design should keep one typed registry index while preserving
role-specific runners and outputs for these shapes; a task that performs an
effect should not be coerced into `Finding` merely to fit a check abstraction.

## Executed evidence

`tests/architecture/test_typed_check_registry_spike.py` verifies metadata
bootstrap, deterministic order, duplicate rejection before factory loading,
rejection of factories that return selector-only objects or incompatible
execute signatures, isolation from unrelated distributions, analyzer laziness,
strict settings-model rejection, typed execution, a specialized result,
plugin API v1 namespace preservation, plugin result validation, and a
Git-branch merge proving that independent declaration files do not conflict
when they add no shared registry or packaging edits. A cold subprocess
also imports the
metadata and registry modules and asserts that neither gate modules nor the
toy analyzer are loaded. The discovery tests use real stdlib `EntryPoint`
objects with a test-only distribution source; no built-in check group is
currently declared in `pyproject.toml`, and no toy selector is added to an
installed entry-point table. The tested `distribution("alphus")` source is
injected by tests, so production Alphus discovery remains unverified in a
wheel. The separate fixture experiment now verifies two prototype strategies in
an installed wheel.
`tests/architecture/test_registry_wheel_experiment.py` goes beyond that toy
merge check with a temporary fixture distribution. One branch adds a typed
file-local exact check and the other a typed cross-file composite; each branch
authors only its two feature files, and Git merges them without touching the
shared registry, packaging table, or build backend. The test builds and installs
a wheel, then runs both definitions from the installed package. It compares
runtime package-module discovery with standard entry-point discovery using
metadata generated by a small setuptools build hook. Both paths select and
execute the same checks, reject unknown and wrong-type settings, and leave
unselected analyzers unloaded. Pyright checks both feature declarations in
strict mode. The test inspects installed `.dist-info` entry points and asserts
the exact factory targets. A normal PEP 517 isolated build enforces the fixture's
`setuptools>=80` requirement; the build hook records the exact resolved version
in ignored metadata for the report. The requirement is intentionally unpinned,
so the test demonstrates the build contract rather than bit-for-bit wheel
reproducibility, and isolated builds require package-index access. The generated
`entry_points.txt` lives under an ignored build directory, and the temporary
repository stays clean.

This is a reproducible architecture fixture, not an Alphus wheel migration.
Its scanner and build hook are prototype code, its strict settings are local to
the fixture, and it does not exercise Alphus CLI/profile behavior, production
config schemas, plugin API v1 in the installed fixture, native tools, or the
other rule shapes listed above. Existing plugin v1 compatibility remains
covered separately by `test_typed_check_registry_spike.py`.

`tests/execution/test_builtin_package_lazy_import.py`
checks a separate boundary: cold `import alphus` loads no gate modules, while
the existing root-level `check_json_structure` and `check_path_discovery`
exports remain available on explicit access. The production Python-style
detector is unchanged; its regression test keeps flagging a function-local
import even when the function is annotated as a `CheckProvider` factory. Only
the exact spike loader path is excluded from this repository's Python-style
profile; Ruff, Pyright, focused tests, and package tests still cover it.

Commands run in the current worktree for the revised spike:

```sh
.venv/bin/python -m pytest \
  tests/architecture/test_typed_check_registry_spike.py \
  tests/architecture/test_registry_wheel_experiment.py \
  tests/execution/test_builtin_package_lazy_import.py \
  tests/gates/source/test_python_style_engine.py \
  tests/test_self_profile.py -q
.venv/bin/python -m pyright scripts/typed_registry_spike.py scripts/registry_spike
# The wheel test also runs Pyright in strict mode on both generated feature modules.
.venv/bin/ruff check \
  scripts/typed_registry_spike.py scripts/registry_spike \
  src/alphus/__init__.py src/alphus/support/public_imports.py \
  src/alphus/gates/languages/python/style.py \
  tests/architecture/test_typed_check_registry_spike.py \
  tests/architecture/test_registry_wheel_experiment.py \
  tests/execution/test_builtin_package_lazy_import.py \
  tests/gates/source/test_python_style_engine.py \
  tests/test_self_profile.py
.venv/bin/alphus --root . --config quality-gates.toml --run --profile check
.venv/bin/alphus --root . --config quality-gates.toml --run --profile markdown-shell-review
```

Validation on the current worktree: 71 focused tests passed, including strict
Pyright on the two fixture declarations; targeted Ruff lint and formatting
passed; strict Pyright on the registry spike reported 0 errors, warnings, or
information; the full self-profile passed 27 checks with
0 failures and 4 provisional passes, including 2,488 package tests passed and
43 skipped; and the Markdown shell review passed. The profile emitted one
informational note that the installed `types-PyYAML` version is outside the
configured range.
The callbacks in both feature-owned registration modules have concrete generic
annotations and contain no casts. Discovery imports the metadata modules but
not `toy_analyzer.py`; execution resolves the analyzer through its typed
provider factory.
The provider protocol lives in `scripts/registry_spike/contracts.py`, not in
the registry module, so the analyzer does not depend on the registry. The
package-root lazy exports address the separate cold-bootstrap leak discovered
by the review. This remains a toy spike, not proof of package-wide laziness or installed
Alphus wheel registration.

The new installed-wheel result proves the two discovery paths only for the
fixture distribution. It does not prove that installed Alphus metadata,
production CLI dispatch, strict TOML integration, or the complete 62-selector
catalog works through this registry.

## Alternatives and trade-offs

- **Manually listed per-check entry points:** standard runtime discovery and
  lazy loading, but every feature edits a shared `pyproject.toml` entry-point
  table. The current registry prototype consumes this standard form.
- **Runtime package-convention discovery:** avoids per-check packaging entries,
  but needs one central scanner and imports every first-party declaration
  module. The installed fixture proved its behavior and lazy analyzer boundary,
  while confirming it is custom discovery machinery.
- **Build-generated entry-point metadata:** the fixture build hook scans
  feature-owned `*_registration.py` modules and writes standard entry-point
  metadata under an ignored build directory. Two feature branches merged
  without touching shared authored files, and the installed wheel executed
  both checks. This avoids per-check `pyproject.toml` edits at the cost of a
  project-owned build hook and fixed module convention.
- **Static AST parsing of typed constructors:** avoids importing declaration
  modules, but creates a custom source language and parser. Replacing tuples
  with dataclasses does not remove that cost.
- **Central Python mapping:** simple runtime behavior and direct type checking,
  but every selector edits a shared enumeration and recreates merge friction.

At the time of the original fixture review, the fixture supported
build-generated entry points over a runtime package scan: runtime lookup used
the standard metadata API and feature additions did not edit per-check
packaging metadata. The statements that this remained a fixture-only design
describe that point in the review history. The production candidate and its
current limits are documented below.

The original Git test remains only a file-conflict simulation: it adds two
toy source files and leaves an empty registry file untouched. The isolated-wheel
test is stronger: it adds and runs two distinct fixture shapes through both
discovery paths while keeping generated metadata out of Git. It still does not
prove production Alphus registration or generated config/dispatch views, so it
is not compatibility evidence for the eleven migrated selectors.
The heterogeneous registry returns `object` at its dispatch boundary, and the
plugin adapter uses a checked narrowing cast; Pyright proves a concrete
provider-factory return, not a cast-free end-to-end generic registry.

At the time of the initial fixture review, the next experiment was to replace
the toy with Alphus's own declarations and build configuration. That production
step is now underway: eleven selectors generate installed entry points and
runtime views. The fixture result remains separate evidence and is not used as
proof of Alphus's production behavior.

The common registry is an index, not a universal result type. Plugin API v1
continues to own its public `RulePlugin`, `PluginRuleSpec`, namespaced
selectors and `PluginFinding` contract. Built-ins retain their existing
`RuleOutput` adapters, `RuleEvaluation`, and specialized native reports. An
adapter may place either registration source in the index without changing
those public result contracts. Selection remains explicit; registry presence
never enables a check.

The earlier spike did not resolve provider ownership in `execution/parallel.py`.
The production path now resolves cyclomatic planning, backend failure, ordered
reduction, and reporting through `CyclomaticRuleOperations` from
`execution.dispatch`. The generic scheduler keeps work ordering, locks,
budgets, and reduction. Native reports stay specialized; the registry does
not flatten them.

## Generated views and parallel authoring

The production candidate now uses standard entry points generated by the
project's PEP 517 backend from eleven typed feature-owned declarations. Runtime
discovery reads only the installed `alphus` distribution and loads a selected
runner lazily. This replaces tuple-pair `ALPHUS_CHECK` declarations for those
eleven selectors and removes their central runner-map entries. It does not yet
make authoring fully typed: the declarations still store runner module and
function names as strings, and runtime loading does not validate the full
callback/result contract.

The candidate regenerates shared runtime views such as
`policy/_generated_feature_policies.py`,
`policy/_generated_feature_definitions.py`,
`policy/_generated_quality_rule_names.py`, `policy/_generated_morphology.py`,
and `execution/_generated_dispatch.py`. They are now ignored source artifacts,
regenerated by each PEP 517 build/editable install, and included explicitly in
source archives. The tracked copies are removed, so two feature branches no
longer commit the same generated files. A fresh checkout must bootstrap them
before source imports, matching the repository's requirement to install the
editable package. The remaining cost is local stale output if a developer
switches branches without rebuilding; this is covered by the documented
bootstrap, not by a checked-in aggregate diff.

The fixture compares two registration sources and leaves one unproven option:

- Runtime package-convention discovery avoids per-check packaging entries but
  needs a central scanner and imports every first-party declaration module.
- Build-generated entry points use standard runtime metadata and avoid per-check
  packaging edits. The candidate now exercises this in an installed Alphus
  wheel for eleven checks, at the cost of a project-owned build hook.
- The build now generates the aggregate Python views as ignored artifacts.
  This removes those files from feature-branch commits; editable install and
  source archive builds are responsible for creating them before import.

The two-branch fixture experiment remains evidence only for its own package.
The Alphus wheel probe proves that installed metadata discovers the eleven
production registrations and dispatches both a finding check and the
specialized cyclomatic result path. The pinned differential matrix remains
partial: thirteen selectors have behavior-level evidence and 49 do not. The
generated-view strategy now removes those files from future feature-branch
diffs, but a two-branch Alphus test is still needed to verify that each branch's
build bootstraps its own views and the merged branch produces the same outputs.

## Owner review comments and disposition

These dispositions record implemented fixes and remaining design decisions. No
GitHub review threads were replied to, resolved, or otherwise changed.

- **JSON inventory and reports:** the earlier committed inventory and wheel
  report dumps were removed from `docs/architecture/`. The inventory test now
  generates current and pinned-reference JSON under `tmp_path`, compares the
  validated models, and leaves no bulk report in the documentation tree. A
  retained run report must remain evidence output, never an authored registry.
- **Pydantic models in `differential_wheels.py`:** use Alphus's existing
  `StrictModel` for strict immutable documents and tuple fields for arrays;
  explicit model overrides remain only where reports intentionally permit
  extra fields. The harness now follows that boundary, covered by manifest,
  inventory, and wheel-experiment tests.
- **Generator import branches:** `scripts` is an explicit package; generators
  import shared code through `scripts.*`, and inventory tests invoke the module
  with `python -m`. This keeps one import path for tests and command-line use.
- **Cyclomatic `tuple[str, str]` effective options:** replace the positional
  pair with a named immutable `CyclomaticOption(name, value)` record and adapt
  at the public report boundary to preserve the current JSON representation.
  This is a real domain-contract issue, separate from complaint ownership.
- **Parallel cyclomatic imports:** `execution.parallel` now resolves plan,
  failure, reduction, and reporting operations through the typed
  `CyclomaticRuleOperations` binding in `execution.dispatch`. The scheduler's
  ordering-only `after` dependencies and native result contracts are unchanged.
- **`comment_markers.py` tuple registration:** the former tuple-pair
  `ALPHUS_CHECK` is now a `FeatureDefinition` and its morphology is a
  `RuleMorphology`. The same typed conversion covers ten other selectors.
  Remaining selectors still use the legacy declaration paths.

## Production path and open validation

The current production slice builds standard `alphus.builtin_checks.v1`
metadata and ignored runtime views from typed source declarations, using the
installed Alphus distribution as the built-in discovery boundary. Explicit
API v1 plugin allowlisting remains separate. The installed-wheel smoke
exercised strict configuration and selected dispatch for file-size plus the
specialized cyclomatic report path; the full self-profile and package suite
are also part of validation. These checks do not establish all-selector
equivalence or validate every backend/failure state through the installed
wheel.

The registry remains an index with role-specific execution paths. Ordinary
findings retain `RuleOutput` and the shared diagnostic adapters; cyclomatic
keeps `CyclomaticReport` and its typed native operations; command steps remain
effectful `CommandRunStep` values on the generic scheduler. Plugin API v1 keeps
its own settings and finding wire contract. This slice does not flatten those
shapes into one result type. The runtime built-in loader's callable/result
validation and the interaction between generated views and the full selector
inventory remain open.

## Current scope

Eleven of 62 baseline selectors now use feature-owned typed declarations and
installed-wheel entry-point dispatch. This is an operational production slice,
not completion of issue #87. The remaining selectors, a two-branch Alphus
bootstrap test, runtime result-contract validation beyond signature binding,
complete direct/profile/serial/parallel differential coverage, and independent
exact-head review remain tracked work. No new detector or 0.0.4 behavior is
part of this slice.

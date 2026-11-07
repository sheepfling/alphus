# Typed check registry spike

This small experiment compares registration shapes for the 0.0.3 morphology
work. It is not production dispatch and does not migrate existing selectors.
The [built-in architecture plan](../BUILTIN-CHECK-ARCHITECTURE.md) remains the
single design entry point; this page records one executable prototype and its
limits.

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
the exact factory targets. It checks that the build's setuptools version meets
`>=80` and returns the exact version; this run used 84.0.0 with the existing
venv, not an isolated build environment. The generated `entry_points.txt` lives
under an ignored build directory, and the temporary repository stays clean.

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

The fixture supports build-generated entry points over a runtime package scan
for this experiment: runtime lookup uses the standard metadata API and feature
additions do not edit per-check packaging metadata. The cost is the build hook
and its convention, which remain prototype code and have not been integrated
with Alphus's build or editable-install workflow. This is a design candidate,
not an approved production architecture.

The original Git test remains only a file-conflict simulation: it adds two
toy source files and leaves an empty registry file untouched. The isolated-wheel
test is stronger: it adds and runs two distinct fixture shapes through both
discovery paths while keeping generated metadata out of Git. It still does not
prove production Alphus registration or generated config/dispatch views, so it
is not compatibility evidence for the eleven migrated selectors.
The heterogeneous registry returns `object` at its dispatch boundary, and the
plugin adapter uses a checked narrowing cast; Pyright proves a concrete
provider-factory return, not a cast-free end-to-end generic registry.

The next experiment should replace the fixture with the actual Alphus
feature-definition and build configuration, then prove generated strict policy,
selector, runner, and output views from two independent branches. It must test
whether generated aggregate files still conflict and measure the required
regeneration after merge. Until this production-shaped proof passes, the
conflict-free result applies only to the fixture and not to Alphus registration.

The common registry is an index, not a universal result type. Plugin API v1
continues to own its public `RulePlugin`, `PluginRuleSpec`, namespaced
selectors and `PluginFinding` contract. Built-ins retain their existing
`RuleOutput` adapters, `RuleEvaluation`, and specialized native reports. An
adapter may place either registration source in the index without changing
those public result contracts. Selection remains explicit; registry presence
never enables a check.

The spike does not resolve provider ownership in `execution/parallel.py`.
That module still repeats dynamic imports and casts for cyclomatic helpers.
A production check entry should own a typed cyclomatic execution adapter
covering plan construction, backend failure, ordered reduction, and report
serialization, summary, and exit status. Serial and parallel paths should
resolve that adapter through the same check entry. The generic scheduler
keeps work ordering, locks, budgets, and reduction. Native reports stay
specialized; the registry does not flatten them.

## Generated views and parallel authoring

The existing eleven-selector migration removes hand-edited central maps, but
it still regenerates shared tracked views such as
`policy/_generated_feature_policies.py`,
`policy/_generated_feature_definitions.py`,
`policy/_generated_quality_rule_names.py`, `policy/_generated_morphology.py`,
and `execution/_generated_dispatch.py`. Two feature branches can therefore
both touch the same generated files even when their declarations are separate.
The generator makes those edits reproducible; it does not remove merge
conflicts. This is a remaining architecture problem, not evidence that
parallel registration is solved.

The fixture compares two registration sources and leaves one unproven option:

- Runtime package-convention discovery avoids per-check packaging entries but
  needs a central scanner and imports every first-party declaration module.
- Build-generated entry points use standard runtime metadata and avoid per-check
  packaging edits, but add a build hook and module naming convention. The test
  proves this only for the fixture distribution.
- Tracked generated Python views still create merge friction in the current
  Alphus migration. Generating those views ephemerally may avoid Git conflicts,
  but type and test workflows would need a reliable generation step before
  import and static checking.

The fixture experiment measured the merge and wheel behavior for two feature
modules, but not the production aggregate views. A production acceptance test
must build/install the merged Alphus wheel and check selectors, strict config,
runner dispatch, plugin boundaries, and behavior outputs. It must also report
which generated files required regeneration and whether concurrent additions
conflict there. Do not count the fixture as proof that Alphus's generated views
are conflict-free.

## Owner review comments and disposition

These are design dispositions only. No GitHub review threads were replied to,
resolved, or otherwise changed.

- **Committed JSON inventory and baselines:** retain the small selector and
  effective-input inventory only if tests consume it as an audit artifact.
  Move full per-scenario wheel reports to CI artifacts; commit a compact
  evidence summary with exact wheel hashes, scenario-manifest and harness
  hashes, coverage and differences. The large source-derived baseline dump
  should be regenerated in tests rather than maintained as another JSON
  catalog. No artifact cleanup is included in this spike.
- **Pydantic models in `differential_wheels.py`:** use Alphus's existing
  `StrictModel` for strict documents and explicit model overrides only where
  the report intentionally permits extra fields. The harness should follow
  the same typed boundary it evaluates. This is not changed by the spike.
- **`generate_builtin_inventory.py` script import branch:** make `scripts` an
  explicit package and invoke package modules consistently, or move shared
  generator APIs into a package intended for imports. Keep command-line script
  execution covered. No scripts packaging change is included here.
- **Cyclomatic `tuple[str, str]` effective options:** replace the positional
  pair with a named immutable `CyclomaticOption(name, value)` record and adapt
  at the public report boundary to preserve the current JSON representation.
  This is a real domain-contract issue, separate from complaint ownership.
- **Parallel cyclomatic imports:** centralize typed provider resolution behind
  the check registry; remove the parallel module's repeated import strings and
  casts only after serial/parallel behavior has differential coverage. Keep
  scheduler ordering semantics unchanged.
- **`comment_markers.py` tuple registration:** the spike demonstrates the
  proposed semantic shape but does not edit production declarations. Do not
  mechanically wrap `ALPHUS_CHECK` in a dataclass. Replace the production
  declaration family only after the registry discovery source, ownership, and
  result adapter are reviewed as one system.

## Gate before further migration

Before the next runtime migration, review the registry source and import
boundary, confirm how a production feature is added and packaged, verify
callback typing without user-authored casts, and decide how the common registry
represents built-in, plugin, native and composite providers. The fixture now
runs an installed-wheel toy path through strict config, explicit selection,
dispatch, result adaptation and reporting. That fixture does not satisfy the
Alphus production gate: the real package still needs the same path through its
catalog, CLI/profile, native outputs and v1 plugin boundary.

## Production slice: cyclomatic result boundary

The fixture result selected one design candidate, not a production registration
architecture: build-generated standard entry points avoid per-check packaging
edits and keep runtime resolution on the standard metadata API. That result does
not settle how Alphus should generate its existing tracked catalog/config/runner
views, and it does not demonstrate conflict-free merges for those production
views. The production registry migration is still paused at that boundary.

A separate behavior-preserving native-result slice now improves the real
`cyclomatic-complexity` path. The actual catalog and strict
`CyclomaticComplexityPolicy` remain the selector/config source; the specialized
`CyclomaticReport` and its CLI/profile output remain the result contract. Its
`effective_options` are represented internally by immutable `CyclomaticOption`
records instead of unnamed string pairs. `report_payload()` explicitly adapts
them to the existing JSON array-of-pairs shape, so this type cleanup does not
change the public report schema. Parallel execution keeps its current lazy
adapter lookup: direct function-local imports were rejected by Alphus's existing
Python-style policy, so this slice does not claim to resolve the duplicated
parallel helper wiring. That wiring should move only with a registry migration
that preserves cold CLI startup and passes the existing style contract.

The existing `alphus.rules.v1` API remains the third-party registration
contract. Its installed-wheel profile test continues to prove explicit plugin
enablement, strict settings, namespaced findings and report adaptation. This
slice exercises the built-in catalog/config/native report path and the v1
plugin path separately; it does not yet place both sources in a new common
production registry. Nor does it prove production feature additions avoid edits
to generated tracked views. The fixture test's two independent declarations
prove that property only for its disposable package, where generated entry-point
metadata is build output and not tracked source.

The remaining production design decision is where generated built-in views
live. Keeping generated catalogs tracked preserves readable source artifacts
but leaves merge conflicts when parallel branches regenerate the same file.
Generating them into build output avoids that shared-file conflict but requires
Alphus build and editable-install integration, plus equivalent strict-config
and CLI/profile tests. The next migration must exercise two distinct production
check shapes and verify both branches regenerate identical merged views from
feature-owned declarations before that approach is adopted. Until then, this
slice changes the typed native result contract only and does not claim to
complete issue #87 or the authoring-friction goal.

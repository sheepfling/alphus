# Typed check registry spike

This small experiment compares registration shapes for the 0.0.3 morphology
work. It is not production dispatch and does not migrate existing selectors.
The [built-in architecture plan](../BUILTIN-CHECK-ARCHITECTURE.md) remains the
single design entry point; this page records one executable prototype and its
limits.

## Prototype and authoring path

The prototype lives in `scripts/typed_registry_spike.py` and
`scripts/registry_spike/`. The toy check follows this flow:

1. `toy_registration.py` owns a strict policy type, a typed
   `RuleMorphology`, and a named `ComplaintContract` containing structured
   `ComplaintTag` records.
2. `register_toy_check()` returns `BuiltinCheckDefinition[Settings, Evidence,
   Output]`. Its provider factory is a typed `EntryPointProviderFactory`;
   the analyzer entry point is resolved only when that check is selected.
   The feature metadata has no provider module or function string.
3. `CheckRegistry.discover()` sorts entry points, loads the metadata factory,
   rejects duplicate names, and combines built-in definitions with the
   existing explicitly enabled API v1 plugin bindings.
4. Calling the definition's typed `execute()` resolves the provider and applies
   the typed result adapter. The toy returns `CyclomaticReport` unchanged,
   demonstrating that the registry does not turn specialized results into
   `PluginFinding` records.

The declaration reuses the existing `RuleMorphology` type. Complaint ownership
uses `ComplaintContract` and `ComplaintTag` records rather than unnamed
string-pair tuples. The production `ALPHUS_CHECK`,
`ALPHUS_COMPLAINT_CONTRACTS`, and some result metadata remain unchanged while
this design is reviewed.

## Executed evidence

`tests/architecture/test_typed_check_registry_spike.py` verifies metadata
bootstrap, duplicate rejection, analyzer laziness, typed execution, a
specialized result, plugin API v1 namespace preservation, and direct provider
entry-point behavior. The entry-point tests use real stdlib `EntryPoint`
objects with a test-only discovery source; no toy selector is added to the
package's installed entry-point table.

Commands run in the current worktree:

```sh
.venv/bin/python -m pytest tests/architecture/test_typed_check_registry_spike.py -q
.venv/bin/python -m pyright scripts/typed_registry_spike.py scripts/registry_spike
.venv/bin/alphus --root . --config quality-gates.toml --run --profile check
.venv/bin/alphus --root . --config quality-gates.toml --run --profile markdown-shell-review
```

Results: 6 spike tests passed; Pyright reported 0 errors, warnings, or
information. The full self-profile passed 27 checks, with 0 failures and 4
provisional passes; its package suite passed 2,478 tests with 43 skipped. The
Markdown shell review passed. The environment emitted one informational
typing-stub notice for an installed `types-PyYAML` version outside the
configured range; it did not fail the profile.
The callbacks in `toy_registration.py` have concrete generic annotations and
contain no casts. Discovery imports the metadata module but not
`toy_analyzer.py`; execution imports the analyzer through its typed callback.
The successful import and strict type check exercise the intended acyclic
boundary: metadata depends on contracts and policy; the analyzer does not
register itself or import the registry.

This is a prototype result, not proof that installed package metadata,
production CLI dispatch, strict TOML integration, or the complete 62-selector
catalog works through this registry.

## Alternatives and trade-offs

- **Metadata-only entry point plus typed registry:** Standard discovery; metadata
  modules load without analyzers; one registry indexes built-ins and API v1
  plugin bindings. A per-check entry point must be packaged. Hand-maintained
  `pyproject.toml` entries become a second authoring location unless generated.
- **Direct first-party provider entry point:** Standard and lazy when the
  selected endpoint is loaded. Its metadata supplies a name and import target,
  not strict config, morphology, effective policy inputs, or result adaptation.
  Those contracts need another source; loading it to inspect them imports the
  provider.
- **Import metadata-only Python modules by package convention:** Feature-local
  typed objects without an entry-point table. Discovery imports every
  registration module, so the boundary needs import-side-effect tests and a
  narrow documented contract.
- **Static AST parsing of typed constructors:** No registration-module imports
  and deterministic discovery, but still a custom source language and parser.
  Replacing tuples with a dataclass does not remove that cost.
- **Central Python mapping:** Simple runtime behavior and direct type checking,
  but every selector edits a shared enumeration and recreates the registration
  burden this work is meant to remove.

The spike favors typed metadata modules plus a common registry as a useful
contract boundary, but it does **not** settle the discovery source. For the
production choice, decide whether per-feature packaging entries are acceptable
or whether avoiding that second authoring location is more important. If
single-location authoring is required, the current metadata-module prototype
needs a discovery design that does not merely reintroduce a bespoke AST
language.

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

Before the next runtime slice, review the registry source and import boundary,
confirm how a new feature is added and packaged, verify callback typing without
user-authored casts, and decide how the common registry represents built-in,
plugin, native and composite providers. Then run one installed-wheel toy path
through strict config, explicit selection, dispatch, result adaptation and
reporting. The present spike proves metadata bootstrap and typed execution in
isolation; it does not satisfy that end-to-end migration gate.

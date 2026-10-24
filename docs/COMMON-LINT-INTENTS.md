# Common lint intents

Alphus groups selected native rules under three comparable intents: naming,
unused symbols, and unreachable code. A shared intent identifies the kind of
concern; it does not promise equal analysis or findings across tools. The
validated, warning-level mappings live in
[`policy/native_intents.py`](../src/alphus/policy/native_intents.py).

These mappings are opt-in metadata. They do not install tools, change a
consumer's native configuration, add rules to a command, or parse arbitrary
stdout and stderr. Consumers own tool versions, rule selection, file scope,
ignores, and native invocations. An adapter can attach a typed Alphus identity
to a normalized native diagnostic while retaining its source, rule ID,
location, message, and public wire format.

## Capability map

### Naming

- **Python:** Ruff's `N801`–`N807`, `N811`–`N818`, and `N999`; Pylint `C0103`.
  Ruff uses distinct rule IDs for classes, functions, methods, arguments,
  variables, modules, and aliases. Pylint's `C0103` relies on per-kind regex
  settings. Ruff's verified range is `>=0.16,<1`; consumers pin Pylint.
- **C and C++:** clang-tidy `readability-identifier-naming`. Match its version
  to the compiler. Only identifier kinds configured in `.clang-tidy` are
  checked; an empty naming configuration does not enforce a convention.
- **JavaScript:** ESLint `camelcase` and `id-match`. Consumers pin ESLint.
  `camelcase` inspects selected definitions and assignments; `id-match` applies
  a consumer-owned regex to a narrower set of declarations.

### Unused symbols

- **Python:** Ruff `F401`, `F841`, `ARG001`–`ARG005`; Pylint `W0611`, `W0612`, `W0613`,
  `W0614`, and `W0238`. Ruff's verified range is `>=0.16,<1`; consumers pin
  Pylint. Coverage includes imports, function-local assignments, arguments,
  wildcard imports, and some private members. Re-exports, underscore arguments,
  callbacks, and generated files need native configuration or exclusions.
- **C and C++:** Clang `-Wunused-variable`, `-Wunused-function`, and
  `-Wunused-parameter`; clang-tidy `bugprone-unused-local-non-trivial-variable`.
  Match tool versions to the build. Compiler warnings only exist when enabled
  by the actual compile flags. The clang-tidy rule covers a narrow class of
  non-trivial locals, not general dead-code analysis.
- **JavaScript:** ESLint `no-unused-vars`. Options control parameters, caught
  errors, destructuring, exports, and ignored names. Module and script modes
  affect how globals and exports are treated.
- **TypeScript:** `@typescript-eslint/no-unused-vars`. Consumers pin ESLint and
  plugin versions. The TypeScript parser and plugin are required; use this
  extension rule in place of core `no-unused-vars`. Type-only symbols and
  underscore conventions depend on configuration.

### Unreachable code

- **Python:** Pylint `W0101`. Ruff has no mapped unreachable-code rule; its
  capability is explicitly unsupported. Consumers pin Pylint, and Pylint's
  control-flow analysis remains configuration-dependent.
- **C and C++:** Clang `-Wunreachable-code` and
  `-Wunreachable-code-aggressive`. Match the compiler version to the build.
  Findings depend on the active warning flags; a missing or disabled warning
  is not a pass.
- **JavaScript:** ESLint `no-unreachable`.
- **TypeScript:** ESLint `no-unreachable` or compiler diagnostic `7027` when
  `allowUnreachableCode` is false. Choose one backend for a file; the compiler's
  default editor suggestions do not make this a gate.

All bindings default to `warning` severity for advisory adoption. Consumers
choose their failure threshold. Alphus does not implicitly replace the
consumer's native configuration or command severity.

`resolve_native_rule_selection` keeps an existing consumer setting authoritative.
It applies a shared selection only after explicit opt-in, and reports a
conflict when the two opted-in settings disagree; the consumer value remains
effective and the conflict is available to callers.

## Mapping and result handling

`binding_for_native_rule` resolves only an explicitly listed backend, rule ID,
and language. Unknown IDs stay native and unclassified. Before a mapping can
be attached, `validate_native_context` requires the executable and version.
Compiler warnings require the effective compiler arguments; clang-tidy checks
also require compile-database context. Reports with syntax errors are rejected.
Verified version ranges are checked directly; consumer-pinned tools must
provide an observed version and required plugins must provide observed
versions; clang and clang-tidy must match the compiler's major version. The
TypeScript compiler mapping requires effective
`allowUnreachableCode=false` settings, not just a compiler invocation.

`bind_native_diagnostic` preserves the native rule ID and public diagnostic
fields while adding the typed Alphus tag in memory. The tag supports category
filtering and cross-language rollups without changing serialized JSON.
Rollups suppress an Alphus finding only when its tag, path, line, and message
exactly match a native result. Separate native rule IDs and different evidence
remain visible; severity is promoted to the highest value among matches.

The current command runner still treats native output as opaque text. A
tool-specific parser must convert structured output into `Diagnostic` records
and provide observed tool context before these mappings participate in a run.
Until then, this catalog is an explicit capability inventory and safe mapping
boundary; it does not claim that a native command ran or its output was parsed.

## Deferred integrations

Dependency and layer boundaries, semantic clone detection, unsafe-construct
rules, and assertion conventions remain separate evaluations. Adopt a future
backend only after checking that it is maintained, names the languages and
frameworks it supports, exposes its version and configuration, and does not
duplicate an existing Alphus or native check. Keep consumer-owned relationships
and exclusions explicit.

- **Dependency boundaries:** require consumer-declared allowed or forbidden
  relationships and report the imports that violate them. Reconcile findings
  with Alphus's architecture/import checks and C++ include-impact evidence;
  include fanout alone is not a dependency violation.
- **Duplication:** select the clone kind (text, token, or semantic), minimum
  size, exclusions, and backend provenance before reporting findings. Exclude
  generated code, fixtures, and intentional mirrored interfaces where the
  consumer requests it. Existing repeated-window C++ findings remain review
  heuristics, not proof of duplicated behavior; do not substitute an arbitrary
  repository-wide percentage.
- **Unsafe constructs and assertion conventions:** inventory maintained
  language- or framework-specific checks, document their scope and native
  configuration, and keep test-oracle independence as its own review concern.
  Do not impose a universal rule across unrelated frameworks.

## Native references

- [Ruff rule catalog](https://docs.astral.sh/ruff/rules/)
- [Pylint message catalog](https://pylint.readthedocs.io/en/stable/user_guide/messages/messages_overview.html)
- [ESLint `no-unused-vars`](https://eslint.org/docs/latest/rules/no-unused-vars)
- [ESLint `no-unreachable`](https://eslint.org/docs/latest/rules/no-unreachable)
- [ESLint `camelcase`](https://eslint.org/docs/latest/rules/camelcase)
- [TypeScript `allowUnreachableCode`](https://www.typescriptlang.org/tsconfig/allowUnreachableCode.html)
- [clang-tidy identifier naming](https://clang.llvm.org/extra/clang-tidy/checks/readability/identifier-naming.html)
- [Clang diagnostic flags](https://clang.llvm.org/docs/DiagnosticsReference.html)

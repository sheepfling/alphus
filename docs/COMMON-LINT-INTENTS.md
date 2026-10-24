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

## Evaluated follow-up integrations

These candidates do not add a shared gate or install a tool. Consumers still
own their native configuration, versions, scope, and exclusions. A generic
Alphus command step can invoke a native checker, but the current runner treats
its output as opaque text; typed findings require a separate parser and
version-pinned fixtures. These are capability evaluations, not Alphus-supported
version ranges, integrated gates, or validated adapters. This document does not
pin or install third-party tools; consumers must pin each tool and its required
parser, runtime, compiler, or plugin in their own repository.

### Dependency and layer boundaries

| Language   | Existing coverage and evaluated candidate                                                                                                                                                                                                                                                                                           | Requirements and current limit                                                                                                                                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python     | Alphus `package-boundaries` checks declared distribution edges, imported local package edges, and cycles. It does not express arbitrary layers inside one package. [Import Linter](https://import-linter.readthedocs.io/en/stable/contract_types/) offers forbidden, protected, layer, independence, and acyclic-sibling contracts. | Reuse Alphus for distribution boundaries. Consider Import Linter for opt-in intra-package contracts only; pin its Python package and keep its module patterns and exceptions consumer-owned. Do not report the same package edge twice. |
| C/C++      | Alphus's include-impact evidence measures affected includes and fanout. It does not decide whether a source-to-target edge violates architecture. clang-tidy include checks concern include correctness; they are not allowed/forbidden layer contracts.                                                                            | No shared source-layer mapping is selected. A future check needs the consumer's build targets, compiler flags, and compilation database; include fanout alone is not a dependency violation.                                            |
| JavaScript | [dependency-cruiser](https://github.com/sverweij/dependency-cruiser/blob/main/doc/rules-reference.md) supports consumer-defined `forbidden` and `allowed` module relationships, severities, and reasons.                                                                                                                            | Candidate for an opt-in module-boundary command. Pin Node, dependency-cruiser, and its config; validate path aliases, unresolved modules, and dynamic imports instead of treating incomplete resolution as a pass.                      |
| TypeScript | dependency-cruiser can analyze TypeScript through the project's configured TypeScript/transpiler support.                                                                                                                                                                                                                           | Use a pinned TypeScript toolchain and the consumer's path/module-resolution settings. No Alphus typed TypeScript module-boundary mapping exists yet.                                                                                    |

### Code duplication

Two maintained candidates cover the requested source languages:

- [PMD CPD](https://pmd.github.io/pmd/pmd_userdocs_cpd.html) supports Python,
  C/C++, JavaScript, and TypeScript. Its minimum-token option gives a concrete
  token clone threshold, and it can emit XML, CSV, or other native reports.
  Pin the PMD release and use its documented Java runtime. Comment suppression
  is language-specific; generated code, fixtures, tests, and intentionally
  mirrored interfaces still need consumer-owned directory or file exclusions.
- [jscpd](https://jscpd.dev/concepts/how-detection-works) is also token-based
  and provides configurable minimum tokens/lines and JSON/SARIF reporters. Its
  configuration distinguishes exact, renamed, near-miss, AST, and semantic
  clone kinds. Pin the package/runtime and explicitly select the desired kinds;
  do not enable semantic or model-backed detection as an accidental default.

PMD CPD is the bounded first candidate for a token-clone prototype; compare it
with jscpd against the same positive, negative, generated-code, and suppression
fixtures before choosing an Alphus adapter. Neither is selected as a shared
Alphus gate yet. Token counts and clone kinds differ by backend and language,
so record the native backend, version, language, minimum token/line threshold,
exclusions, locations, and analyzed-file coverage. Do not compare raw scores
across tools or impose a repository-wide duplication percentage. Existing
repeated-window C++ results remain advisory review evidence, not proof of
duplicated behavior.

### Unsafe constructs and security hotspots

| Language   | Maintained native candidates                                                                                              | Configuration and evidence boundary                                                                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python     | Ruff's selected `S` rules and [Bandit](https://bandit.readthedocs.io/en/latest/) AST plugins.                             | Pin the tool and exact rule set. Avoid duplicate Ruff/Bandit findings; Bandit reports common security patterns, not exploitability or a complete security review.              |
| C/C++      | [clang-tidy](https://clang.llvm.org/extra/clang-tidy/checks/list.html) CERT, bug-prone, and Clang Static Analyzer checks. | Pin clang-tidy to the compiler/toolchain and use the build's compile database and flags. Check groups are specific diagnostics, not a universal unsafe-code ban.               |
| JavaScript | [eslint-plugin-security](https://github.com/eslint-community/eslint-plugin-security).                                     | Pin ESLint and the plugin. Its maintainers describe results as security hotspots with false positives that need human triage.                                                  |
| TypeScript | The JavaScript ESLint security plugin is a candidate only for rules that work with the consumer's TypeScript parser.      | Pin ESLint, plugin, parser, and TypeScript versions together; prove each selected rule on TypeScript fixtures before mapping it. TypeScript coverage is otherwise unsupported. |

There is no single cross-language definition of “unsafe construct.” Keep each
native rule ID, language, parser/tool version, source location, severity, and
consumer exclusion. Do not infer that an unselected or unavailable rule passed.

### Test assertion conventions

| Language/framework                    | Evidence and limits                                                                                                                                                                                                                     |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python/pytest                         | `assert` is idiomatic and pytest enhances its failure output. Use pytest's framework APIs for exception assertions; a generic ban on `assert` would reject ordinary tests and would not establish oracle quality.                       |
| C/C++ test frameworks                 | Assertion macros and failure behavior vary by the selected framework. Compiler warnings do not establish that expected values are independent or meaningful. No framework-neutral mapping is selected.                                  |
| JavaScript/TypeScript test frameworks | Assertion APIs and matchers differ across Jest, Mocha/Chai, Node, and other frameworks. A rule about Node's `assert` API is not a rule about a test's oracle. Require explicit framework-specific coverage; otherwise mark unsupported. |

Keep issue [#15](https://github.com/sheepfling/alphus/issues/15) separate:
assertion style is not proof of test-oracle independence. No universal
assertion-convention rule is selected.

### Adoption criteria

Before turning any candidate into an Alphus mapping or gate:

1. Pin the native tool and required parser, compiler, runtime, or plugin; verify
   the version and configuration actually used.
2. Scope each language independently. Make generated-code, test, fixture, and
   intentional-mirror exclusions explicit, with a reason where supported.
3. Preserve native rule IDs, messages, locations, and severity. Add a typed
   Alphus category only when evidence has the same meaning; never merge
   unrelated checks because their names sound similar.
4. Add positive, negative, ambiguity, exclusion, malformed-output, missing-tool,
   and incomplete-resolution fixtures. Operational errors cannot become a
   clean pass.
5. Keep the integration opt-in. Do not install tools for consumers, add CI
   triggers, or enable a repo-wide architecture, clone threshold, security ban,
   or assertion rule by default.

## Native references

- [Ruff rule catalog](https://docs.astral.sh/ruff/rules/)
- [Pylint message catalog](https://pylint.readthedocs.io/en/stable/user_guide/messages/messages_overview.html)
- [ESLint `no-unused-vars`](https://eslint.org/docs/latest/rules/no-unused-vars)
- [ESLint `no-unreachable`](https://eslint.org/docs/latest/rules/no-unreachable)
- [ESLint `camelcase`](https://eslint.org/docs/latest/rules/camelcase)
- [TypeScript `allowUnreachableCode`](https://www.typescriptlang.org/tsconfig/allowUnreachableCode.html)
- [clang-tidy identifier naming](https://clang.llvm.org/extra/clang-tidy/checks/readability/identifier-naming.html)
- [Clang diagnostic flags](https://clang.llvm.org/docs/DiagnosticsReference.html)
- [Import Linter contracts](https://import-linter.readthedocs.io/en/stable/contract_types/)
- [dependency-cruiser rules](https://github.com/sverweij/dependency-cruiser/blob/main/doc/rules-reference.md)
- [PMD copy/paste detector](https://pmd.github.io/pmd/pmd_userdocs_cpd.html)
- [jscpd detection model](https://jscpd.dev/concepts/how-detection-works)
- [Bandit documentation](https://bandit.readthedocs.io/en/latest/)
- [clang-tidy checks](https://clang.llvm.org/extra/clang-tidy/checks/list.html)
- [ESLint security plugin](https://github.com/eslint-community/eslint-plugin-security)
- [pytest assertion documentation](https://docs.pytest.org/en/stable/how-to/assert.html)

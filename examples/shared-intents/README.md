# Shared quality intent example

This example coordinates a function-complexity review across Python, C++, and
JavaScript. It shows where native rules are comparable and where the counts
differ. It does not create one cross-language numeric score.

After installing Alphus in editable mode, inspect the dry-run plan from the
repository root:

```sh
alphus --root examples/shared-intents --config quality-gates.toml --plan --json
```

Run the selected native checks with:

```sh
alphus --root examples/shared-intents --config quality-gates.toml
```

The profile is provisional. Install and pin Ruff, clang-tidy, and ESLint in the
consumer's development environment before running it. For clang-tidy, create a
compilation database first:

```sh
cmake -S examples/shared-intents -B examples/shared-intents/build \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

The intent sets per-language thresholds explicitly: Ruff C901 uses 12,
clang-tidy's branch count uses 6, and ESLint uses 10. Only the Ruff binding is
declared exact for the shared McCabe definition. The C++ binding counts control
statements, and the JavaScript binding retains ESLint's selected variant and
syntax-specific behavior. Their thresholds are local native settings, not
interchangeable measurements. `--plan` reports each backend range, rule ID,
scope, effective configuration, owner, rollout, and mapping status without
invoking any tool.

Language-specific values override shared values when present; omitted values
inherit the shared policy. The example sets each language's include scope and
adds the shared generated-file exclusion. A binding may request JSON evidence
validation for a selected output stream. Alphus checks that stream for a valid
top-level JSON array while preserving stdout and stderr in the execution report;
it does not interpret backend-specific diagnostic schemas or extract numeric
metrics. Bindings left at `evidence_format = "raw"` retain output without
parsing it.

The native files remain the owners of tool behavior: `ruff.toml`, `.clang-tidy`,
and `eslint.config.js`. The TOML `effective_configuration` entries state the
values the consumer has resolved in those files; Alphus does not rewrite or
replace them. Version ranges declare the versions covered by this example;
Alphus does not install tools or enforce those ranges against an installed
binary. Install only the tools selected by the consumer. C and C++ projects must
provide their own compiler and compilation database.

Ruff's C901 and exit status are described in its [rule
reference](https://docs.astral.sh/ruff/rules/complex-structure/) and [exit-code
guide](https://docs.astral.sh/ruff/linter/#exit-codes). Clang-tidy documents the
distinct branch and statement thresholds in [`readability-function-size`](https://clang.llvm.org/extra/clang-tidy/checks/readability/function-size.html).
ESLint documents the classic and modified variants in its [`complexity` rule](https://eslint.org/docs/latest/rules/complexity) and its [CLI exit codes](https://eslint.org/docs/latest/use/command-line-interface#exit-codes).

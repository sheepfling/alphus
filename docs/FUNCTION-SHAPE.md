# Native function-shape policy

Function-shape metrics are opt-in native checks. Alphus validates their policy
and prints a dry-run mapping; Ruff, Pylint, ESLint, and clang-tidy continue to
parse source and own the reported count. Alphus does not run a second AST
counter, rewrite native configuration, autofix signatures, or normalize counts
across languages.

## Policy

Add a `[checks.function_shape]` section with one target per language/backend
pair. Presence of a metric enables only that metric; `maximum` is the inclusive
allowed count (the native rule reports when its count exceeds that value).
Targets choose language-specific scopes and exclusions. Use distinct targets to
select Ruff or Pylint for Python. The mapping can be inspected without invoking
the linters:

```toml
[checks.function_shape]

[[checks.function_shape.targets]]
language = "python"
backend = "ruff"
minimum_version = "0.16.0"
severity = "warning"
include = ["src/**/*.py"]
exclude = ["src/generated/**"]
metrics = [
  { name = "parameters", maximum = 5 },
  { name = "nesting", maximum = 3 },
  { name = "statements", maximum = 30 },
]

[[checks.function_shape.targets.overrides]]
include = ["src/api/**"]
exclude = ["src/api/generated/**"]
metrics = [{ name = "parameters", maximum = 8 }]
severity = "warning"

[[checks.function_shape.targets]]
language = "javascript"
backend = "eslint"
minimum_version = "9.0.0"
severity = "warning"
include = ["web/**/*.js", "web/**/*.mjs"]
metrics = [{ name = "parameters", maximum = 5 }]

[[checks.function_shape.targets]]
language = "cpp"
backend = "clang-tidy"
minimum_version = "18.0.0"
include = ["native/**/*.cpp", "native/**/*.h"]
compilation_database = "build/compile_commands.json"
metrics = [
  { name = "parameters", maximum = 6 },
  { name = "nesting", maximum = 4 },
  { name = "statements", maximum = 40 },
]
```

`minimum_version` is a consumer-declared floor included in the plan; Alphus
does not install tools or inspect the version on `PATH`. The C++ planner checks
that the compilation database exists, is valid JSON, and contains command
entries. It does not prove those commands succeed. A native clang-tidy command
must still run with that database; missing or invalid compiler context is an
operational failure, never a clean check.

Run `alphus --root . --config quality-gates.toml --plan-function-shape` to
print JSON containing the backend, consumer-declared minimum version, enabled
metrics, exact native rule/option, native count description, scope, and preview
requirements. The command is read-only and does not add a native config file.
The Python planner returns a frozen plan object; `to_dict()` creates fresh
JSON-compatible data for callers that need serialization or mutation.
An unsupported setting is rejected by policy validation rather than omitted.
Path overrides replace the target's full metric set when `metrics` is
specified; otherwise they inherit it. An override can also change severity.
The plan prints scopes separately so consumers can use a reviewed
per-scope native configuration. Exclude FFI/generated/interface implementation
files, callbacks, or legitimate domain APIs by path where needed; Alphus does
not infer those roles from source.

For clang-tidy, `ignore_macros` and
`count_member_initializers_as_statements` pin native count behavior. Defaults
follow clang-tidy (`false` and `true`). These fields are rejected for other
languages. The planner sets unselected `readability-function-size`
`ParameterThreshold`, `NestingThreshold`, and `StatementThreshold` options to
`-1` so clang-tidy keeps omitted metrics disabled, including in metric-replacing
overrides.

## Capability matrix

- Python / Ruff: parameters `PLR0913`; nesting `PLR1702`; statements `PLR0915`.
  `PLR1702` needs preview mode; `PLR0913` exempts methods marked `@typing.override`.
- Python / Pylint: parameters `R0913`; nesting `R1702`; statements `R0915`.
  Native message thresholds use Pylint's `design` options.
- JavaScript / ESLint: parameters `max-params`; nesting `max-depth`; statements
  `max-statements`. `max-depth` counts blocks, not callback nesting.
- C++ / clang-tidy: `readability-function-size` uses its parameter, nesting, and
  statement thresholds. It requires a compilation database; macro behavior is
  controlled by native options.

Rule availability and preview status are taken from the tools' rule catalogs.
The validator enforces the documented introduction floor for Ruff's three
rules, Pylint 1.9 for this selected Pylint set, and ESLint 0.0.9 for these core
rules. For clang-tidy, the configured `minimum_version` is the consumer's
compatibility assertion because the option page does not publish an
introduction floor. The plan does not verify the version against an installed
binary.
The native definitions are documented by [Ruff's PLR0913](https://docs.astral.sh/ruff/rules/too-many-arguments/),
[Ruff's PLR0915](https://docs.astral.sh/ruff/rules/too-many-statements/),
[Ruff's PLR1702](https://docs.astral.sh/ruff/rules/too-many-nested-blocks/),
[Pylint's message catalog](https://pylint.readthedocs.io/en/stable/user_guide/messages/messages_overview.html),
[ESLint's max-params](https://eslint.org/docs/latest/rules/max-params),
[ESLint's max-depth](https://eslint.org/docs/latest/rules/max-depth),
[ESLint's max-statements](https://eslint.org/docs/latest/rules/max-statements), and
[clang-tidy readability-function-size](https://clang.llvm.org/extra/clang-tidy/checks/readability/function-size.html).

## Count boundaries and rollout

The native checker defines details such as receivers, keyword-only and
variadic parameters, defaulted and destructured parameters, declaration versus
definition handling, nested functions/callbacks, implicit statements, macro
expansion, and instantiated templates. ESLint counts each destructured
parameter declaration once; its `max-params` `countThis` option applies only to
TypeScript. ESLint `max-statements` excludes statements in nested functions
from the enclosing function's count. clang-tidy `readability-function-size`
does not count lambdas, instantiated declarations, or nested class inline
functions as ordinary function bodies; `IgnoreMacros` and
`CountMemberInitAsStmt` alter its statement/nesting definition. Ruff
`PLR0913` excludes bound `self`/`cls` and `*args`/`**kwargs`, but counts
defaulted and keyword-only parameters; this is exercised against Ruff 0.16.1
in the native boundary fixtures. It also exempts explicitly `@typing.override`
methods. Read the selected
backend's versioned documentation and treat its reported count as authoritative.
The plan retains the backend rule ID and its count description; no
cross-language equality is promised.
Cross-language source examples live in `tests/fixtures/function_shape/`;
the Ruff integration test executes the positive, boundary, and negative
Python cases with its native rules. Pylint, ESLint, and clang-tidy remain
optional native tools and should be exercised by a consumer profile that
provisions those tools and its C++ compile context.

Use an advisory rollout first. Ruff and Pylint commands can use their native
exit-zero options; ESLint uses warning severity; clang-tidy diagnostics remain
warnings unless the consumer's command promotes them. Existing native config
files remain the consumer's source of truth: apply the printed key/value
mapping in that config or in a reviewed per-run overlay. Keep the rule IDs in
the native command output so the origin remains visible. Alphus does not parse
native diagnostics into duplicate Alphus findings. If consumers run multiple
backends over the same files, each backend may emit its own equivalent finding.
ESLint severity values map `error` to `error` and `warning` to `warn`; `info` is
rejected for ESLint targets and overrides because ESLint has no informational
severity.

Positional parameter count is not this feature's total-parameter metric, and
neither metric says whether argument types are confusable. See the separate
[interface-safety work](https://github.com/sheepfling/alphus/issues/14). These
limits are configurable review signals, not universal architectural rules.
Exclude generated code, callbacks, FFI boundaries, interface implementations,
and legitimate domain APIs when the consumer's codebase needs those
exceptions. Do not replace a semantic record with a generic parameter bag only
to lower a count; no signature autofix is provided.

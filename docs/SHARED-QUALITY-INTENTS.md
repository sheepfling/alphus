# Shared quality intents

Shared intents give a stable Alphus policy identity to checks implemented by
native language tools. They extend the existing orchestration profiles and
command steps; they do not replace those steps or create another runner.

The [working example](../examples/shared-intents/README.md) coordinates Python,
C++, and JavaScript function-complexity checks. It declares Ruff C901 as an
exact McCabe mapping, and clang-tidy and ESLint as comparable mappings with
their own measurements and thresholds. A comparable mapping is not evidence
that two tools count the same constructs or produce interchangeable numbers.

## Capability contract

Each shared intent has an `alphus/any/...` rule ID, summary, canonical metric,
unit, count method, enabled and required settings, rollout, selected profiles,
file inventory, and native bindings. Each binding names its language, backend,
declared version range, native rule, metric and counting method, supported
options, effective native configuration, coverage limits, and optional
exit-code and output-format classifications. Supported mappings also name
their command step.

The `mapping` value has three meanings:

- `exact`: metric, unit, and count method must match the shared intent.
- `comparable`: the rule serves a related review goal but measures differently.
  It needs a language-specific threshold when the intent also declares a shared
  numeric threshold.
- `unsupported`: this language has no selected native implementation. It has
  no command step and remains visible in plans and execution reports.

`version_range` is a declared compatibility range in PEP 440 specifier syntax.
Alphus validates its syntax but does not probe an installed executable or
enforce the range at runtime. Consumers should pin the native tools in their
own dependency workflow and test the versions they install. The example lists
the applicable backend ranges and keeps every integration provisional.

## Precedence and ownership

Shared values are defaults. A language override replaces a shared value when
that field is present; omitted fields inherit. For file scope, a language
override replaces the shared include patterns and appends its exclusions to
the shared exclusions. The command step must use that resolved inventory
exactly. This makes the selected paths visible and keeps the intent scope and
the native invocation aligned.

Native `effective_configuration` must agree with a resolved shared threshold,
severity, or failure threshold when it maps that option. Conflicting native
values, undeclared option keys, and incompatible mappings are configuration
errors during policy loading. The configuration is declarative: Alphus reports
it in the plan but does not edit or replace `.ruff.toml`, `.clang-tidy`, ESLint
configuration, or other native files. No automatic fixes run through an
intent.

Some native settings encode a numeric threshold as text. `threshold_values`
declares those per-threshold native values; Alphus compares the declared value
and type with `effective_configuration` instead of silently coercing it.

The native command remains the owner of diagnostics. Alphus keeps its native
rule ID and output on the command step; each intent result points to that step
as its evidence source and carries the stable Alphus semantic rule ID. Alphus
does not normalize native diagnostic schemas or synthesize a second copy of a
native finding.

## Plans and results

`alphus --plan --json` includes an `intents` array when the policy declares
intents. Each row shows resolved language values, mapping status, command and
evidence step, selected files, expanded arguments, native ownership, rollout,
and effective configuration. Human-readable plans include the same core
provenance. Policies without intents retain their existing plan and execution
JSON keys.

At execution time, an intent binding can report disabled, not selected, not
applicable, passed, failed, or unsupported. Failed bindings distinguish a
declared violation exit code, a declared configuration exit code, and other
operational failures. Missing executables and timeouts fail the step. An empty
file inventory is reported as `not_applicable`, never as a pass. A required
unsupported binding blocks only when the intent is `mainline`; provisional or
optional unsupported mappings remain visible as advisory outcomes.

When every selected intent binding for a command step is disabled, Alphus
records the step as `disabled` without launching its native command. A step
shared by another selected, enabled binding still runs, and the disabled
binding remains visible in the result.

Output is raw by default and is retained on the command result. A binding may
declare `evidence_format = "json-array"` or `"json-object"` and choose `stdout`
or `stderr` for the evidence stream. Alphus checks that decoded output has the
requested top-level sequence/list or mapping/object shape; invalid JSON or a
different shape fails operationally. It does not interpret container contents
or extract metric values. Use `raw` when a backend does not provide one of
those output shapes. Status and failure-kind classifications use closed
string-valued enums and retain their string values in JSON reports.

Native tools remain opt-in. Their installation and build requirements belong
to the consumer. In particular, C++ projects supply their own compiler and
compilation database. This foundation does not add universal scores, replace
native parsers, install tools, or change hosted CI triggers.

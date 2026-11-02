# Cyclomatic complexity gates

Alphus provides an opt-in `cyclomatic-complexity` rule that coordinates pinned
native backends. It does not replace their metric definitions with a shared
parser. Consumers choose one backend per supported language, set an inclusive
maximum, and may override that limit and severity for each backend. The default
severity is `warning`, so a configured rule can enter an advisory profile before
a project chooses to make warnings fail.

The [polyglot consumer example](../examples/cyclomatic/README.md) shows an
installed-package policy for Python, C/C++, and JavaScript. Its tools and
versions are explicit. The Lizard dependency is optional and pinned through
`alphus[cyclomatic-lizard]`; Ruff and ESLint remain tools owned and pinned by
the consumer repository.

## Planning and running

Resolve the file inventory and native invocations without starting any native
tool:

```shell
alphus --root /path/to/consumer \
  --config /path/to/consumer/quality-gates.toml \
  --rule cyclomatic-complexity --plan
```

Run the selected backends and inspect their structured report:

```shell
alphus --root /path/to/consumer \
  --config /path/to/consumer/quality-gates.toml \
  --rule cyclomatic-complexity --json
```

`--output auto` selects rich text for a terminal and plain text when output is
redirected. Choose `--output plain` or `--output rich` to set the human format;
`--output json` is equivalent to `--json`. JSON output cannot be combined with
an explicit human format.

The same rule can be added to an orchestration profile using
`rule = "cyclomatic-complexity"`. Profile JSON includes a `report` object on
that step. Existing profile steps keep their current output fields. Direct
`--report` suppresses threshold exits but still returns failures for unavailable
tools, version mismatches, malformed native output, timeouts, parse failures,
and missing coverage. A configured language with no matching files is
`no_matching_files` (or `incomplete_coverage` when another backend selected
files), with exit code 2; this is never reported as a clean metric.
Threshold violations return exit code 1. Operational failures, including
missing coverage, return exit code 2 even with `--report`.

Pass `--jobs N` to run independent configured backends under one worker budget.
A profile step opts in with `parallel = true`. See
[parallel execution](PARALLEL-EXECUTION.md) for worker and ordering controls.

## Report contract

Every run records the metric, backend and actual tool version, native rule,
count method, variant, maximum, severity, effective native options, and selected
versus analyzed file counts. Function records contain a stable path-qualified
identity and source location (line and column when the native tool supplies
one). Lizard supplies numeric values for all parsed
functions. Ruff and ESLint supply threshold diagnostics, not full numeric
inventories: their records therefore have `value: null` and `record_scope` is
`violations_only`. Native diagnostic text is retained as provenance, but Alphus
does not extract a numeric score from it.

Lizard function records exclude its `*global*` pseudo-function and do not use
file or class aggregates. The API adapter uses the parser's function and
method-level records, preserving a path-qualified long name and source line.
Ruff and ESLint keep separate closure and method diagnostics; ESLint's rule may
also report class field initializers and static blocks as its own implicit
function units. Those records retain the native kind in their identity rather
than becoming a class aggregate. Duplicate `(file, identity, line, column)`
records are collapsed deterministically.

## Backend semantics and limits

These backends share an inclusive maximum (`value > maximum` fails), not a
promise that they count every construct identically:

| Language | Backend | Gate or count method | Variant and limits |
| --- | --- | --- | --- |
| Python | Ruff C901 | Native McCabe threshold gate | Passing scores are unavailable; parser errors fail. |
| C/C++ | Lizard API | Numeric function records | `standard` is default; `modified` changes switch counting. |
| JavaScript | ESLint `complexity` | Native threshold gate | Ignores project rules and source comments. |

ESLint runs with `--no-config-lookup --no-inline-config`, so project settings
and source comments cannot change the configured complexity limit or enable
unrelated rules.

Ruff C901 is derived from McCabe complexity. ESLint's classic and modified
variants have different switch, optional-chain, and default-initializer
behavior. Lizard's C/C++ parser can analyze without a compilation database, but
its partial parser can misread complex templates or macro-dependent code.
These limitations are included in plan and report output. Cognitive complexity
and NPath are different metrics and are not accepted as backend substitutions.

The adapter pins an exact PEP 440 version and rejects a different runtime
version. Ruff and ESLint JSON are parsed only for their version-pinned native
diagnostic shapes; unknown rule codes, message formats, or parse diagnostics
fail closed. Lizard is called through its Python API rather than its human
reporting CLI. Missing executables, API failures, malformed output, timeout,
and incomplete file coverage produce operational failures, never a zero score.
The Lizard worker receives the deterministic selected-path list as a UTF-8 JSON
manifest on stdin, so the operating-system command line stays fixed as the
inventory grows. Its limit defaults to 64 MiB and can be set in
`[checks.cyclomatic_complexity]` with `lizard_manifest_max_bytes` (from 1 byte
through 256 MiB). The worker receives this value through `--manifest-max-bytes`;
an oversized or malformed request is an operational failure. The manifest
contains paths only, not source text.

## Fixture and upgrade policy

Golden fixtures in [`tests/fixtures/cyclomatic`](../tests/fixtures/cyclomatic/)
pin the expected native result shapes for Ruff 0.16.1, ESLint 10.13.0, and
Lizard 1.24.2. The adjacent source examples exercise branches, loops, exception
paths, nesting, boolean expressions, ternaries, switch/match, Python
comprehensions and assertions, and JavaScript optional chains and defaults.
Lizard fixtures separately cover its standard and modified switch behavior.

When upgrading a backend, review and update its output fixtures and construct
coverage, then compare the new baseline against the old tool and variant before
changing a consumer limit. Do not assert score equality across Ruff, Lizard, or
ESLint; record any intentional baseline change with its backend, version,
variant, and analyzed-file scope. Adding this optional rule does not change the
project's existing command recipes or hosted CI triggers.

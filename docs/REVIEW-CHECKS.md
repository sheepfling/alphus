# Python review checks

These bounded source checks emit structured **warning** findings. They prompt a
review of intent; they do not prove numeric correctness, test quality, or the
absence of side effects. Existing policies remain valid without their optional
sections. Ruff, Pyright, pytest, mdrepo, and rumdl retain their own checks.

Alphus applies all five scanners to its real source/test inventory through the
`review` profile and includes them in `check` with a warning failure threshold.
Build/install the wheel using [the self-check guide](SELF-CHECK.md), then
invoke the installed command from the temporary directory:

```sh
"$work/venv/bin/alphus" --root "$repo" \
  --config "$repo/quality-gates.toml" --run --profile review
```

Other consumers retain the default error threshold unless they explicitly set
`orchestration.failure_threshold = "warning"` or a rule step's `severity`.
Native command failures still fail.

## Numeric literals

Selector: `numeric-literals`. IDs: `numeric-literals.inline-constant` and
`numeric-literals.inline-conversion`.

The built-in catalog recognizes these exact values in binary or augmented
arithmetic: pi (`3.14`, `3.14159`, `3.141592653589793`), e (`2.71828`,
`2.718281828459045`), and tau (`6.28318`, `6.283185307179586`). A coincidental
price or coefficient can match; the warning asks whether a named constant is
appropriate. Matching uses no proximity tolerance or dimensional inference.
Direct uppercase module assignments of numeric literals and assertion
expectations are left alone.
Class constants, local uppercase assignments, and assignments under conditionals
are not classified as module constant declarations.

Scientific constants, including values published by SciPy, belong in that
consumer catalog with units and provenance. Alphus matches the configured
numeric literals without importing SciPy or assuming that a nearby number has
the same physical meaning.

Physical constants and unit factors require an explicit consumer catalog:

```toml
[checks.numeric_literals]
extensions = [".py"]
exclude = []
math_constants = true

[[checks.numeric_literals.constants]]
name = "project gravity approximation"
values = [9.81]
replacement = "a named constant with documented units and provenance"

[[checks.numeric_literals.constants]]
name = "inch to centimeter factor"
kind = "conversion"
values = [2.54]
replacement = "a named, tested unit conversion"
name_tokens = ["inch", "inches"]
```

Catalog values must be finite and unique within an entry; entry names must be
unique. Set `math_constants = false` to supply a fully consumer-owned catalog.
Conversion entries apply only to multiplication/division, including `*=` and
`/=`. Optional tokens match identifiers or snake/camel case words in the
arithmetic expression and nearest function name. Ordinary assignment output
targets and unrelated local variables do not supply unit context; an augmented
target is an arithmetic operand. Ordinary `*1000`, `9.81`,
ratios, scientific literals, and offset conversions have no inferred unit
meaning. Evaluating formulas to infer units or derive factors, external constant
authorities, and dimensional correctness remain outside this checker.

## Test quality

Selector: `test-quality`. IDs: `test-quality.large-prose-assertion` and
`test-quality.ephemeral-plan-dependency`.

```toml
[checks.test_quality]
extensions = [".py"]
exclude = []
test_paths = ["tests/**", "**/test_*.py", "test_*.py", "**/*_test.py"]
large_prose_min_chars = 300
large_prose_min_words = 50
# Declare only documents that this consumer considers transient inputs.
ephemeral_document_patterns = ["work-notes/sessions/**"]
```

The prose check inspects exact `==` assertions in `test_` functions/methods when
a direct string or a simple static variable reaches both thresholds. Known
module constants are supported; local rebinding or parameters shadow them.
Python source fixtures and JSON objects/arrays are recognized and skipped.
Compact diagnostic and field checks below the thresholds, and substring
assertions, pass.
An intentional large narrative contract still produces an advisory finding.
Dynamic text, snapshot frameworks, unittest assertion methods, and semantic
natural-language judgments are not analyzed.

The document check requires an actual statically recognized read, `open` in a
read mode, or a Path `exists`/`is_file`/`stat` operation matching a configured
pattern. It follows literal Path joins, simple aliases, and some `__file__`
parent paths without opening the referenced document. A word such as "plan"
or a string containing a path is insufficient. For this document subcheck,
stable README/schema/planning format contracts pass unless their paths are
explicitly declared transient. Prose assertions
are evaluated independently.
Pytest `tmp_path`/`tmpdir` inputs and files created earlier in the same test are
recognized as fixtures. Helper-built paths, external fixture setup, indirect
reads, and general interprocedural dependencies are unresolved.

Alphus sets `ephemeral_document_patterns = ["docs/**"]` for its own tests.
This makes a direct read of repository documentation an enforced finding in
the self `check` profile; a test-created fixture or temporary path remains
allowed. Consumers select their own document folders. This is not a global
file exclusion.

## Input contracts

Selector: `input-contracts`. IDs: `input-contracts.argument-mutation` and
`input-contracts.read-only-interface`.

```toml
[checks.input_contracts]
extensions = [".py"]
exclude = []
report_mutation = true
suggest_read_only = true
```

For recognized annotated collection parameters, the scanner follows direct
uses and simple local aliases. It reports item writes/deletions, known mutator
calls, and augmented assignment to a known mutable parameter. Rebinding a name,
mutating a slice copy, or augmenting an unknown scalar value is not proof of
caller mutation. A nested mutator call can produce a reachable-value warning.
These are observations of mutation syntax, not a proof of what an arbitrary
method does at runtime.

A concrete list used only for one visible traversal can receive an `Iterable[T]`
suggestion. Indexing, length, or repeated traversals require `Sequence[T]` in
this conservative guidance. `Iterable` may be a one-shot iterator; it does not
promise indexing, length, or repeated traversal. Dictionary and set reads can
suggest `Mapping[K, V]` and `AbstractSet[T]`. Unknown helpers, escapes, unsupported
methods, and uncertain aliases suppress read-only advice. List-specific methods
such as `sort` do not receive an automatic `MutableSequence` replacement.
For `bytes`, `bytearray`, and `memoryview`, the rule records visible writes to
mutable buffers but does not suggest replacing one with another: `bytes` is
immutable, while a `memoryview` may expose a writable underlying buffer.

The existing `python-style.concrete_inputs` annotation convention stays at its
configured severity, independently of these optional warnings. Its imported
`typing.List as L` and `typing.Dict as D` aliases are now recognized. Prefer a
typed `MutableSequence[T]` or `MutableMapping[K, V]` where that interface fits
intentional mutation; mutation alone does not justify `Any`. The separate
`python-style.opaque_mappings` policy still requires approved boundary paths
and a reason for unknown mapping values.

Read-only `Mapping`/`Sequence` interfaces and frozen Pydantic models do not
provide deep runtime immutability. Another alias can mutate backing data, and
values reached through a read-only collection may themselves be mutable.

The analysis does not evaluate custom type aliases, variadic element
annotations, helper bodies, or general interprocedural effects. Deferred
functions/classes/lambdas and unmodelled try/match paths make affected input
uses uncertain; writes inside those regions may be missed. Loop-element
aliases are not tracked as caller-reachable values. It does not prove that an
unreported parameter is immutable or free of side effects, and it makes no
automatic source changes.

## Pydantic practices

Selector: `pydantic-practices`. IDs: `pydantic-practices.dump-revalidation` and
`pydantic-practices.implicit-mutability`.

```toml
[checks.pydantic_practices]
extensions = [".py"]
exclude = []
report_dump_revalidation = true
require_explicit_frozen = false
```

The dump/revalidation check follows direct local assignments and simple aliases
inside each function. It warns when a `model_dump` or `model_dump_json` result
then reaches a `model_validate`, `model_validate_json`, `validate_python`, or
`validate_json` call. A second validation can be intentional at a trust
boundary; review the call rather than deleting it automatically. The scanner
does not prove receiver types or control-flow reachability.

The optional mutability check recognizes direct `pydantic.BaseModel` subclasses
and their locally declared children. It asks each to declare a literal
`frozen=True` or `frozen=False` through `ConfigDict`, a literal `model_config`
dictionary, or a class keyword. This is a consumer convention, not a Pydantic
requirement. Imported parent classes and computed configuration are unresolved.

## FastAPI and Starlette practices

Selector: `fastapi-practices`. IDs: `fastapi-practices.literal-status` and
`fastapi-practices.literal-error-code`.

```toml
[checks.fastapi_practices]
extensions = [".py"]
exclude = []
report_literal_status = true
check_http_exception_detail_codes = true

[[checks.fastapi_practices.error_code_calls]]
call = "project.api.errors.Problem"
position = 1

[[checks.fastapi_practices.error_code_calls]]
call = "project.api.error_contracts.ErrorResponse"
keyword = "code"
```

The status check recognizes imported FastAPI/Starlette HTTP exceptions and
response constructors, plus route decorators on a module-level `FastAPI()` or
`APIRouter()` instance. It suggests a named status constant for literal
integers. FastAPI accepts numeric status codes, so this is a style warning,
not an error in the application. Router factories returned by helpers and
dynamic decorators are not inferred.

Error-code checks activate only for configured, dotted imported call names or,
when enabled, literal `code` values in an HTTP exception's direct `detail`
dictionary. The consumer owns its vocabulary and the rule does not import the
application or assume any particular code registry. Aliased imports resolve
to the configured name; dynamic factories and computed dictionaries do not.

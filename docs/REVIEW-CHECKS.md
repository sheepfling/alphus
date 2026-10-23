# Python review checks

These bounded source checks emit structured **warning** findings. They prompt a
review of intent; they do not prove numeric correctness, test quality, or the
absence of side effects. Existing policies remain valid without their optional
sections. Ruff, Pyright, pytest, mdrepo, and rumdl retain their own checks.

Alphus applies all six scanners to its real source/test inventory through the
`review` profile and includes them in `check` with a warning failure threshold.
Build/install the wheel using [the self-check guide](SELF-CHECK.md), then
invoke the installed command from the temporary directory:

```shell
"$work/venv/bin/alphus" --root "$repo" \
  --config "$repo/quality-gates.toml" --run --profile review
```

Other consumers retain the default error threshold unless they explicitly set
`orchestration.failure_threshold = "warning"` or a rule step's `severity`.
Native command failures still fail.

## Numeric literals

Selector: `numeric-literals`. IDs: `alphus/python/none/style/inline-constant` and
`alphus/python/none/style/inline-conversion`.

The built-in catalog recognizes these exact values in binary or augmented
arithmetic: pi (`3.14`, `3.14159`, `3.141592653589793`), e (`2.71828`,
`2.718281828459045`), and tau (`6.28318`, `6.283185307179586`). A coincidental
price or coefficient can match; the warning asks whether a named constant is
appropriate. Matching uses no proximity tolerance or dimensional inference.
Direct uppercase module assignments of numeric literals and assertion
expectations are left alone.
Class constants, local uppercase assignments, and assignments under conditionals
are not classified as module constant declarations.

Scientific constants and unit factors can use the separate
`scipy-constants` rule below. Consumer-specific factors remain configurable here.

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

The exact catalog matcher in `alphus.gates.review.numeric_catalog` accepts
`NumericUse` records with a value, line, arithmetic operation, and identifier
context. The Python AST adapter in `numeric_engine` produces those records today.
A C, C++, or JavaScript adapter can supply the same records after parsing its
own syntax and use `match_numeric_uses(..., scope=...)` without importing Python
AST nodes. Language adapters must exclude comments, strings, declarations, and
non-arithmetic values according to their own grammar; the shared matcher only
compares normalized evidence against configured catalogs.

## SciPy constants and conversions

Selector: `scipy-constants`. IDs:
`alphus/python/scipy/style/inline-constant` and
`alphus/python/scipy/style/inline-conversion`.

Enable the built-in catalog with one small section:

```toml
[checks.scipy_constants]
extensions = [".py"]
```

The catalog reviews exact arithmetic literals for `speed_of_light`, `Planck`,
`Boltzmann`, and `Avogadro`, plus the `inch`, `foot`, `mile`, `hour`, and
`day` unit factors. It checks each unit factor and its reciprocal. Unit
factors require a related identifier or enclosing function name, such as
`inches` or `meters`. Dividing by a factor also matches; the direction of a
conversion still needs human review. Add consumer-specific entries through
`[[checks.scipy_constants.constants]]` using the same fields as the numeric
catalog. Disable groups with `physical_constants = false`,
`unit_conversions = false`, or `inverse_conversions = false`.

The built-in symbols and units follow the
[SciPy constants reference](https://docs.scipy.org/doc/scipy/reference/constants.html).
Alphus does not import SciPy, compare floating-point values approximately, or
infer physical dimensions. The gate is provisional in Alphus's own `review`
profile, so its findings are visible without blocking the profile.

## Test quality

Selector: `test-quality`. IDs: `alphus/python/none/testing/large-prose-assertion` and
`alphus/python/none/testing/ephemeral-plan-dependency`.

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

Selector: `input-contracts`. IDs: `alphus/python/none/correctness/argument-mutation` and
`alphus/python/none/correctness/read-only-interface-violation`.

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

Selector: `pydantic-practices`. IDs: `alphus/python/pydantic/validation/dump-revalidation`,
`alphus/python/pydantic/correctness/implicit-mutability`,
`alphus/python/pydantic/correctness/deprecated-v1-api`,
`alphus/python/pydantic/validation/unvalidated-construct`,
`alphus/python/pydantic/validation/unvalidated-copy-update`,
`alphus/python/pydantic/correctness/validator-fallthrough`,
`alphus/python/pydantic/style/field-positional-default`, and
`alphus/python/pydantic/metadata/external-schema-documentation`.

```toml
[checks.pydantic_practices]
extensions = [".py"]
exclude = []
report_dump_revalidation = true
require_explicit_frozen = false
report_deprecated_v1_apis = false
report_unvalidated_construct = false
report_unvalidated_copy_update = false
report_validator_fallthrough = false
report_field_positional_default = false
report_external_model_docs = false
external_model_names = []
```

To include one model exposed by another interface, set
`report_external_model_docs = true` and add its class name, for example:

```toml
report_external_model_docs = true
external_model_names = ["PublicRequest"]
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

The five migration and declaration checks are independently opt-in. The v1
check recognizes imported `validator`/`root_validator` decorators, legacy
`Config` classes, and legacy methods on locally declared models or annotated
model parameters. The construct and copy checks cover calls on locally
declared model classes and annotated model parameters; both APIs can be valid
for trusted data. The validator check reports only simple validator bodies
with an implicit path to the end; complex control flow is left unreported.
The Field style check recognizes imported `pydantic.Field` calls with a
positional default and reports informational advice. All checks are source
only and never import consumer modules. Model identity, aliases through
complex control flow, dynamic decorators, and computed values are not
inferred. Straight-line local aliases in functions are followed; ambiguous
rebindings are skipped.

`field-positional-default` is also reported by Flake8-Pydantic as `PYD001`.
If a consumer already enables that plugin, leave the Alphus style flag off to
avoid duplicate diagnostics. Alphus keeps the check optional and does not
require Flake8 or the plugin. Strict Pyright may also report a missing return
for annotated validators; the validator finding is Pydantic-specific and stays
advisory.

`report_external_model_docs` emits informational findings for external models
without a model description or field descriptions. It identifies models used
by locally declared FastAPI routes (route parameter/return annotations and
`response_model`) and their nested local model fields. Add names to
`external_model_names` for models declared in a scanned file whose route or
other external use is in another module or framework. The checker does not
load imported model definitions across files. For a local model, a class
docstring or literal model-level JSON Schema description satisfies the
model check; `Field(description=...)` or field-level
`json_schema_extra={"description": ...}` satisfies a field check. Dynamic
schema customizations are treated as unknown and skipped. This is advisory:
Pydantic uses these descriptions in its
[generated JSON Schema](https://pydantic.dev/docs/validation/latest/concepts/json_schema/),
which FastAPI includes in its
[OpenAPI documentation](https://fastapi.tiangolo.com/tutorial/response-model/).
They are not needed for validation or runtime correctness.

See the [runnable Pydantic consumer example](../examples/consumer/pydantic-practices/README.md)
for a complete opt-in policy, plan command, and JSON findings run.

## FastAPI and Starlette practices

Selector: `fastapi-practices`. IDs: `alphus/python/fastapi/correctness/literal-http-status` and
`alphus/python/fastapi/correctness/literal-error-code`.

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

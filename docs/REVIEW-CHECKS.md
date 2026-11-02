# Python review checks

These bounded source checks emit structured **warning** and **info** findings.
They prompt a review of intent; they do not prove numeric correctness, test
quality, or the absence of side effects. Existing policies remain valid without
their optional sections. Ruff, Pyright, pytest, mdrepo, and rumdl retain their
own checks.

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
arithmetic, bitwise, shift, and matrix multiplication expressions: pi
(`3.14`, `3.14159`, `3.141592653589793`), e (`2.71828`,
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

The built-in catalog reviews exact arithmetic literals for the SI-defined
`speed_of_light`, `Planck`, `Boltzmann`, `Avogadro`, standard gravity,
elementary charge/electron volt, and molar gas constants. It also covers
common SciPy unit factors in the length, time, mass, volume, pressure, area,
and speed families. These include `inch`, `foot`, `yard`, `mile`,
`nautical_mile`; `minute`, `hour`, `day`, `week`, `year`, `Julian_year`;
`gram`, `pound`, `ounce`; `liter`; `atmosphere`, `bar`; `hectare`, `acre`;
and `mph`, `kmh`, `knot`. Each factor and its reciprocal are checked.

Unit factors require a related identifier or enclosing function name, such as
`inches` or `meters`. Multiplication and division both match. The finding
names a SciPy symbol; review the dimensions and direction before replacing
arithmetic. The charge and electron volt share the same numerical value, so
their finding names both alternatives and asks for a unit check. Add
consumer-specific entries through `[[checks.scipy_constants.constants]]` using
the same fields as the numeric catalog. Disable groups with
`physical_constants = false`, `unit_conversions = false`, or
`inverse_conversions = false`.

The built-in symbols and units follow the
[SciPy constants reference](https://docs.scipy.org/doc/scipy/reference/constants.html).
Alphus does not import SciPy, compare floating-point values approximately, or
infer physical dimensions. This rule does not detect composed conversion
formulas, affine temperature conversions such as Celsius to Kelvin, or
SciPy's `lambda2nu`/`nu2lambda` function equivalents. The gate is provisional
in Alphus's own `review` profile, so its findings are visible without
blocking the profile.

## Test quality

Selector: `test-quality`. IDs: `alphus/python/none/testing/large-prose-assertion`,
`alphus/python/none/testing/ephemeral-plan-dependency`, and
`alphus/python/none/testing/shared-oracle`.

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

### Shared-oracle advisory

The shared-oracle check is independently opt-in and disabled by default. It
inspects only files selected by `test_paths` and only calls resolved from
`oracle_production_modules`. This is a conservative source check: it parses
consumer code without importing or executing it. It is not a detector of test
authorship or a proof of correctness.

```toml
[checks.test_quality]
extensions = [".py"]
test_paths = ["tests/**"]
oracle_independence = true
oracle_production_modules = ["my_package"]
oracle_helper_allowlist = ["my_package.test_helpers.reference_value"]

[[checks.test_quality.oracle_exclusions]]
path = "tests/test_compatibility.py"
test_function = "test_public_delegates_to_core"
reason = "This test documents the public wrapper delegation contract."
```

The scanner reports a direct production call used on both sides of a simple
equality assertion, including calls reached through import aliases, callable
aliases, and local result assignments. Its diagnostic includes the assertion
operand spans and the source spans of the shared calls. It says that this
comparison does not supply independent evidence for that calculation; it does
not claim that the test is useless.

`oracle_production_modules` contains dotted Python module prefixes. The helper
allowlist contains exact dotted callable names. Exclusions match one test
function in one exact configured test file and require a one-line reason of at
least 20 characters. A missing production-module scope is a configuration error when
the check is enabled.

Unknown wrappers, dynamic imports, branch-dependent bindings, and unresolved
receivers are skipped. Fixture builders outside the configured production
modules, comparison helpers such as `pytest.approx`, distinct reference
implementations, literal vectors, and ordinary public behavior assertions do
not match. Add a focused, reasoned exclusion for a deliberate delegation or
consistency contract. This scanner does not compare copied arithmetic or
algorithm similarity, inspect exact mock-call sequences, or infer the behavior
inside a wrapper.

For example, comparing `circle_area(3)` with another `circle_area(3)` uses the
same implementation to produce both values. A literal or independently
calculated reference such as `circle_area(3) == 28.274333882308138` supplies a
separate expected value. For mathematical code, prefer hand-worked or authoritative
reference vectors with units, tolerances, and provenance; the scanner cannot
judge whether the vector itself is correct.

### Optional mutation pilot

Use a small, selected function and its focused tests for a first mutation
review. `mutmut` requires `fork` support; its current documentation says
Windows users need WSL. Run it from a clean disposable checkout or worktree,
pin the version used for the review, and do not apply generated mutants to the
source tree.

```toml
[tool.mutmut]
source_paths = ["src/my_package/geometry.py"]
pytest_add_cli_args_test_selection = ["tests/test_geometry.py"]
```

```shell
mutmut run "my_package.geometry.area*"
mutmut browse
```

Keep the pilot to one function, set a short wall-clock budget such as two
minutes, and record any interrupted work as `not-run`. If using mutmut's
per-mutant timeout settings, check the installed version's documentation
first; those settings are version-sensitive. Review outcomes separately:

- `killed`: a focused test failed while the mutant was active.
- `survived`: the tests passed; inspect whether the mutant is equivalent or
  exposes a missing assertion.
- `timeout`: the mutant did not finish within the configured time.
- `error`: the runner or mutated program errored; this is not a test kill.
- `not-run`: the mutant was not evaluated, including work left after the
  budget or on an unsupported platform.

A surviving mutant may be equivalent, and a high kill rate does not prove
independent validation. Unsupported platforms and incomplete runs are not
success results.

### Property and metamorphic tests

Hypothesis is an optional native test dependency, not a second Alphus
generator. Choose strategies from the input domain and write properties only
for invariants justified by the API or mathematics:

```python
from hypothesis import given, strategies as st


@given(st.integers(), st.integers())
def test_addition_is_commutative(left: int, right: int) -> None:
    assert add(left, right) == add(right, left)
```

This property alone would accept an implementation that always returns zero.
Add hand-worked or authoritative vectors, such as `add(1, 2) == 3`, when they
are supported by an independent source. A round trip or inverse pair can share
the same defect. Record vector provenance, units, and tolerances where
relevant. Use metamorphic relations only when the expected relationship
between transformed inputs and outputs has an independent justification.

See the [Hypothesis quickstart](https://hypothesis.readthedocs.io/en/latest/quickstart.html)
and [mutmut documentation](https://mutmut.readthedocs.io/en/latest/) for their
native setup and command details.

## Input contracts

Selector: `input-contracts`. IDs:
`alphus/python/none/correctness/argument-mutation` and
`alphus/python/none/correctness/read-only-interface-violation`.

```toml
[checks.input_contracts]
extensions = [".py"]
exclude = []
report_mutation = true
suggest_read_only = true
sequence_narrowing_paths = []
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

`sequence_narrowing_paths` opts selected files into the same advisory for an
already abstract `Sequence` or `Iterable` interface. It defaults to empty to
avoid broadening findings across unrelated code. Alphus scopes it to the
positional-interface analyzer so its own quality profile checks that a
single-pass AST input remains typed as `Iterable`.

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
`alphus/python/pydantic/metadata/external-schema-documentation`,
`alphus/python/pydantic/validation/custom-init`, and
`alphus/python/pydantic/validation/public-unconstrained-any`.

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
report_custom_init = false
report_unconstrained_any = false
public_model_paths = []
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
other external use is in another module or framework. A configured name also
selects a declared class that inherits an imported custom Pydantic base, which
the single-file scan cannot resolve. The checker does not load imported model
definitions across files. Alphus enables this check for its public file and
line-limit policy models because their JSON Schema is a configuration
interface. For a local model, a class
docstring or literal model-level JSON Schema description satisfies the
model check; `Field(description=...)` or field-level
`json_schema_extra={"description": ...}` satisfies a field check. Dynamic
schema customizations are treated as unknown and skipped. This is advisory:
Pydantic uses these descriptions in its
[generated JSON Schema](https://pydantic.dev/docs/validation/latest/concepts/json_schema/),
which FastAPI includes in its
[OpenAPI documentation](https://fastapi.tiangolo.com/tutorial/response-model/).
They are not needed for validation or runtime correctness.

`report_custom_init` adds informational review findings for custom `__init__`
methods on locally recognized Pydantic models. Prefer field/model validators or
`model_post_init` for model behavior. A custom initializer can be intentional,
so this rule asks for review and does not claim it is incorrect.

`report_unconstrained_any` warns about `Any` fields only in local Pydantic
models found in explicitly selected `public_model_paths`. It recognizes
`typing.Any` and `typing_extensions.Any`, including nested generic annotations
and simple forward-reference strings. It skips private attributes and
`ClassVar`s. Imported models, local type aliases, and runtime-generated schemas
are unresolved; the path selection is the consumer's declaration that these
models form a public data boundary. The finding is advisory and does not require
replacing intentional compatibility fields.

### Native-tool overlap and deferred candidates

Pydantic's [linting guide](https://pydantic.dev/docs/validation/latest/integrations/dev-tools/linting/)
points Flake8 users to Flake8-Pydantic. Its published `PYD001` through `PYD005`
rules cover positional `Field` defaults, unannotated model attributes,
unnecessary `Field(default=...)`, defaults placed inside `Annotated`, and
annotation/name collisions. Alphus already has the opt-in `PYD001` equivalent;
the other declaration rules stay with Flake8-Pydantic and native type/runtime
diagnostics instead of being duplicated here. `PYD010` for
`__pydantic_config__` likewise belongs with TypedDict/type-checker validation.

There is no blanket mutable-default rule: Pydantic deep-copies unhashable model
defaults per instance, and a consumer can still choose `default_factory` as a
style convention. A static gate cannot prove a validator's side effects or that
a `TypeAdapter` is on a hot path, so profile those paths and test side effects
at runtime. Pydantic also intentionally inherits and merges model config;
static checks do not warn on inheritance without a consumer-specific expected
configuration. See Pydantic's guidance on
[field defaults](https://pydantic.dev/docs/validation/latest/concepts/fields/),
[custom model initialization](https://pydantic.dev/docs/validation/latest/concepts/models/),
and [performance](https://pydantic.dev/docs/validation/latest/concepts/performance/).

See the [runnable Pydantic consumer example](../examples/consumer/pydantic-practices/README.md)
for a complete opt-in policy, plan command, and JSON findings run.

## FastAPI and Starlette practices

This opt-in rule supports source advice and, when explicitly configured, route
and generated OpenAPI review. The native Ruff profile and execution limits are
described in the [FastAPI quality guide](FASTAPI-QUALITY.md).

Selector: `fastapi-practices`. Source-only IDs:
`alphus/python/fastapi/correctness/literal-http-status` and
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

To also inspect registered routes and OpenAPI, set an explicit application
target. For example, `application = "my_api.main:app"` with
`application_python_paths = ["src"]` imports the consumer module and calls
`app.openapi()`; it does not start lifespan or send requests. Configure
`exclude_route_paths`, `required_route_metadata`,
`require_response_contract`, and `protected_route_paths` to set consumer scope.
Duplicate method/path registrations and missing or duplicate operation IDs are
checked whenever the application is configured. FastAPI remains optional for
Alphus installs, and the application import path must be usable without
production infrastructure. See the guide for diagnostic IDs, baseline setup,
and the limits of documented OpenAPI security versus actual request
authorization.

## Positional interfaces

Selector: `positional-interfaces`. ID:
`alphus/python/none/correctness/confusable-positional-parameters`.

This opt-in pilot reports directly annotated, consecutive positional parameters
with the same builtin primitive type. It defaults to informational severity and
does not infer that any call is wrong. Native parameter-count and call-order
diagnostics remain separate. See the [positional interface guide](POSITIONAL-INTERFACES.md)
for the Python boundaries, native capability matrix, and runnable consumer example.

## SQLAlchemy 2.x practices

Selector: `sqlalchemy-practices`. IDs:
`alphus/python/sqlalchemy/style/legacy-query`,
`alphus/python/sqlalchemy/style/legacy-declarative-base`,
`alphus/python/sqlalchemy/style/legacy-backref`,
`alphus/python/sqlalchemy/correctness/literal-execute`,
`alphus/python/sqlalchemy/architecture/module-session`, and
`alphus/python/sqlalchemy/architecture/repository-commit`.

```toml
[checks.sqlalchemy_practices]
target_sqlalchemy = ">=2.0,<3.0"
extensions = [".py"]
exclude = ["tests/fixtures/**"]
report_legacy_query = true
report_legacy_declarative_base = true
report_backref = true
report_literal_execute = true
report_module_session = false
report_repository_commit = false
repository_paths = []
```

An explicit bounded SQLAlchemy 2.x target is required; Alphus does not infer
the consumer's runtime or dependency version. The supported range starts at
2.0 or later and ends before 3.0. The separate M1b `module-session` advisory is
disabled by default and can be enabled after reviewing its source scope.

The first three rules are modernization advice. `Session.query()` and a
direct `Query(...)` constructor are still supported in SQLAlchemy 2.x; a bare
`Query` import or type annotation is not reported. The
declarative-base rule reports a local `declarative_base()` assignment only
when a locally declared model inherits from that base. The backref rule looks
for a resolved SQLAlchemy `relationship(backref=...)` call. Use typed
`Mapped[...]` relationships with `back_populates` when that is the consumer's
selected convention.

The `literal-execute` rule is a warning for a direct string literal passed to a
resolved `Connection.execute()` or `Session.execute()` call when its trimmed
text starts with a recognized SQL command. Use
`text("SELECT ... WHERE id = :id")` with bound values, or use
`Connection.exec_driver_sql()` when driver-level SQL is deliberate. The
[SQLAlchemy 2.0 migration guide](https://docs.sqlalchemy.org/en/20/changelog/migration_20.html)
describes this execute contract. The
[Connection API guide](https://docs.sqlalchemy.org/en/20/core/connections.html)
covers `exec_driver_sql()`. This rule does not inspect constructed SQL, variable
contents, f-strings, dynamic SQL, leading SQL comments, identifiers, or query
safety. Ruff S608 remains the owner for its separate generic check of
dynamically assembled SQL strings.

The session rules resolve imported `Session` and `AsyncSession` types, simple
local sessionmaker factories, typed session parameters, and connections
created by a locally recognized engine. `module-session` reports a mutable
session instance created at module scope; it allows module-level `Engine`,
`sessionmaker`, and `async_sessionmaker` factories. It does not claim that
every other call to `commit()` is a transaction-boundary defect. To review
commits only in consumer-selected data-access code, enable the rule and scope
it explicitly:

```toml
report_repository_commit = true
repository_paths = ["src/repositories/**", "src/data_access.py"]
```

That advisory reports resolved session and connection `commit()` calls in
those paths so a consumer can compare them with its declared transaction
ownership. A commit may be valid when the repository owns the transaction.
Unknown receivers, untyped local aliases, dynamic imports, computed factories,
and intermodule flows are not inferred. No consumer module is imported, and
the scanner itself does not import SQLAlchemy or connect to a database.

The scanner is advisory and bounded. It does not prove transaction safety,
SQL injection freedom, migration safety, or absence of N+1 queries. Use the
consumer's native Ruff, Pyright, pytest, and Alembic checks alongside it.
For a database-backed consumer, run `alembic upgrade head` and `alembic check`
against a disposable database configured with that consumer's dialect; review
generated revisions manually, including renames, constraints, and backfills.
In pytest, count statements with SQLAlchemy engine events and assert how
counts scale with result size; exercise intended relationship loaders,
`Result.unique()` where joined collection loading requires it, rollback
boundaries, and async session ownership. Those runtime checks need the
consumer's database fixtures and do not belong in Alphus's portable scanner.

See the [synthetic SQLAlchemy consumer example](../examples/consumer/sqlalchemy-practices/README.md)
for an opt-in provisional profile, representative findings, and runnable
plan/report commands.

## Source-family organization review

Selector: `source-families`. This opt-in review groups sibling source files by
filename-token prefixes in the selected Git inventory. A name is split on
underscores, hyphens, periods, and spaces, and at lower/digit-to-uppercase
camel-case boundaries. Tokens are case-folded; standalone numeric tokens are
discarded. The minimum prefix length counts token characters after separators
are omitted. A candidate prefix must be a proper token prefix and cover at least
`min_family_files` logical units. Files in different directories are never
grouped. When prefixes nest, each member is assigned to its deepest qualifying
prefix so reports do not repeat the same members.

Python, C, C++, JavaScript, and TypeScript extensions are recognized. Matching
C/C++ header and implementation suffixes with the same stem in one directory
count as one logical unit; other same-stem files with different extensions
remain separate units. Findings retain physical file counts. By default `.h` is
labeled `C/C++`; consumers can relabel suffixes with `language_overrides`, or
use ordered `path_language_overrides` when a suffix is ambiguous in particular
directories. The last matching path override wins and path overrides take
precedence over suffix overrides.

The default heuristic has no dependency or history evidence. Uppercase acronym
runs are not split into separate words, and files outside the configured
extensions or supplied inventory are invisible to it. Names that do not share
a meaningful token prefix are not detected. These are limits of the lexical
stage, not evidence that a family is cohesive.

```toml
[checks.source_families]
extensions = [".py", ".c", ".h", ".cpp", ".hpp", ".js", ".ts"]
include = ["src/**"]
exclude = ["src/vendor/**", "src/generated/**"]
min_family_files = 6
min_prefix_characters = 4
max_files = 20000
max_findings = 100
max_reported_members = 40
language_overrides = [[".h", "C++"]]
path_language_overrides = [["src/legacy_c/**", "C"]]
file_length_limits = [[".py", 500], [".cpp", 800]]
# Optional: direct Python import evidence for selected .py files under `src`.
python_import_evidence = true
python_module_roots = ["src"]
max_import_edges = 12
max_import_analysis_bytes = 8388608
```

The first slice is lexical-only and low-confidence. A shared prefix selects a
review candidate; it does not establish responsibility, coupling, public
surface, or a need to move files. Each finding reports the family key, selected
sibling proportion, language counts, physical-line range and distribution,
per-member line counts, and applicable configured file limits. Member and
distribution evidence are capped, and truncation is stated in the finding. The
configured thresholds, extensions, scope, exclusions, and language overrides
are included so reviewers can see the effective settings. The scan streams line
counts and never imports or executes consumer code. Selected-source processing,
per-finding evidence, and total-finding output are bounded; incomplete scans
produce explicit warnings instead of implying a complete clean result. The
optional Python import pass is disabled by default and requires explicit
`python_module_roots`; it parses only selected `.py` files, reports uniquely
resolved direct `import` and `from ... import ...` module edges, and bounds
file reads, bytes per family, and displayed edges. Unresolved, ambiguous,
relative-import forms it cannot resolve, parse failures, and files outside the
selected inventory are not treated as absent dependencies. It does not follow
dynamic imports, aliases/re-exports, type-checker resolution, or imports in
other languages. These edges are partial dependency evidence and do not prove
shared responsibility, coupling strength, or a public contract. Public API and
history evidence remain unassessed.

A typical finding starts: `src/service: Family gateway_*: 12 logical units
across 12 physical files; 12 of 20 selected sibling source files (60%);
language mix Python=12; physical lines 38–190 (12 counted; distribution: 1
file(s) at 38 lines, ...); configured file limits .py≤500 lines. lexical-only,
low-confidence review candidate.` It also lists bounded member evidence and
states that coupling, imports, responsibility, and public surface were not
assessed.

Use `include`, `exclude`, and `extensions` to scope intentional generated,
vendor, schema-output, fixture, compatibility, test, public-reexport, platform,
or interface families. Keep a short reason beside each consumer exclusion in
the TOML policy so the suppression remains reviewable. Broad names and large
families can still be legitimate; treat a finding as a prompt to inspect actual
responsibilities and public contracts. Preserve established import/include/
export paths before changing a layout. File-length limits remain an independent
hygiene control: splitting files below a limit does not demonstrate improved
cohesion. Dependency, responsibility, public-surface, and history analysis are
not part of this first slice. Fewer files, renamed prefixes, or a new directory
do not by themselves demonstrate better boundaries.

# Python review checks

This folder groups source-review guidance. This page covers the Python review
profile and its selectors. The [semantic patchwork guide](semantic-patchwork/README.md)
documents that advisory family; its [calibration record](semantic-patchwork/CALIBRATION.md)
holds pinned-source observations and their limits.

These bounded source checks emit structured **warning** and **info** findings.
They prompt a review of intent; they do not prove numeric correctness, test
quality, or the absence of side effects. Existing policies remain valid without
their optional sections. Ruff, Pyright, pytest, mdrepo, and rumdl retain their
own checks.

Alphus applies all six scanners to its real source/test inventory through the
`review` profile and includes them in `check` with a warning failure threshold.
Build/install the wheel using [the self-check guide](../SELF-CHECK.md), then
invoke the installed command from the temporary directory:

```shell
"$work/venv/bin/alphus" --root "$repo" \
  --config "$repo/quality-gates.toml" --run --profile review
```

Other consumers retain the default error threshold unless they explicitly set
`orchestration.failure_threshold = "warning"` or a rule step's `severity`.
Native command failures still fail.

The opt-in public-constant inventory follows selected in-repository absolute
and relative imports, simple module-qualified references, and literal
module-level `__all__` exports. Dynamic `__all__`, module `__getattr__`, and
star imports make the module's exported surface unknown, so the inventory
suppresses unused-constant advice for that module. References from consumers
outside the selected inventory cannot be proven; treat any remaining result as
review guidance, not authorization to rename or remove an API.

The local-import review recognizes direct and aliased `TYPE_CHECKING` guards.
It also reports imports inside functions, including optional-dependency loads
and imports used to avoid a dependency cycle. This is source classification
only: it does not establish that a cycle exists, that an optional dependency is
packaged incorrectly, or that moving an import is safe. Preserve and review
lazy boundaries in their application context.

The opt-in `python-style.semantic_result_paths` check limits scanning to chosen
files; a file selection alone does not prove that every callable in the file
is public. Pair it with exact, fully qualified `semantic_result_apis` entries
such as `my_package.api.load_pair` or `my_package.api.Factory.create` to declare
the public contracts under review. Private names, methods on private classes,
unselected callables, homogeneous variadic tuples, named records, and
conventional coordinate/range or wire conversion APIs are accepted.
`typing.Tuple` and its imported aliases are followed in nested result
annotations. The rule uses configured symbol identity and local syntax only:
it cannot resolve arbitrary imported type aliases or determine
external/dynamic consumers. Give wire and compatibility contracts explicit
names, and review each finding; the check never rewrites APIs or callers.

For example, a consumer can select the source inventory and declare only the
public callable whose result contract is under review:

```toml
[checks.python_style]
semantic_result_paths = ["src/my_package/api.py"]
semantic_result_apis = ["my_package.api.load_pair"]
```

## Third-party typing stubs

Selector: `typing-stub-suggestions`. This opt-in informational rule reads
explicit import/distribution mappings and PEP 621 dependency groups. It checks
the installed runtime version against configured bounds and skips packages
whose installed distribution includes `py.typed` or `.pyi` files. See the
[typing stub suggestions guide](../TYPING-STUB-SUGGESTIONS.md) for configuration,
examples, and the limits of its static import analysis.

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

## Repeated numeric limits

Selector: `repeated-numeric-limits`. ID:
`alphus/python/none/maintainability/repeated-numeric-limit`.

This opt-in review-only rule compares explicit numeric literals in `if` and
conditional-expression guards across selected Python paths. A consumer must
select `source_paths` and declare named roles with exact boundary identifiers;
only `<`, `<=`, `>`, and `>=` comparisons against those names (or `len(name)`)
can match. Reversed operands are normalized, while opposite directions and
strict/inclusive bounds remain separate. Attribute expressions are ignored to
avoid conflating receivers such as `tree.node_count` and `graph.node_count`.
Values below 2, booleans, equality/membership/identity comparisons, loop bounds,
assertions, test paths, generated paths, and references to named constants are
ignored. Findings report every matching file and line,
the literal, declared role, and uncertainty. They do not suggest or perform
constant extraction.

```toml
[checks.repeated_numeric_limits]
extensions = [".py"]
source_paths = ["src/analysis/**"]
exclude = ["src/analysis/experimental/**"]
severity = "info"

[[checks.repeated_numeric_limits.roles]]
name = "AST traversal ceiling"
identifiers = ["node_count", "ast_nodes"]
```

Evaluate Ruff's maintained
[`PLR2004` (`magic-value-comparison`)](https://docs.astral.sh/ruff/rules/magic-value-comparison/)
first for unnamed comparison values in selected Python files. It identifies
individual magic-value comparisons and common scalar exemptions; it does not
establish that equal values across files implement one policy. This rule groups
only matches with explicitly declared roles and remains an advisory.

The initial calibration uses synthetic cases: 1/1 positive case for an equal
cap at the same declared boundary (including reversed comparison operands) and
6/6 negative categories for independent roles, common scalar values and loop
bounds, named constants/unselected paths, test/generated files, unsupported or
opposite-direction comparisons, and distinct attribute receivers. No production
repository sample has been scored, so real-world precision is unknown and
enforcement is unsupported. The AST check
does not follow aliases, assignments, imported constants, arbitrary call
expressions, dynamic configuration, nested boolean meaning, or equivalent
thresholds written with different numeric values. It also cannot prove that
consumer-declared names refer to the same semantic boundary; review each
finding. It is distinct from `numeric-literals` arithmetic constants,
`manual-matrix-kernels` numerical reuse, and native cyclomatic metrics.

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

## Declared source-to-test coverage

The separate, opt-in `source-test-coverage` rule checks only the source/test
relationships a consumer declares and reports unknown when those declarations
or execution evidence are unavailable. It never matches basenames or infers
pytest-style conventions. See the [coverage-contract guide](SOURCE-TEST-COVERAGE.md)
for the evidence format, status meanings, and a runnable example. This audit is
separate from the test-content and oracle-independence checks below.

## Test layout

Selector: `test-layout`. Configure source package roots and their corresponding
test roots. Conventional `test_*.py` and `*_test.py` modules should live below
the test directory that mirrors their source package. A test for a source
module at the package root can remain at the test root. Cross-module tests
belong below a configured integration root, which defaults to `integration`.
Global `conftest.py` files and package `__init__.py` files are support files and
are not treated as test modules.

The checker reports a missing or unsafe configured root, test modules placed
outside the matching source package directory, root-level tests with no
matching source module, and test directories that do not exist in the source
package layout. It detects both direct module names and flattened nested names
such as `test_dis_receiver.py`, which should live under `tests/dis/`.

This is a layout check, not a source-to-test coverage claim. It does not infer
which functions a test exercises. Use
[source/test coverage contracts](SOURCE-TEST-COVERAGE.md) when a consumer needs
explicit, revision-matched execution evidence.

See [the test-layout guide](TEST-LAYOUT.md) and the
[consumer policy example](../../examples/consumer/test-layout/quality-gates.toml).

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
least 20 characters. A missing production-module scope is a configuration
error when the check is enabled.

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

The opt-in `input-contracts` rule can review selected internal interfaces for
a configured domain type unioned with `Mapping[str, JsonValue]` or
`dict[str, JsonValue]`, including supported `typing_extensions` equivalents.
Set `domain_mapping_types` to consumer-known, fully
qualified model names and select only relevant internal files in the top-level
inventory. A finding requires a literal string-key read from the union
parameter and reports the parameter and read locations. A direct assigned
`model_validate` or `parse_obj` result used later in the function counts as
local normalization evidence. See
[`examples/consumer/domain-mapping-review.toml`](../../examples/consumer/domain-mapping-review.toml).

For adjacent signatures that cannot be selected by a union annotation, a
consumer may add exact `domain_mapping_contracts` selectors. Each selector
names one repository-relative Python path, lexical function name (including
enclosing classes), parameter, and expected fully qualified domain type. A
selected `Mapping[str, JsonValue]`/`dict[str, JsonValue]` parameter is reviewed
when its function directly reads a literal string key or passes that exact
parameter to a unique module-level helper whose corresponding parameter has a
direct literal-key read. One straight-line assignment alias in the selected
function or helper is followed when it is a simple name-to-name assignment;
the finding names the pass-through call and helper read. This is one-hop
evidence only: branch-dependent aliases, imported/class helpers, duplicate
helper names, and deeper flows remain unresolved. A selected
`object` parameter is reviewed only when the function directly reads one of its
attributes. This narrow setting is useful when the consumer has independently
declared that the input represents a particular domain model; it does not infer
that contract from parameter names or access syntax. Generic mapping shapes
with other key/value types, other broad annotations, dynamic keys, nested
attributes, arbitrary helper calls, and unselected functions remain outside
the scan.
Use exact `domain_mapping_exceptions` selectors to document a reviewed adapter
or compatibility boundary. Each exception requires the path, function,
parameter, expected domain type, and a non-empty reason; it suppresses only
that exact selected parameter when its domain type is unambiguous and matches.
For union annotations, an exception does not suppress a finding if the input
also accepts another configured domain type. A stale or ambiguous exception
leaves the review finding visible.

This is a review candidate, not proof that validation is absent or that the
interface is wrong. The scanner does not resolve model-like names
automatically or infer behavior through arbitrary aliases, casts, helpers, or
branch-specific normalization. The single direct-helper slice is not recursive
and does not establish whether helper-local validation is sufficient.
Unsupported flow should be reviewed manually; the advisory stays opt-in and
informational.
Direct attribute access on `object` can be intentional duck typing or a
compatibility boundary, so a finding asks for review rather than asserting that
the interface must become a concrete model. A configured contract does not
prove a runtime validation defect, a caller's actual values, or that a typed
model is the only suitable interface.

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

### Manual schema validation review

`manual_schema_validation_boundaries` independently opts exact admission
functions/parameters into `manual-schema-validation` review. A finding requires
locally visible fixed string-key checks plus repeated scalar type or numeric
range guards that raise or return. It groups the boundary, guard locations,
recognized constraints, and an optional consumer-declared authoritative schema
into one informational finding:

```toml
[[checks.input_contracts.manual_schema_validation_boundaries]]
path = "src/app/decode.py"
function = "load_options"
parameter = "payload"
authoritative_schema = "app.models.Options"
```

The selector declares a review scope; it does not assert that manual checks are
wrong. A result from a recognized `model_validate`, `validate_python`, or
`parse_obj` call suppresses the candidate only when it is returned or its
assigned result is used later. Consumers can name an equivalent validator or
record a substantive one-line justification for a deliberate custom protocol
contract. A single guard, generic key/value walker, open extension mapping, or
unselected function is not a candidate.

The check does not import consumer schemas or execute validators. Aliases,
shadowing, arbitrary helpers, imported schema identity, and branch completeness
remain unknown; helper locations and this uncertainty are included in the
finding where visible. The rule does not decide required-versus-nullable fields,
coercion, bool/int policy, finite numbers, duplicate keys, serialization, or
wire compatibility. Keep it advisory and compare each result with an
independent boundary contract before remediation.

For remediation review, lower finding counts alone are not completion evidence.
A cast, copied recursive `JsonValue` alias, pattern matching used only to evade
the warning, widening a domain parameter to model-or-mapping, moving the same
guards into an opaque helper, or adding a second handwritten validator without
showing why the existing schema is inadequate does not establish safer
validation. `JsonValue` describes generic JSON shape; a `TypedDict` annotation
alone performs no runtime check. Any separately authorized boundary migration
needs behavioral tests for required versus explicit-null fields, unknown keys,
bool/int handling, finite values, coercion, nested shapes, discriminators,
defaults, errors, and wire compatibility.

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
`alphus/python/pydantic/validation/public-unconstrained-any`, and
`alphus/python/pydantic/style/static-mutable-default-factory`.

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
prefer_static_mutable_defaults = false
report_external_model_docs = false
external_model_names = []
report_custom_init = false
report_unconstrained_any = false
public_model_paths = []
```

`prefer_static_mutable_defaults` is an opt-in, informational style preference
for Pydantic fields that use exactly `Field(default_factory=list)` or
`Field(default_factory=dict)`. Pydantic copies unhashable literal defaults for
each model instance, so those factories are not needed solely to prevent
instances from sharing a list or dictionary. The check excludes dataclasses,
dynamic factories, and factories that consume validated data. It does not
rewrite code; retain factories when they express computed or contextual values.

For a known UTC-only persistence boundary, `utc_persistence_contracts` can
select an exact source function and call argument:

```toml
[[checks.pydantic_practices.utc_persistence_contracts]]
path = "src/storage.py"
function = "save_created_at"
call = "writer.save"
keyword = "created_at"
```

This opt-in advisory reports a known non-UTC `datetime.now(ZoneInfo("..."))`
capture passed to that exact keyword unless the same captured value is
explicitly normalized with `astimezone(timezone.utc)` or a recognized zero-
offset `ZoneInfo` alias. Calling `astimezone()` without an explicit target,
converting to another named zone, or using `replace(tzinfo=...)` does not prove
UTC normalization. Unknown zones, aliases through variables, validators and
cross-function flow remain unreported. It does not establish consumer meaning
from a field name, and it does not replace Ruff DTZ rules for naive clock
captures.

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

There is no blanket mutable-default correctness rule: Pydantic deep-copies
unhashable model defaults per instance. The opt-in `prefer_static_mutable_defaults`
flag below is a low-severity style preference for exact built-in list/dict
factories only; it does not require a factory or rewrite fields. A static gate
cannot prove a validator's side effects or that
a `TypeAdapter` is on a hot path, so profile those paths and test side effects
at runtime. Pydantic also intentionally inherits and merges model config;
static checks do not warn on inheritance without a consumer-specific expected
configuration. See Pydantic's guidance on
[field defaults](https://pydantic.dev/docs/validation/latest/concepts/fields/),
[custom model initialization](https://pydantic.dev/docs/validation/latest/concepts/models/),
and [performance](https://pydantic.dev/docs/validation/latest/concepts/performance/).

See the [runnable Pydantic consumer example](../../examples/consumer/pydantic-practices/README.md)
for a complete opt-in policy, plan command, and JSON findings run.

For selected internal functions that declare a domain-model result, a consumer
may add an exact `domain_return_contracts` entry:

```toml
[[checks.pydantic_practices.domain_return_contracts]]
path = "src/domain/summary.py"
function = "build_summary"
model = "app.models.Summary"
```

`model-dump-domain-return` is informational and requires the selected function
to return the same locally resolved model type it accepts as a parameter while
directly returning that parameter's `model_dump()` result. A local Pydantic model
is recognized from its declaration; an imported model must also be named in
`external_model_names` so its identity is consumer-declared. The explicit
selector declares an internal domain-return boundary. Unselected JSON/CSV writers,
external adapters, unresolved aliases, copied dumps, and cross-function flow
are not inferred. Review whether serialization belongs at an I/O boundary; the
finding does not establish that a conversion is unsafe and never recommends
deleting validation or changing wire behavior automatically.

For an explicitly closed action domain, a consumer can opt in to a bounded
review of a selected string parameter:

```toml
[[checks.pydantic_practices.finite_state_contracts]]
path = "src/actions.py"
function = "dispatch"
parameter = "action"
values = ["approve", "reject"]
```

The advisory requires a direct `str` annotation and a complete `if`/`elif`
chain comparing the parameter with exactly the declared values. It suggests a
`Literal`, `Enum`/`StrEnum`, or validated finite type. Typed inputs, partial
chains, parameter rebinding, unselected paths, and values outside the declared
contract are left alone. This policy does not establish that an external
protocol is closed; maintainers must only configure it when they own that
closed-set contract.

## Project-convention coverage and ownership

The checks below are review aids with independent owners. A repository should
select only the paths and contracts it maintains; lack of static evidence is
unknown rather than proof of a defect.

- **Preserve domain models:** Pydantic reports dump/revalidation and selected
  direct domain-return dumps; input-contracts reports configured direct escapes.
  Identity and cross-module flow need a consumer contract.
- **Match collection inputs:** input-contracts follows direct uses and simple
  aliases; mutation and uncertain escapes are preserved.
- **Review flush/fsync/replace:** human review needs output-role and
  write-guarantee contracts. Atomic visibility differs from crash durability;
  no consumer output contract was supplied to scope this rule.
- **Prefer `Annotated` and static defaults:** native tools own declaration
  correctness. The static-default rule is an opt-in preference; assignment-form
  `Field` stays valid.
- **Centralize package configuration:** native packaging tools and consumer
  review. Included requirement files retain declaration locations for
  conflicting exact pins. Cross-manifest authority is not inferred.
- **Match pytest style:** Ruff `PT` rules in the scoped
  [pytest style profile](../PYTEST-STYLE.md). `unittest`, mocks, and migration
  suites remain valid.
- **Centralize business states:** human review with typed `Literal`/`Enum`
  evidence. An opt-in `finite_state_contracts` entry can declare a selected
  function parameter's closed string values; a complete `if`/`elif` decision
  chain over that exact set is an informational candidate when the parameter
  remains a plain `str`. Typed `Literal`/`Enum` inputs, partial chains, rebound
  parameters and unselected or unresolved values are skipped. Repetition alone
  does not prove a finite domain.
- **Keep timezone awareness and UTC distinct:** Ruff `DTZ` covers naive calls.
  Aware types and UTC normalization need boundary contracts.
- **Separate generated output from inputs:** Git inventory covers known build
  artifacts and explicitly declared tracked-output contracts with exact
  provenance exceptions. Untracked files and paths outside a consumer contract
  are ignored; this does not infer static write locations or generator
  behavior.

The runnable [pytest-style consumer profile](../../examples/python/pytest-style.toml)
shows native rule selection. The Pydantic example above shows the separate
domain/model profile. These recipes demonstrate configuration, not sampled
production precision or universal enforcement.

The dependency-lock check reports conflicting exact pins for a normalized
package name when environment markers match, including declarations reached
through included files. Compatible ranges, same-version extras, and distinct
marker scopes remain accepted. It does not infer that independent manifests
are authoritative; that requires an explicit consumer contract.

## Inputs needed for other consumer-specific conventions

The issue's additional triage cases need project contracts before they can be
checked safely. No consumer repository or representative examples were supplied
for these cases, so they remain review guidance and have no production
precision claim:

- Cross-manifest dependency review needs the package root, each maintained or
  generated manifest, and an explicit authority order. Environment-marker
  overlap and dynamic build metadata must remain unknown when unresolved.
- Flush/fsync/replace review needs each selected writer's output role and its
  atomic-visibility or crash-durability requirements.
- Static generated-output write-location review needs declared output/generator
  paths and provenance for versioned fixtures and operator-maintained inputs.
  The Git gate handles only paths already tracked and matching an explicit
  contract; a filesystem path alone cannot distinguish a write from a value.
- Finite-state review needs selected fields/types and their declared closed
  variants. Repeated strings alone do not supply that contract.
- Payload/schema review needs payload paths, the authoritative schema and
  version mapping, and the consumer's validation command. Missing ownership is
  not a successful validation result.
- Action/result review needs selected domain actions, their result models, and
  the renderer boundary. A `print` call alone does not identify a violation.
- Shared-fixture review needs the exact test fixtures and evidence that setup,
  parametrization, scope, and teardown behavior are equivalent.
- Numerical review needs the consumer-declared dtype/shape contract or linear
  system semantics. Without them, array and inverse expressions stay unknown.

## FastAPI and Starlette practices

This opt-in rule supports source advice and, when explicitly configured, route
and generated OpenAPI review. The native Ruff profile and execution limits are
described in the [FastAPI quality guide](../FASTAPI-QUALITY.md).

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
diagnostics remain separate. See the [positional interface guide](../POSITIONAL-INTERFACES.md)
for the Python boundaries, native capability matrix, and runnable consumer example.

## Dynamic Markdown assembly

Selector: `dynamic-markdown`. ID:
`alphus/python/none/maintainability/dynamic-markdown-assembly`.

This opt-in Python advisory looks for dynamic values placed into Markdown
structure in consumer-selected producer files. Configure narrow paths so
ordinary application strings and unrelated templates are not treated as
Markdown output:

```toml
[checks.dynamic_markdown]
extensions = [".py"]
producer_paths = ["src/my_app/markdown/**"]
exclude = []
severity = "warning"
declared_safe_helpers = ["my_app.markdown_cells.escape_table_cell"]

[[checks.dynamic_markdown.exceptions]]
paths = ["src/my_app/markdown/legacy_serializer.py"]
reason = "Reviewed low-level serializer preserves the declared Markdown dialect."
```

Add `dynamic-markdown` as a rule step in a consumer-owned profile to run it.
`producer_paths` is required; the checker never treats punctuation or an
f-string alone as evidence that a file produces Markdown. The optional
`exceptions` entries suppress matching paths and require a review reason.
`exclude` remains available for ordinary path exclusions. A producer path must
also be present in the root `[files]` inventory; this rule does not expand the
repository-wide file scope.

`declared_safe_helpers` is an exact, opt-in project contract for context-specific
value helpers. An entry is recognized only when the selected source imports that
qualified helper and uses it through the imported name; import aliases are
followed, while parameters and local reassignments that shadow the imported name
remain untrusted. Configuring a helper records the consumer's assertion that the
helper handles the relevant Markdown context. Alphus does not inspect or certify
the helper body, and importing a Markdown package alone never suppresses other
manual assembly findings. Dynamic values passed to undeclared or unresolved
helpers remain review candidates when the surrounding Markdown structure is
visible.

The synthetic regression suite separately renders representative table, link,
code-span, and code-fence builders with `markdown-it-py` and inspects their HTML
structure. These fixtures validate the chosen table dialect and builder
examples; they do not certify arbitrary consumer output or imply that a static
finding proves rendered Markdown is malformed.

### Real-generator source checks

At SnakeMD [commit `21256ece8c73edfe13e255218374dda54da3eb51`][snakemd-revision],
the selected [`readme.py`][snakemd-readme] (281 Python lines) is the project's
checked-in README generator. It builds content through `snakemd.Document`
methods and structured `Inline`, `Table`, and `Code` objects. Running the
source advisory from Alphus commit
`7f923bd4b7767a8629c8c256703a5f95aa20e339` with Python 3.11.16 on that file
produced zero findings. This is one accepted-builder example and one zero-
candidate result; it is not a precision estimate or evidence that SnakeMD's
output is safe. The consumer source was not executed and its rendered README
was not parsed in this check. Positive real-generator evidence remains the
mdutils table-builder example recorded in PR #81; these small samples do not
establish broad calibration or justify enforcement.

[snakemd-revision]: https://github.com/TheRenegadeCoder/SnakeMD/tree/21256ece8c73edfe13e255218374dda54da3eb51
[snakemd-readme]: https://github.com/TheRenegadeCoder/SnakeMD/blob/21256ece8c73edfe13e255218374dda54da3eb51/readme.py

```toml
[[orchestration.steps]]
kind = "rule"
name = "Dynamic Markdown review"
rule = "dynamic-markdown"

[[orchestration.profiles]]
name = "markdown-review"
steps = ["Dynamic Markdown review"]
```

Run that consumer-owned profile with `alphus --run --profile markdown-review`.

The first supported patterns are f-strings, string concatenation, literal
`.format()` templates, direct local aliases, and straight-line list
`append`/`join` assembly, including a list initialized before a loop and
appended to with a recognizable one-iteration row pattern. For that loop case,
the analyzer treats the loop body as a representative row; it does not infer
iteration counts or execute the producer. It reports values in pipe-delimited
table rows, common unordered and ordered list items (up to eight leading
spaces), block quotes, simple Markdown link labels or destinations, and
matched backtick spans or fences. List and block-quote matching is skipped
inside recognized fenced code blocks. Findings include the dynamic expression
and observed source construction. They ask for context-specific review, such
as table-cell escaping and row boundaries, list-marker indentation, block
boundaries, or link destination encoding; they do not claim that rendered
output is malformed or prescribe one universal escaping call.

The analyzer does not execute or import consumer modules. It follows local
bindings only when their value remains unambiguous; assignments that differ
across branches are left unresolved. Unknown helpers, interprocedural flow,
computed templates, raw-fragment provenance, and library APIs are not
recognized as safe. Importing a Markdown package does not suppress a separate
manual construction. This first pass does not analyze general block composition
or certify renderer output. Calibrate it against sanitized real generator
examples and independently check representative rendered structure before
considering broader rollout. Prefer a dialect-aware library or tested shared
builder for document production.

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

See the [synthetic SQLAlchemy consumer example](../../examples/consumer/sqlalchemy-practices/README.md)
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
# Optional: literal quoted C/C++ includes resolving inside the selected inventory.
cpp_include_evidence = true
# Optional: parser-backed literal relative JS/TS module references.
javascript_import_evidence = true
max_import_edges = 12
max_public_api_names = 20
max_contract_declarations = 12
# One run-wide Python or C/C++ pass byte budget, shared across all families.
max_import_analysis_bytes = 8388608
# Optional: bounded, read-only co-change evidence for selected family paths.
git_cochange_evidence = true
max_git_history_commits = 100
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
resolved direct `import` and `from ... import ...` module edges, including
incoming references from selected Python files outside each family. Source
reads and AST parses are cached across family reports, under one run-wide
`max_import_analysis_bytes` budget; displayed edges are separately capped.
The import walk remains family-specific, but selected files are not re-read or
re-parsed for each family. Unresolved, ambiguous, above-package-root relative
imports, parse failures, and files outside the selected inventory are not
treated as absent dependencies. It does not follow dynamic imports,
aliases/re-exports, or type-checker resolution.

The optional C/C++ pass is also disabled by default. It indexes literal quoted
includes in selected C/C++ files under one run-wide `max_import_analysis_bytes`
budget, reserving the budget for all retained family members before scanning
selected external files. It reports literal include edges from family members
to selected targets and incoming references from selected external files to
family members, with source lines. Resolution is a relative-path match against
the selected inventory, not compiler resolution: include search paths, macros,
angle-bracket includes, conditional activation, and unselected targets are not
assessed. Read failures or an exhausted shared budget produce incomplete-scan
warnings; missing evidence is not treated as zero references.

JavaScript and TypeScript import evidence is also disabled by default and
requires the optional `alphus[javascript]` extra. Its Tree-sitter parsers
inspect selected `.js`,
`.jsx`, `.mjs`, `.cjs`, `.ts`, and `.tsx` files and report only literal relative
`import`, `export ... from`, dynamic `import()`, and `require()` references
resolving uniquely to selected files (including extensionless exact-file
candidates). Package resolution, TypeScript path aliases, index lookup,
shadowed `require`, conditional activation, and compiler configuration are not
resolved. Parse failures and exhausted byte budgets produce incomplete-scan
warnings; unresolved references are not treated as absent dependencies. Other
language evidence requires its own explicitly enabled analysis. These edges
show partial dependency evidence; they do not prove shared responsibility,
coupling strength, or a public contract. For parsed
Python family members, the optional pass also reports bounded names from a
single direct literal module-level `__all__` assignment. Dynamic, augmented,
or reassigned declarations are reported as unresolved; package-level
re-exports, consumers outside the selected inventory, and names without a
literal `__all__` are not inferred. This is syntax evidence, not a complete
public API or responsibility assessment. The pass also reports bounded,
module-level classes with a
qualified `typing.Protocol` or `typing_extensions.Protocol` base and their
direct method names. It also reports bounded fields for module-level classes
with a qualified `typing.TypedDict` or `typing_extensions.TypedDict` base.
These are explicit contract-shaped syntax only; aliases, ABCs, factory
declarations, other forms, implementations, and actual sharing across consumers
remain unknown. Import edges and declarations do not establish which files
share responsibility. When a selected family member directly imports one of
those Protocol or TypedDict names and references the unshadowed import in an
annotation or class base, the report includes both the importing reference
location and declaration file. Rebinding causes the reference to be omitted.
This is cross-file type-reference syntax, not proof of runtime use, an
established shared contract, or common responsibility. Optional
`git_cochange_evidence`
uses a bounded read-only `git log` query for selected family paths and reports
observed commit IDs and co-changed paths. This is correlation only; it does not
establish causation, ownership, or responsibility. Shallow history, query
failures, pathspec limits, and a full commit window are called out, and no
co-changes are explicitly not evidence of independence. Renames are not
followed, and unrelated/historical path names outside the current family are
not mapped.

Optional `cpp_include_evidence` reports direct literal quoted include
directives only when the normalized path is another selected source file. It
does not use a compile database or resolve angle-bracket/macro includes,
conditional activation, include search paths, or unselected targets. This is
lexical path evidence, not compiler-resolved dependency data. JavaScript and
TypeScript use the optional parser-backed literal relative-reference pass
described above; package resolution, TypeScript aliases, index lookup,
shadowed `require`, conditional activation, and compiler configuration remain
unassessed. Unsupported or unresolved relationships are not evidence of zero
coupling.

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
cohesion. Optional Python and C/C++ evidence supplements the lexical candidate
with bounded source relationships, and optional Git history records correlation
only. Responsibility and public-surface assessment remain incomplete.
JavaScript/TypeScript evidence is optional and limited to the literal relative
references described above; package resolution and other cases remain
unassessed. Fewer files, renamed prefixes, or a new directory do not by
themselves demonstrate better boundaries.

### Exploratory real-project calibration

Read-only GitHub snapshots collected on 2026-11-02 provide a small exploratory
check, not a precision or recall estimate. A path-name screen used the default
family thresholds (`min_family_files=5`, `min_prefix_characters=4`), Python
source paths under each package root, and excluded test-directory segments.
It found no candidate groups in Requests (`src/requests`, 19 files, revision
[`3c7baaa`](https://github.com/psf/requests/commit/3c7baaa05ab4aa49cc819ce3a819d260de19c157)),
Flask (`src/flask`, 24 files, revision
[`49943b5`](https://github.com/pallets/flask/commit/49943b5a94413a530761350f04e896f76e8d620e)),
HTTPX (`httpx`, 23 files, revision
[`b5addb6`](https://github.com/encode/httpx/commit/b5addb64f0161ff6bfe94c124ef76f6a1fba5254)),
or Pydantic (`pydantic`, 54 files, revision
[`b09325b`](https://github.com/pydantic/pydantic/commit/b09325b0a41d9a957df9a530e5c6a7836799df1e)).
These four results are inventory-name screens only: source contents and
semantic evidence were not inspected, so no candidate is not evidence of
cohesion or a missed defect.

The PR-head analyzer was also run on the 35 direct `*.py` files in Matplotlib's
`lib/matplotlib/backends` directory at
[`5a84a6f`](https://github.com/matplotlib/matplotlib/commit/5a84a6f84361b9c94458a85b20c40e8a1ffe55d7),
with the same family thresholds. It emitted one advisory: `backend_*`, 32 of
35 selected siblings (91%), 32 logical units, and 11–2,850 physical lines.
[The guide](https://github.com/matplotlib/matplotlib/blob/5a84a6f/galleries/users_explain/figure/backends.rst)
describes these as intentional output implementations for GUI and file
formats. This is a known legitimate platform/backend family and a false
positive if the lexical candidate is treated as evidence of poor boundaries.
It demonstrates why the result must remain advisory and be reviewed against
the project's purpose.

Enabling Python import evidence on that same 35-file snapshot resolved 50
direct intra-family edges, while 297 imports were unresolved or outside the
selected inventory. The snapshot omitted the rest of Matplotlib's `lib/`
source tree and nested backend directories, so those unresolved imports and
the absence of selected outside consumers cannot establish the full dependency
graph or zero external use. This one curated candidate plus four path-only
no-candidate screens is too small and biased to support an accuracy claim or
stronger enforcement.

## Durable benchmark prose review

Selector: `benchmark-docs`. This opt-in Markdown review finds section-level
candidates when benchmark language appears with a cluster of duration,
throughput, or comparative measurements. It reports a source path and heading
and asks for human review. It does not decide whether a result is stale, wrong,
or unsuitable, and it does not infer that context is missing from nearby prose.
Links to methodology, protocol, reproducibility, or benchmark commands suppress
that section because relevant context may live elsewhere.

The rule scans only Markdown files selected by the consumer's `include` globs.
Use `exclude` for local scope decisions. Historical report directories and
filenames matching `historical_report_patterns` are skipped by default; set the
list to `[]` only when those reports should also be reviewed. Exact
path-and-heading exceptions require a reason of at least twenty characters.
`max_files`, `max_file_bytes`, and `max_findings` bound work and output. If the
file inventory is truncated or a selected file cannot be read, the rule reports
an incomplete-scope status instead of implying that every selected document was
analyzed. A successful scan with no finding means no candidate matched within
the configured, readable scope; it is not a semantic cleanliness claim.

```toml
[checks.benchmark_docs]
include = ["README.md", "docs/performance/**"]
exclude = ["docs/generated/**"]
historical_report_patterns = [
  "**/benchmarks/**",
  "**/benchmark-reports/**",
  "**/*benchmark-report*.md",
]
max_files = 100
max_file_bytes = 1000000
max_findings = 20

[[orchestration.steps]]
kind = "rule"
name = "Durable benchmark prose review"
rule = "benchmark-docs"
rollout = "provisional"
```

Keep a concise workload description and reproducible benchmark command in
current-facing documentation when useful. When detailed, machine-specific
measurements need to be retained, consider a dated report that is explicitly
maintained. The checker never runs benchmarks or asks consumers to check in
machine-specific benchmark JSON. The positive timing, throughput, and speedup
fixtures are synthetic and their values are invented solely to exercise lexical
matches; they are not benchmark evidence. A real negative fixture excerpts the
QuatOps `experiments/README.md` procedure for saving run artifacts and keeping
medians out of durable docs. The checked QuatOps documentation and available
history contained no durable numeric comparison to use as a real positive
calibration example. Tests also cover routine timeout/install waits, software
versions, fenced examples, linked methods, historical report paths, and exact
scoped exceptions. This sample does not measure precision or enforcement
performance; collect multiple human-labeled real positives and negatives before
making those claims.

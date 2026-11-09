Warning: truncated output (original token count: 18279)
Total output lines: 1368

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
[typing stub suggestions guide](TYPING-STUB-SUGGESTIONS.md) for configuration,
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
suggestion. Indexing,…8279 tokens truncated…# SQLAlchemy 2.x practices

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
requires the optional `alphus[javascript]` extra. Its Tree-sitter parsers inspect selected `.js`,
`.jsx`, `.mjs`, `.cjs`, `.ts`, and `.tsx` files and report only literal relative
`import`, `export ... from`, dynamic `import()`, and `require()` references
resolving uniquely to selected files (including extensionless exact-file
candidates). Package resolution, TypeScript path aliases, index lookup,
shadowed `require`, conditional activation, and compiler configuration are not
resolved. Parse failures and exhausted byte budgets produce incomplete-scan
warnings; unresolved references are not treated as absent dependencies. Other
language evidence requires its own explicitly enabled analysis. These edges are partial
dependency evidence and do not prove
shared responsibility, coupling strength, or a public contract. For parsed
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

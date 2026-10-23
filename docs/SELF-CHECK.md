# Self-checking Alphus

The `check` profile validates the package against its own repository policy. It
runs Alphus portable rules, the comment-marker and review rules, TOML syntax, installed-package
import smoke and compatibility-import removal checks, native Ruff lint and
format checks, strict Pyright, and the package tests.
The repository's GitHub Actions quality workflow runs this profile on Python
3.11 through 3.14 for pull requests and main-branch pushes. It checks editable
installation, builds and installs a wheel, then invokes the installed package.
An additional Python 3.11 job runs the profile with every direct runtime and
`python` extra dependency at its declared minimum version.

## Run the installed wheel against this checkout

Use Python 3.11 through 3.14. From anywhere inside the Alphus Git checkout, build a
wheel, install it with
the project's declared development dependencies in a temporary environment,
then run its installed `alphus` command from outside the checkout. The
explicit `--root` and `--config` paths make it inspect this checkout's real
source and policy while importing the installed wheel.

```sh
repo="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/wheels"
python3 -m pip wheel --no-deps --wheel-dir "$work/wheels" "$repo"
python3 -m venv "$work/venv"
wheel="$(find "$work/wheels" -maxdepth 1 -name 'alphus-*.whl' -print -quit)"
"$work/venv/bin/python" -m pip install "$wheel[python]"

(
  cd "$work"
  "$work/venv/bin/alphus" \
    --root "$repo" \
    --config "$repo/quality-gates.toml" \
    --run --profile check
)
```

The `python` extra supplies Pyright, pytest, and Ruff in the same environment as
the installed wheel. Pip also installs the wheel's runtime requirements. The
profile includes Ruff lint, formatting, strict Pyright, and pytest.
Its Ruff lint and format steps also declare file-scoped fix commands. They
are visible through `--fix-plan` and run only through `--apply-fixes` with
named steps; see [fix plans](FIXES.md).

The [runtime-type contract](RUNTIME-TYPES.md) describes typed AST dispatch and
explicit reflection-value annotations. The existing exclusions below remain
unchanged; that correction adds no file exclusions or threshold relaxation.

## Self-profile scope and exclusions

`quality-gates.toml` inventories `src/**/*.py`, `tests/**/*.py`, `README.md`,
`docs/**/*.md`, and all repository TOML and JSON files. The profile retains
the eight original portable rules, the target-audit isolation rule, and Python
lint/package tests, then adds
TOML syntax, Python formatting, strict Pyright, Numeric review, Test review, and Input contract
review. The separate `json` profile is available when JSON documents are
added to this repository. The global
`[files].exclude` is empty.
The package-boundary step also validates console and GUI script entry-point
reference syntax in `pyproject.toml`; it catches an invalid module segment
before an editable installation reaches the build backend.
The package tests load every declared script target and require a callable,
which also catches valid-looking references to missing modules or attributes.
The `Python package imports` command discovers every `.py` file under `src`,
requires regular package membership and initializers, and imports
each module in a fresh interpreter. It removes
`PYTHONPATH` from each child so the CI run checks the installed wheel rather
than importing directly from `src`. This includes `__main__.py`; command
entry modules therefore need a main guard.
The `Python compatibility imports` command rejects forwarding modules unless
they have an [owned, dated removal plan](COMPATIBILITY-IMPORTS.md). Alphus runs
it without a plan so new compatibility wrappers fail immediately.
The `Comment markers` rule rejects `TODO`, `FIXME`, `HACK`, `XXX`, and `XXXX`
in Python and TOML comments. Its policy also supports JavaScript, TypeScript,
C/C++, and Java comment syntax for consumers that select those files. It
ignores string values and reports the comment's file and line. JSON documents
have no comment syntax; the separate JSON syntax step rejects comments there.
The target-audit isolation rule checks that the four files copied into a
Python 3.10 target environment do not import Alphus's Python 3.11 controller
or its Pydantic, Rich, and Typer dependencies.

The only non-empty rule exclusions are:

- **Runtime type usage, `tests/**`:** tests deliberately exercise dynamic and
  broad runtime-type
  cases to verify the rule; this policy is for application code.
- **Runtime type usage, `src/alphus/gates/source/python_style.py`,
  `src/alphus/gates/source/runtime_types.py`, and
  `src/alphus/gates/python/compatibility.py`:** these AST analyzers inspect
  syntax node types, not application runtime values.
- **JSON structure, `tests/**`:** tests include decoder calls in source
  snippets to
  verify which patterns the rule reports.
- **Path inspection, `tests/**`:** test code asserts suspicious path strings to
  exercise the string-inspection heuristic; it is not application code.

Path handling has `exclude = []`; its `inspection_exclude = ["tests/**"]`
suppresses only the string-inspection heuristic. Structural implicit-root
checks still cover tests. `tests/test_path_discovery_engine.py` verifies that a
test file's `Path(__file__).resolve().parents[1]` finding remains while its
`startswith("/")` inspection finding is suppressed.

All other configured rule `exclude` lists are empty: file size, line length,
comment markers,
output escaping, Python structure, and structural path handling. There is no
global file exclusion. The numeric, test-quality, and input-contract
review scanners also have empty exclusion lists. These targeted exceptions do
not relax Ruff or Pyright.

The `review` profile still selects the three warning scanners on its own.
`check` now includes it and fails on warnings so test prose and input-contract
regressions cannot be silently accepted. The test scan covers `tests/**` and
flags direct reads from `docs/**`; temporary fixtures and paths created by the
test remain allowed. See [review checks](REVIEW-CHECKS.md) for exact behavior
and current limits.

## Native Python checks

Run these from the repository root in the development environment:

```sh
ruff check src tests --select E4,E7,E9,F,ANN,I
ruff format --check src tests
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')" src
```

These commands are the self-profile's native Python steps. The Pyright
command uses the repository's strict mode from
`pyproject.toml`. Native tools retain ownership of lint, formatting, and type
diagnostics; Alphus does not duplicate or reinterpret them.

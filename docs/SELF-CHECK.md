# Self-checking Alphus

The `check` profile validates the package against its own repository policy. It
runs Alphus portable rules, the review rules, TOML syntax, an installed-package
import smoke check, native Ruff lint and format checks, strict Pyright, and
the package tests.
The repository's GitHub Actions quality workflow runs this profile on Python
3.11 and 3.12 for pull requests and main-branch pushes. It checks editable
installation, builds and installs a wheel, then invokes the installed package.

## Run the installed wheel against this checkout

Use Python 3.11 or newer. From anywhere inside the Alphus Git checkout, build a
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
"$work/venv/bin/python" -m pip install "$wheel" 'pyright>=1.1.414,<2' 'pytest>=8,<10' 'ruff>=0.16,<1'

(
  cd "$work"
  "$work/venv/bin/alphus" \
    --root "$repo" \
    --config "$repo/quality-gates.toml" \
    --run --profile check
)
```

The Pyright, pytest, and Ruff version ranges match the `dev` extra in `pyproject.toml`.
Pip installs the wheel's runtime requirements alongside those tools. The
profile includes Ruff lint, formatting, strict Pyright, and pytest.

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
The target-audit isolation rule checks that the four files copied into a
Python 3.10 target environment do not import Alphus's Python 3.11 controller
or its Pydantic, Rich, and Typer dependencies.

The only non-empty rule exclusions are:

- **Runtime type usage, `tests/**`:** tests deliberately exercise dynamic and
  broad runtime-type
  cases to verify the rule; this policy is for application code.
- **Runtime type usage, `src/alphus/gates/source/python_style.py` and
  `src/alphus/gates/source/runtime_types.py`:** these AST analyzers use `isinstance` to narrow
  AST nodes, not application runtime values.
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

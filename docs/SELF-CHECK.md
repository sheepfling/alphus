# Self-checking Alphus

The `check` profile validates the package against its own repository policy. It
runs Alphus portable rules, native Ruff lint, and the package tests. Ruff
formatting and strict Pyright remain native checks run separately; Pyright is
not a step in this profile.

## Run the installed wheel against this checkout

Use Python 3.11 or newer. From anywhere inside the Alphus Git checkout, build a wheel, install it with
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
"$work/venv/bin/python" -m pip install "$wheel" 'pytest>=8,<10' 'ruff>=0.16,<1'

(
  cd "$work"
  "$work/venv/bin/alphus" \
    --root "$repo" \
    --config "$repo/quality-gates.toml" \
    --run --profile check
)
```

The pytest and Ruff version ranges match the `dev` extra in `pyproject.toml`.
Pip installs the wheel's runtime requirements alongside those tools. The
profile includes Ruff lint and pytest; it does not include formatting or
Pyright.

## Self-profile scope and exclusions

`quality-gates.toml` inventories `src/**/*.py`, `tests/**/*.py`, `README.md`,
`docs/**/*.md`, `examples/**/*.toml`, `pyproject.toml`, and
`quality-gates.toml`. The profile runs Package boundaries, Python structure,
Runtime type usage, JSON structure, Output escaping, Path handling, Line
length, File size, Python lint, and Package tests. The global
`[files].exclude` is empty.

The only non-empty rule exclusions are:

- **Runtime type usage, `tests/**`:** tests deliberately exercise dynamic and broad runtime-type
  cases to verify the rule; this policy is for application code.
- **Runtime type usage, `src/alphus/python_style.py` and
  `src/alphus/runtime_types.py`:** these AST analyzers use `isinstance` to narrow
  AST nodes, not application runtime values.
- **JSON structure, `tests/**`:** tests include decoder calls in source snippets to
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
global file exclusion. The optional numeric, test-quality, and input-contract
review scanners also have empty exclusion lists. These targeted exceptions do
not relax Ruff or Pyright.

The separate `review` profile applies three optional warning scanners to the
same real inventory. It does not change the ten-step `check` profile. Its test
prose scan covers `tests/**`; its ephemeral-document patterns are empty because
this repository declares no transient plan documents as test inputs. See
[optional review checks](REVIEW-CHECKS.md) for exact behavior and current limits.

## Native Python checks

Run these from the repository root in the development environment:

```sh
ruff check src tests --select E4,E7,E9,F,ANN,I
ruff format --check src tests
pyright src
```

The first command is the self-profile's native Ruff lint step; formatting is
checked separately. `pyright src` uses the repository's strict mode from
`pyproject.toml`. Native tools retain ownership of lint, formatting, and type
diagnostics; Alphus does not duplicate or reinterpret them.

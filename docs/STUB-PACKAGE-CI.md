# Shared CI checks for stub packages

Alphus hosts the reusable PEP 561 stub-package verification action at
[`ci/stub-quality`](../ci/stub-quality). The verifier and fixture runner live
in `src/alphus/gates/stubs`; Python 3.10-compatible audit helpers live in
`src/alphus_stub_quality`. Both ship in the one Alphus wheel. The action
invokes the same verifier from its pinned checkout.
Alphus is a verification tool; consumer distributions retain only their stubs
and runtime requirements.

The action owns the repeated CI harness: dependency/tool setup, external wheel
and sdist build, installation of the built wheel, positive mypy and Pyright
consumer checks, marked negative fixtures, `pip check`, and `stubtest`. It also
provides generic API-audit inspection helpers to package-specific audit scripts.
Negative fixtures may use exact `# expect-error` line markers or an exact
diagnostic count with checker-specific required diagnostic text.

Each consumer repository keeps the facts that define its own contract:

- runtime package requirement and compatibility pin, provided as the action's
  `requirements-file`;
- `stub-quality.json` paths and runtime module names;
- positive and marked negative typing fixtures;
- its API inventory, runtime smoke assertions, and `stubtest` allowlist.

An API-audit module can receive `api_audit_args`; the verifier expands
`{source}` and `{consumer}` to the isolated source and consumer-copy paths.
This lets a source-inspection audit receive its package-specific stub root
without making that contract part of the shared action.

For example, an audit that accepts a stub-root argument can set
`api_audit_args` to `['--stub-root', '{source}/mdutils-stubs']`.

The action runs after the caller checks out its repository. Keep a full Git
history checkout when the stub package uses `setuptools-scm`; the action builds
an isolated source copy, so build artifacts do not pollute the caller checkout.
The caller owns event triggers and permissions. A small caller workflow can
retain its existing merge-only and manual-dispatch policy while invoking this
one shared job step.

Example caller step (replace the revision with the reviewed Alphus commit SHA):

```yaml
- uses: sheepfling/alphus/ci/stub-quality@<ALPHUS_COMMIT_SHA>
  with:
    requirements-file: requirements-compat.txt
    config-file: stub-quality.json
```

## Separate checker and target environments

Alphus installs on Python >=3.11,<3.16. A stub package may target Python >=3.10.
`--target-python` names the actual target executable; the default is the
checker interpreter for compatibility with existing local commands.
`ALPHUS_TARGET_PYTHON` supplies the same selection to a composed profile.
The verifier probes and records both full versions, executable paths, prefixes
and installed tool versions before running. It preserves venv executable paths.

| Stage                                                   | Interpreter/environment                       |
| ------------------------------------------------------- | --------------------------------------------- |
| Wheel/sdist build without isolation; install; pip check | Target                                        |
| API adapter; native mypy.stubtest; runtime smoke        | Target                                        |
| Pyright fixtures; optional Mypy/Ty                      | Checker; explicit target packages and version |
| Optional native Twine metadata check                    | Checker                                       |

Mypy receives `--python-executable TARGET --python-version X.Y`; Pyright
receives `--pythonpath TARGET --pythonversion X.Y`. `X.Y` comes from the actual
target probe. The standalone fixture CLI also probes the target and rejects a
conflicting explicit version. These flags override consumer language defaults.
The checker's own version alone is not compatibility evidence.

For a reusable POSIX local run, start in the consumer repository. Set
`ALPHUS_WHEEL` to the reviewed wheel and choose each target interpreter:

```shell
ALPHUS_WHEEL="$(find dist -maxdepth 1 -name 'alphus-*.whl' -print -quit)"
test -n "$ALPHUS_WHEEL" || { echo 'Build an Alphus wheel in dist/ first' >&2; exit 1; }
repo="$(pwd)"
work="$(mktemp -d)"
python3.12 -m venv "$work/checker"
python3.10 -m venv "$work/target"
"$work/checker/bin/python" -m pip install "$ALPHUS_WHEEL" \
  'mypy>=2.3' 'pyright>=1.1.414' 'twine>=7.0'
"$work/target/bin/python" -m pip install -r "$repo/requirements-target.txt" \
  -r "$repo/requirements-compat.txt"
(
  cd "$work"
  "$work/checker/bin/python" -m alphus.gates.stubs.verify \
    --root "$repo" --config stub-quality.json --with-twine \
    --target-python "$work/target/bin/python" --report "$work/result.json"
)
```

mdutils uses `requirements/compatibility.txt` for its runtime pin instead.
The target requirements declare build/backend tools, wheel, typing_extensions
and Mypy for native stubtest. Neither Alphus nor Pyright needs to be installed
in the target. The checker needs no consumer runtime or stub package.

The API adapter uses a temporary target import overlay containing exactly five
unchanged installed-wheel files: `alphus_stub_quality/__init__.py`,
`api_audit_support.py`, `api_contracts.py`, `runtime_audit.py` and `py.typed`.
No core Alphus module, controller, Pydantic dependency, source checkout or whole
checker site-packages directory is exposed. Inherited PYTHONPATH, PYTHONHOME,
MYPYPATH and VIRTUAL_ENV are removed; user-site loading is disabled. The built
consumer wheel is installed in the target. Fresh venvs are the reproducible
isolation boundary; the verifier does not erase unrelated preinstalled packages.

`--report` records both identities, exact stage argv, exits and elapsed times.
A failure stops later stages, leaves `passed=false`, and preserves native output
in the caller's log. Spawn failures record exit 127 and the error. Preflight
errors exit before stages; an old report is removed before preflight, so absence
of a new report cannot masquerade as a prior success. A missing target tool
fails in that target; there is no checker fallback. Target smoke or dependency
failure fails the run even when static fixtures pass.

The POSIX stub action creates distinct checker and target venvs even when their
versions match. Set `python-version: "3.12"`, `target-python-version: "3.10"`
and `target-requirements-file: requirements-target.txt` for that matrix leg.
Its original inputs remain usable; an omitted target version selects the checker
version. The caller retains its trigger and permission policy.

## Generic gates and consumer adapters

`alphus-typing-fixtures` (also `python -m alphus.gates.stubs.typing_fixtures`)
checks positive and expected-negative examples with Pyright by default.
Mypy and Ty are opt-in fixture checkers: install `alphus[python,mypy]` or
`alphus[python,ty]` in the checker environment, then select
`--checkers pyright mypy` or `--checkers pyright ty`. The Ty extra pins its
pre-1.0 checker version because its diagnostic contract can change between
releases. Ty uses concise diagnostics and accepts the selected target
interpreter and Python version. Add `--ty-diagnostic` to require a specific
negative diagnostic. The isolated verifier accepts
`typing_checkers = ["pyright", "mypy", "ty"]` in its `verification` config.

The fixture runner probes every selected checker module before running cases.
The shared `alphus.support.tool_probe` also locates native commands; the C++
artifact scanner uses it for objdump. The installed-stub verifier still needs
Mypy in its target environment for the separate `mypy.stubtest` stage.

Positive examples require exit zero and no errors. Negative contracts require
an exact set of marked lines, or a configured diagnostic count, plus any
checker-specific diagnostic fragments. An unrelated failure never establishes
the configured expected errors. Multiple diagnostics on one marked line are
allowed unless an explicit count says otherwise. Timeouts and spawn failures
fail.

`alphus-stub-quality` runs the isolated build/install consumer gate. It retains
native tool output and delegates type semantics and runtime compatibility to
Mypy, Pyright and stubtest. Package-specific runtime smoke modules stay local.

`ApiCoverageTests` in `alphus_stub_quality.api_contracts` supplies reusable
unittest gates for module inventories, source/stub class shapes, annotation
completeness, export aliases, public-call probes, declaring-class probe counts,
asserted result types, and configured surface constraints. A consumer subclasses
it with module paths, loaded runtime modules, export expectations, version,
stub root and example path.
The structural helpers in `api_audit_support` and runtime matching in
`runtime_audit` also support packages with a different facade/ownership policy.
No package names or expected APIs are built into those engines.

The example crawler resolves direct imports, configured module/class re-exports,
constructor assignments and direct calls. It does not prove runtime coverage,
resolve arbitrary control flow or dynamic aliases, or infer complete typing
semantics.
Source shape checks preserve AST default expressions and decorator distinctions.

Only the five shared audit helper files need Python 3.10 compatibility.
The controller stays installed in the Python >=3.11,<3.16 checker environment.
Alphus's own regression suite uses these same shared engines with neutral
positive and intentionally broken examples.

The execution gates use the installed `alphus-typing-fixtures` and
`alphus-stub-quality` entrypoints. They can be selected as command steps in an
Alphus profile. They are workflow gates that coordinate native tools and
environments, so they use the same command-step interface as other tools
instead of the source-only `--rule` scanner interface. The GitHub Action
installs the same pinned Alphus code as a verification tool. The former
stub helper forwarders have been removed; import controller APIs from
`alphus.gates.stubs` and target audit helpers from `alphus_stub_quality`.

The [migration record](TEST-GATE-MIGRATION.md) maps consumer ownership and
records revision-specific acceptance evidence.

## Composed consumer profiles

The two stub consumers use the general [quality action](../ci/quality/action.yml)
for their `quality` selection (`python` plus `markdown`). Their separate
stub-action matrix runs `stubs` once for each target 3.10–3.14. The local default
`check` still composes all three profiles. CI does not repeat the 3.12 stub gate
inside `quality`. Both actions and local requirements pin the same Alphus SHA.
See [consumer profiles](CONSUMER-PROFILES.md) for composition and pinning.
The stub-only action above retains its existing interface for other callers.

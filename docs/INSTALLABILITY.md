# Alphus installability and release readiness

## Candidate package

The candidate is `sheepfling/alphus`, under review in PR #1 on
`codex/alphus-quality-closure`; the closure changes are recorded in the
review-candidate snapshot below. The package declares version `0.1.0`, Python
`>=3.11`, the `alphus` console command, and `py.typed`. The earlier 3.11 and
3.12 proofs document source revisions tested before this closure work.

## Current editable-install proof (2026-10-22)

At commit `45f26bf92cc3d01127c05a1995d75219720df736`, a disposable Python
3.12.14 environment on Windows installed the checkout with `uv pip install -e .`
and resolved its runtime dependencies. The installed `alphus --help` command
exited successfully. Installed metadata exposed the expected `alphus.cli:main`,
`alphus_stub_quality.verify:main`, and
`alphus_stub_quality.typing_fixtures:main` entry points. This validates the
current editable packaging path; it does not establish a public-index install
or a hosted CI result. The self-profile's package-boundary step now rejects
malformed console and GUI entry-point references such as `alphus.:main` before
a build backend is invoked.
The entry-point paths above record that historical proof. The current source
points those same console commands at `alphus.gates.stubs`; the old module
paths remain compatibility imports.

## Python 3.11 wheel and runtime proof

Built `alphus-0.1.0-py3-none-any.whl` with Python 3.11.16 in the isolated
environment `/tmp/alphus-python311-venv`. The final wheel SHA-256 is
`870f61c751696075f240c1c5afb5eeced07b0e5d5fb483be4b5ceefcbe7170e9`. Runtime
dependencies and the local wheel were installed in that venv; versions were
packaging 26.3, pydantic 2.14.0, Rich 15.0.0, and Typer 0.27.3. The profile
tool versions were mdrepo 0.0.1.post0, rumdl 0.2.77, Ruff 0.17.0, Pyright
1.1.411, and pytest 9.1.1. The CLI resolved from the installed wheel in
`site-packages`, metadata reported version `0.1.0`, `py.typed` was present,
and `pip check` found no broken requirements.

With that installed wheel, the self-check profile passed 10/10 steps, including
139 package tests. Focused orchestration and consumer-profile tests passed 12/12.
A separate generic consumer fixture passed its coordinated profile 12/12,
including mdrepo, rumdl, Ruff, Pyright, and pytest. Its deliberately invalid
variant exited 1 with the expected missing-target (`MDR004`), orphan
(`MDR101`), and formatting findings; 10/12 steps passed and the later Python
checks still ran. Pyright is invoked with the profile's `{python}` interpreter
so it checks the selected environment. The fixture lives at
`/tmp/alphus-consumer-fixture-35b-final`.

The read-only `mdutils-stubs` compatibility check used the archived commit
`8fee582bfe756580687bfb87620d9d1d73865d80` and the same Python 3.11
environment: `stub-package` passed 6/6 and `markdown-quality` passed 2/2.
Its policy still pins Alphus at `73e4cdb`; no mdutils-stubs files were changed.

## Python 3.12 proof

Built the current package source at commit
`f445b9d62c8b5ea3be8085ce20011fe6ecba34cd` (tree
`c27f1e4272b2fe63897f8451c048ef9fd870beb1`) with Python 3.12.14 in the
isolated environment `/tmp/alphus-clean-deps-20261010`. The wheel SHA-256 is
`1496caa0f3355283c801bdbc80f5dd640bcea572be6467294821c19d3839341b`. The
wheel was installed from the local artifact into
`/tmp/alphus-f445-py312-installed`; its import resolved there, metadata
reported version `0.1.0`, `py.typed` was present, CLI help succeeded, and
`pip check` found no broken requirements. The venv has packaging 26.3, pydantic
2.14.0, Rich 15.0.0, Typer 0.27.3, mdrepo 0.0.1.post0, Ruff 0.17.0, and
pytest 9.1.1. The external profile tools were Pyright 1.1.411 and rumdl
0.2.77.

The installed wheel's self-check profile passed 10/10, including 139 package
tests. A generic consumer fixture passed 12/12, including mdrepo, rumdl, Ruff,
Pyright, and pytest. Its deliberately invalid variant exited 1 with the
expected missing-target (`MDR004`), orphan (`MDR101`), and formatting
findings; 10/12 steps passed and the later Python checks still ran. The first
build attempt in the restricted shell failed to resolve `pypi.org`; the
approval-reviewed official PyPI route then fetched isolated build dependencies
and the same exact-source wheel build succeeded. This records the transport
failure and its resolution, rather than treating the first attempt as a
remaining package blocker. The proof does not expand mdutils-stubs' separate
Python 3.11–3.14 runtime or 3.10–3.14 typing coverage.

## Review closure snapshot (2026-10-12)

Built `alphus-0.1.0-py3-none-any.whl` from this closure candidate with Python
3.11.16 in `/tmp/alphus-python311-venv`. The SHA-256 is
`2d413e758a7c91a5891722ce290ef34fe78c0e310aeddc0751f21b846b76ef4b`. The
same pure-Python wheel was installed with `--no-deps` into fresh target
directories and imported from those directories under Python 3.11.16 and
3.12.14. The 3.12 environment was
`/tmp/alphus-clean-deps-20261010`; it already contained the runtime and test
dependencies. Its build backend did not include setuptools, so the universal
wheel was built once under 3.11 and the exact artifact was used for both
installed-wheel proofs.

The installed-wheel self-check profile passed 10/10 steps on each Python
version, including 145 package tests. A clean copy of the consumer fixture,
with its intentionally broken Markdown link and formatting corrected, passed
all 12 profile steps on both versions, including mdrepo, rumdl, Ruff, Pyright,
and pytest. The original broken-docs fixture was left untouched; its expected
negative profile exited 1 with `MDR004`, `MDR101`, and Markdown-format findings,
while the remaining checks ran (10/12 steps passed) on both versions. The
fresh positive fixture is `/tmp/alphus-consumer-positive-ac972`.

## Distribution status

The earlier proofs establish local wheel builds and installations for their
source revisions, with dependencies resolved from the approved official PyPI
route. They do not establish a clean install from a public Alphus package
index or from a public Git URL. Prior registry checks found no PyPI project or
GitHub release. Draft PR #1 is review only and is not a release. The local tag
`quality-gate/module-role-assignments` is a development tag. No publish or
release action was taken.

For adoption, merge the PR, choose the distribution channel, and
verify a clean install through that channel. Keep consumer pins on immutable
commits until a supported distribution path is selected and verified.

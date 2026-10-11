# Alphus installability and release readiness

## Candidate package

The candidate is `sheepfling/alphus`, branch `feature/initial-work`, at source
revision `35b2924da7a689d0f9b3986b8306a5ea479295f1` (tree
`0fac805351d7866aa39b8da6980668b62c547ef5`). The package declares version
`0.1.0`, Python `>=3.11`, the `alphus` console command, and `py.typed`. The
published extraction branch `feature/initial-work` is five commits ahead of
`main` at `289b1072202f75200df709384f22de81e9b13db3`; the review branch adds
one closure commit on top of the extracted package.

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

An earlier Python 3.12.14 wheel/profile run passed 10/10 self-check steps,
including 139 package tests, and 12/12 consumer steps. A fresh Python 3.12
wheel build for this final source snapshot could not complete: build isolation
could not resolve `pypi.org` to download `setuptools>=68`. Treat that earlier
run as historical, not as a current exact-revision proof. This check does not
expand mdutils-stubs' separate Python 3.11–3.14 runtime or 3.10–3.14 typing
coverage.

## Distribution status

These proofs establish local wheel build and installation with dependencies
resolved from the approved official PyPI route. They do not establish a clean
install from a public Alphus package index or from a public Git URL. Prior
registry checks found no PyPI project or GitHub release. At that lookup there
was no PR; this review branch is being submitted as a draft PR that includes
the extracted package history plus the closure commit. A draft PR is not a
release. The local tag `quality-gate/module-role-assignments` is a development
tag. No publish or release action was taken.

For adoption, merge the feature branch, choose the distribution channel, and
verify a clean install through that channel. Keep consumer pins on immutable
commits until a supported distribution path is selected and verified.

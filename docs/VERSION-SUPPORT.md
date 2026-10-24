# Version support

Alphus has three separate version boundaries: the interpreter running Alphus,
the interpreter of an optional stub-package target, and the native tools a
consumer selects. The package metadata in `pyproject.toml` is the authority for
installable Python and dependency ranges. A range permits installation; CI
evidence establishes the combinations Alphus has actually exercised.

## Alphus checker

**Checker Python:** `>=3.11,<3.16`. CI runs the full editable-install and
installed-wheel profile on 3.11, 3.12, 3.13, 3.14, and 3.15.

**Runtime packages:** `packaging>=23,<27`, `pydantic>=2.7,<3`,
`rich>=15,<16`, and `typer>=0.27.3,<0.28`. CI runs the full profile with
resolved versions on each checker Python and with all direct lower bounds
together on 3.11.

**Optional `python` extra:** `pyright>=1.1.414,<2`, `pytest>=8,<10`, and
`ruff>=0.16,<1`. CI checks the resolved versions and direct lower bounds. These
tools install only when the extra is selected.

The upper bounds exclude unreviewed major versions. The CI jobs do not prove
every intermediate version or every cross-product of the listed ranges. Pin
exact versions in a consumer lockfile when repeatable results matter. Update
the metadata, this table, and the CI matrix together when changing a range.

Alphus-owned repository, hygiene, source, and review gates inherit the checker
Python and runtime dependency range. Python gates that use `ast.parse` read
source with the running checker's Python grammar. To inspect syntax introduced
in Python 3.14, run Alphus on Python 3.14. They do not accept an independent
target-language-version setting.

## Stub-package target

The stub verifier runs in the checker environment above. Its isolated target
interpreter must be Python `>=3.10`, as checked by `--target-python`. The audit
helpers copied into a Python 3.10 target ship in the same Alphus wheel; the
target does not install the Alphus distribution. Historical consumer acceptance
covered targets 3.10 through 3.14 under the revisions recorded in
[Test gate migration](TEST-GATE-MIGRATION.md). That evidence is separate from
the current checker CI matrix.

## Selected native tools

The `tools` list selects commands; it does not declare tool version ranges in
the policy. The `python` extra installs the Python recipe tools within the
metadata ranges above. The consumer installs and pins rumdl, mdrepo, Taplo,
Prettier, and any custom commands in its own development or CI environment.
Alphus retains their output and exit status without claiming that all versions
of those tools have identical behavior. The optional React and Angular ESLint
profiles use peer plugins installed by the consumer; this package checks its
React profile with `@eslint-react/eslint-plugin` 5.28 and
`eslint-plugin-react-hooks` 7.1, and its Angular profile with
`angular-eslint` 22.6. Match Angular's plugin to the consumer's Angular major.
The standard HTML and CSS exports are exercised with `html-validate` 10.17,
`stylelint` 17.16, and `stylelint-config-standard` 40. HTML-validate 10.x
supports the package's Node 20 range; on Node 22 it needs 22.16 or newer.
Its 11.x line requires newer Node.
See [Subtool composition](SUBTOOLS.md) for configuration ownership and fix
commands.

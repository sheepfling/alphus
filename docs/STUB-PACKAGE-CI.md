# Shared CI checks for stub packages

Alphus hosts the reusable PEP 561 stub-package verification action at
[`ci/stub-quality`](../ci/stub-quality). The reusable gates and inspection
helpers
live in `src/alphus_stub_quality` and ship in the Alphus wheel. The action
invokes that same implementation from its pinned checkout.
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

For a local run, install the reviewed Alphus wheel in a dedicated verification
environment,
then use the same consumer configuration:

```sh
python -m alphus_stub_quality.verify \
  --root /path/to/consumer --config stub-quality.json --with-twine
```

Install the consumer's declared verification tools and runtime requirement in
the selected Python environment before the local run. The GitHub Action does
that setup itself.

## Generic gates and consumer adapters

`alphus-typing-fixtures` (also `python -m alphus_stub_quality.typing_fixtures`)
checks positive and expected-negative examples through native Mypy and Pyright.
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

Alphus requires Python 3.11 or later to install. Its shared test
modules retain Python 3.10 syntax for consumer matrix jobs: use a reviewed
Alphus source checkout with `PYTHONPATH=/path/to/alphus/src` for those jobs.
Provision the verifier's Pydantic dependency in that environment as the action
does.
This does not extend the supported Python versions of the main Alphus CLI.
Alphus's own regression suite uses these same shared engines with neutral
positive and intentionally broken examples.

The execution gates use the installed `alphus-typing-fixtures` and
`alphus-stub-quality` entrypoints. They can be selected as command steps in an
Alphus profile; they are not source-only `--rule` scanners. The GitHub Action
installs the same pinned Alphus code as a verification tool.

The [migration record](TEST-GATE-MIGRATION.md) maps consumer ownership and
records the current acceptance blocker.

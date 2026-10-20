# Shared CI checks for stub packages

Alphus hosts the reusable PEP 561 stub-package verification action at
[`ci/stub-quality`](../ci/stub-quality). The Python helpers live under this
CI-only directory, outside Alphus's installable `src/` tree. Consumer
repositories call the action at an immutable Alphus commit from GitHub Actions.
They do not install Alphus,
add it to `pyproject.toml`, or ship any Alphus code with their packages.

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

For a local run, use the same verifier from an Alphus checkout and the same
consumer configuration:

```sh
PYTHONPATH=/path/to/alphus/ci/stub-quality/python \
python /path/to/alphus/ci/stub-quality/python/alphus_stub_quality/verify.py \
  --root . --config stub-quality.json --with-twine
```

Install the consumer's declared verification tools and runtime requirement in
the selected Python environment before the local run. The GitHub Action does
that setup itself.

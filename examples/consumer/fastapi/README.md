# FastAPI consumer profile

This example shows an opt-in static profile for FastAPI repositories. It adds
Ruff's FastAPI, selected async-safety, annotation, and security rules while
preserving the base selection in `pyproject.toml`. It also runs Alphus's
existing FastAPI style advisory.

The check reads Python source only. It does not import the application or
require FastAPI, Pydantic, a database, credentials, or network access. Install
FastAPI and Pydantic in the consuming application's own environment when its
runtime and tests need them. Install Ruff 0.16 or newer for this example.

From this directory, inspect and run the profile with:

```sh
alphus --config quality-gates.toml --profile fastapi --plan
alphus --config quality-gates.toml --profile fastapi --run
```

To adopt it in an existing policy, add the two FastAPI steps and a named
`fastapi` profile, then include that profile in `check` when the team is ready
to make the findings part of its normal workflow. The read-only Ruff step has
no automatic fixer. Review `FAST001` findings before changing response
declarations because they can affect the generated OpenAPI document.

See [the FastAPI quality guide](../../../docs/FASTAPI-QUALITY.md) for the
current coverage boundary and deferred route, OpenAPI, security, and runtime
checks.

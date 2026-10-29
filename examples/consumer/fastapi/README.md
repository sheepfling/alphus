# FastAPI consumer profile

This example shows an opt-in profile for FastAPI repositories. It adds Ruff's
FastAPI, selected async-safety, annotation, and security rules while preserving
the base selection in `pyproject.toml`. It also reviews configured source
advisories and the explicitly selected application's registered routes and
generated OpenAPI schema.

The Ruff and source-advisory steps only read source. The route step imports
`routes:app` from `src/`, calls `.openapi()`, and does not start the ASGI
lifespan or issue HTTP requests. The configured app and its factory must be
safe to import without production credentials, a database connection, or
network access. FastAPI and Pydantic remain application dependencies; the
Alphus development suite has a separate `fastapi-test` extra. Install Ruff
0.16 or newer for this example.

From this directory, inspect and run the profile with:

```sh
alphus --config quality-gates.toml --profile fastapi --plan
alphus --config quality-gates.toml --profile fastapi --run
```

Install this application's FastAPI dependencies in the same environment before
running the profile. A consumer that configures `openapi_baseline` must also
install and pin `oasdiff`; the comparison uses local files and never opens a
hosted diff review.

To adopt it in an existing policy, add the two FastAPI steps and a named
`fastapi` profile, then include that profile in `check` when the team is ready
to make the findings part of its normal workflow. The read-only Ruff step has
no automatic fixer. Review `FAST001` findings before changing response
declarations because they can affect the generated OpenAPI document.

The example's behavioral tests use FastAPI's `TestClient` with HTTPX, a local
token, and dependency overrides. From the Alphus repository root, run them
without starting a network server or contacting external services:

```sh
python -m pip install -e ".[python,fastapi-test]"
python -m pytest examples/consumer/fastapi/tests
```

See [the FastAPI quality guide](../../../docs/FASTAPI-QUALITY.md) for rule
limits, OpenAPI baseline setup, and advice on behavior static checks cannot
prove.

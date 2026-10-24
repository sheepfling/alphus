# FastAPI quality profile

FastAPI support remains opt-in: consumers select a `fastapi` profile or include
it in their existing aggregate profile. The static source checks do not import
FastAPI. Route and OpenAPI review runs only when a consumer explicitly sets
`checks.fastapi_practices.application`.

## Current coverage

Alphus registers the `fastapi-practices` rule in its review profile. Its
source-only mode parses Python without importing FastAPI or contacting an
application. It reports:

- Literal HTTP status values in recognized FastAPI and Starlette calls.
- Literal error codes in consumer-configured call sites, with a separate
  opt-in check for literal `detail["code"]` values on HTTP exceptions.

When an application target is configured, the same rule also inspects the
registered `APIRoute` table and generated OpenAPI documents for duplicate
method/path registrations, missing or duplicate operation IDs, and any
consumer-enabled requirements for response schemas, route metadata, and
documented security. An optional checked-in OpenAPI baseline can be compared
with a consumer-installed `oasdiff` executable.

Alphus imports only the configured application, calls `.openapi()`, and does
not start the application lifespan or send HTTP requests. Imports and any
explicitly configured zero-argument factory execute consumer code; consumers
must keep that path safe without production credentials, database connections,
or network access. FastAPI and Starlette are loaded lazily and remain outside
Alphus's runtime dependencies. HTTPX and FastAPI are available only in the
development `fastapi-test` extra. Ruff remains consumer-owned and no Ruff
autofix is run.

## First delivery: native Ruff profile

The example in [`examples/consumer/fastapi`](../examples/consumer/fastapi/)
adds an explicit `fastapi` profile. Its Ruff configuration extends the
consumer's `pyproject.toml` and uses `extend-select`, preserving the base
selection and exclusions. The profile checks these stable rules:

| Rules | Coverage |
| --- | --- |
| `FAST001`, `FAST002`, `FAST003` | Redundant response model, dependency `Annotated`, missing path parameter |
| `ASYNC210`, `ASYNC230`, `ASYNC240`, `ASYNC251` | Blocking HTTP, file, path, and sleep operations in async functions |
| `B008` | Function calls in defaults, with FastAPI parameter constructors configured as immutable calls |
| `ANN001`, `ANN201` | Missing parameter and return annotations |
| `S113`, `S501`, `S608` | Missing HTTP timeouts, disabled certificate checks, and SQL built from strings |

The sample targets Python 3.12 and requires Ruff 0.16 or newer. FastAPI and
Pydantic stay in the consuming application's dependency set; the static
profile itself does not import or execute them. The example's
`fastapi-practices` step remains a warning-level advisory alongside Ruff's
native findings. Ruff keeps its native exit status: a reported Ruff violation
fails this profile, while `severity = "warning"` applies to the Alphus advisory.

The lint command intentionally has no `fix_argv`. In particular, Ruff's
`FAST001` fix is unsafe because removing `response_model` can change runtime
behavior or generated OpenAPI. `FAST002` fixes can also change function
defaults. Review findings and make any API edit explicitly. See the
[FAST001 rule documentation](https://docs.astral.sh/ruff/rules/fast-api-redundant-response-model/)
and [Ruff's B008 settings](https://docs.astral.sh/ruff/settings/#lint-flake8-bugbear-extend-immutable-calls).

Use a narrow `extend-select` list and add application-specific exclusions with
an adjacent explanation. This foundation does not introduce a separate
suppression registry or change Ruff's project-wide rule selection.

## False positives and exceptions

`FAST001` can be intentional when a team keeps an explicit response declaration
to control serialization or the public schema. `FAST002` is a consistency
recommendation; a legacy signature may need a local exception. The async and
security rules recognize known syntax and calls, so wrappers and project-owned
trust boundaries still need review. For example, `S501` may match a local
test certificate setup, and `S608` may match a trusted static query.

Use a rule-specific Ruff `# noqa: <ID>` at the finding only when the reason is
recorded next to the code or in project policy. Keep per-file ignores narrow;
avoid disabling a whole rule family to silence a few call sites.

## Registered route and OpenAPI checks

Add the consumer-owned application target to the existing policy:

```toml
[checks.fastapi_practices]
extensions = [".py"]
application = "my_api.main:app"
application_python_paths = ["src"]
exclude_route_paths = ["/health*", "/metrics*", "/internal/*", "/files/*"]
required_route_metadata = ["summary", "description", "tags"]
require_response_contract = true
protected_route_paths = ["/v1/private/*"]
```

The module and attribute are imported only for the selected check. A callable
is invoked only when `application_factory = true`; it must take no arguments.
FastAPI's generated OpenAPI schema includes included and nested routers. Mounted
FastAPI sub-apps are inspected separately with their mount prefix applied.
`include_in_schema = false` removes a route from OpenAPI checks, while duplicate
registration checks still inspect the registered route table. Paths matching
`exclude_route_paths` are excluded from all route checks. Patterns are
case-sensitive route globs using `*` and `?`; `*` matches zero or more
characters, including `/`, and `?` matches one character.

The deterministic rule IDs are:

| Rule ID suffix | Finding |
| --- | --- |
| `correctness/duplicate-route` | Duplicate registered method and path |
| `metadata/missing-operation-id` | OpenAPI operation without an ID |
| `metadata/duplicate-operation-id` | ID repeated across operations |
| `validation/missing-response-contract` | Configured operation has no typed 2xx response schema |
| `metadata/missing-route-metadata` | Configured summary, description, or tags are absent from OpenAPI |
| `security/missing-openapi-security` | A configured protected path lacks an OpenAPI security requirement |
| `validation/openapi-breaking-change` | The configured compatibility tool found a breaking difference |

The duplicate route and operation ID checks run whenever `application` is
configured. Response schema, metadata, and protected-route checks are opt-in
through their policy fields. Use exclusions for intentionally raw response,
file, streaming, redirect, health, metrics, or internal operations. Findings
use endpoint source file and line when Python exposes a repository-local source
location; otherwise they point at the configured application target.

Stable FastAPI findings can be adjusted by exact rule ID. Every override needs
a short reason; file exclusions suppress only that rule in the selected source
paths.

```toml
[[checks.fastapi_practices.finding_overrides]]
rule_id = "alphus/python/fastapi/correctness/literal-http-status"
severity = "info"
exclude_paths = ["examples/legacy-api/**"]
reason = "These fixtures intentionally demonstrate literal status codes."
```

`protected_route_paths` is consumer policy about which paths must document
security. Alphus checks the generated OpenAPI operation's `security` field;
this only verifies a published contract declaration. It does not prove that a
request is authorized at runtime, and a plain `Depends()` never counts as
authorization evidence. Add representative HTTP tests for the actual access
control behavior.

To compare a checked-in baseline, install and pin `oasdiff` in the consumer's
environment, then set:

```toml
openapi_baseline = "openapi-baseline.json"
openapi_breaking_threshold = "WARN"
```

The default `WARN` threshold fails on both definite and potential breaking
changes; `ERR` fails only on definite breaks. The baseline must be a repository
file, and the comparison uses a temporary JSON file for the root application's
current schema after applying route exclusions. The same exclusions are passed
to `oasdiff` for the baseline comparison, so ignored operations are removed from
both sides. Failure findings include up to four single-line changes for review.
Mounted FastAPI sub-applications are inspected with their prefixes for route
checks, but baseline comparison currently covers only the configured root
application schema; mounted sub-app schemas do not have separate baseline
settings.
The maintained [oasdiff CLI](https://github.com/oasdiff/oasdiff) provides
breaking-change rules, JSON/YAML output, and local-file comparison. Its
coverage and severity may need consumer tuning, so Alphus does not install it
or implement another schema diff engine. Do not use hosted review/upload flags
for proprietary schemas.

## Behavioral tests and analysis limits

The example tests use `TestClient` and HTTPX with dependency overrides and
`yield` cleanup, without a production database or external network. The
development-only extra is installed with:

```shell
python -m pip install -e ".[python,fastapi-test]"
python -m pytest tests/gates/review/frameworks/test_fastapi_contracts_engine.py \
  examples/consumer/fastapi/tests
```

Application import and schema generation do not run ASGI lifespan handlers,
resolve dependencies, or exercise persistence. Static source checks do not
prove absence of blocking I/O in async endpoints, request-scoped database
session safety, transaction ownership, resource cleanup, or absence of
import-time network activity. Use small `TestClient`/HTTPX cases, dependency
overrides, and explicit consumer policy for those behaviors. The example
demonstrates unauthorized and authorized requests plus a `yield` dependency's
cleanup; it is not a universal session-lifecycle checker.

Contract compatibility is delegated to the optional maintained tool rather
than an Alphus-specific diff engine. A baseline describes consumer-approved
compatibility; it is not generated or approved automatically.

The route implementation and fixtures are optional: core Alphus installs
without FastAPI, Starlette, or HTTPX. The existing reusable Ruff profile stays
read-only and does not change global Ruff configuration or add hosted CI jobs.

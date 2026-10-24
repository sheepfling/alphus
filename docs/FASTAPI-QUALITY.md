# FastAPI quality profile

This guide records the baseline audit for issue #4 and the first delivery
boundary. FastAPI support remains opt-in: consumers select a `fastapi` profile
or include it in their existing aggregate profile.

## Current coverage

Alphus already registers the `fastapi-practices` source rule in its review
profile. It parses Python source without importing FastAPI or contacting an
application. Its current findings are limited to:

- Literal HTTP status values in recognized FastAPI and Starlette calls.
- Literal error codes in consumer-configured call sites, with a separate
  opt-in check for literal `detail["code"]` values on HTTP exceptions.

These findings are warnings. They do not inspect an instantiated application,
registered route table, generated OpenAPI document, database session, or
runtime behavior. `Depends()` is not treated as proof of authorization.

Ruff, Pyright, and pytest remain consumer-owned commands. Alphus does not add
FastAPI, Starlette, or HTTPX to its runtime dependencies. The existing Ruff
command in Alphus's self-check uses an explicit repository-specific rule
selection, so it is not a reusable FastAPI rule preset.

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

## Follow-up coverage

Route and OpenAPI checks need registered application introspection and generated
schemas, so they belong in a later PR with deterministic fixtures. The issue's
proposed FAPI101-FAPI104 checks cover duplicate method/path registration,
operation ID uniqueness, response contracts, and public-route metadata; final
IDs should follow the existing rule naming conventions.

| Follow-up | Scope |
| --- | --- |
| PR 2 | Registered routes and generated OpenAPI contracts; mounted routers and custom-response fixtures |
| PR 3 | Project-policy authorization, async/database resource safety, lifespan, and production settings |
| PR 4 | OpenAPI compatibility, error responses, layer boundaries, and optional behavioral tests |

Security and resource-lifecycle checks need explicit project policy; the
presence of a dependency is not authorization evidence. Contract baselines,
compatibility diffs, dependency overrides, and behavioral HTTP tests remain
later work.

Static checks will stay conservative. Production credentials, databases, and
network access are not required for route or schema inspection. Runtime claims
will require behavioral tests rather than being inferred from source syntax.

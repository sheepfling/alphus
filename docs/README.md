# Alphus documentation map

Start with [installation and first use](../README.md#install), then choose the
path that matches the repository being checked.

| Need                                                      | Read                                        |
| --------------------------------------------------------- | ------------------------------------------- |
| Choose language bundles and configure one profile         | [Consumer profiles](CONSUMER-PROFILES.md)   |
| Understand installed native tools and their configuration | [Subtools](SUBTOOLS.md)                     |
| Plan and apply available fixes                            | [Fixes](FIXES.md)                           |
| Run independent quality checks concurrently               | [Parallel execution](PARALLEL-EXECUTION.md) |
| Analyze gate history across repositories                   | [History analytics](QUALITY-HISTORY-ANALYTICS.md) |
| Export profile evidence and inspect early failures          | [Profile reporting](REPORTING.md)            |
| Check Python stubs in an isolated target                  | [Stub package CI](STUB-PACKAGE-CI.md)       |
| Reuse CI integrations across providers                    | [CI integrations](CI-INTEGRATIONS.md)       |
| Check C++ source, builds, and artifacts                   | [C++ quality](CPP-QUALITY.md)               |
| Check Git ignores or historical repository artifacts      | [Repository hygiene](REPOSITORY-HYGIENE.md) |
| Understand shared text and file-size measurements          | [Source hygiene](SOURCE-HYGIENE.md)         |
| Review test, input, source-family, and framework checks   | [Review checks](REVIEW-CHECKS.md)           |
| Audit consumer-selected lint suppression reasons          | [Lint suppressions](LINT-SUPPRESSIONS.md)   |
| Detect docs/default drift                                   | [Docs/config drift](DOCUMENTATION-CONFIG-COUPLING.md) |
| Separate machine CLI contracts from presentation policy     | [Python CLI policy](CLI-POLICY.md)                    |
| Gate cyclomatic complexity across Python, C/C++, and JS    | [Cyclomatic complexity](CYCLOMATIC-COMPLEXITY.md) |
| Review positional argument interfaces                      | [Positional interfaces](POSITIONAL-INTERFACES.md) |
| Add FastAPI-specific static checks                        | [FastAPI quality](FASTAPI-QUALITY.md)        |
| Map common lint intents to native rules                   | [Common lint intents](COMMON-LINT-INTENTS.md) |
| Verify Alphus with its own policy                         | [Self-check](SELF-CHECK.md)                 |

## How the pieces fit

[Architecture](ARCHITECTURE.md) defines the owning packages and the boundary
between a portable rule and a command step. [Extensibility](EXTENSIBILITY.md)
explains how to add a rule or language theme. [Version support](VERSION-SUPPORT.md)
lists the supported Python and dependency ranges. [Installability](INSTALLABILITY.md)
records wheel and editable-install checks.

The root [`quality-gates.toml`](../quality-gates.toml) configures Alphus's
own self-check. Files named `quality-gates.toml` under `examples/` are
consumer starting points; tests load some of them as fixtures. They are
not part of the root self-check configuration.

The C++ checker implementations ship in `src/alphus/gates/cpp/`. Their
detailed evidence contracts live in [the C++ guide index](cpp/README.md),
and sample JSON policy inputs live under
[`examples/cpp/policies/`](../examples/cpp/policies/).

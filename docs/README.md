# Alphus documentation map

Start with [installation and first use](../README.md#install), then choose the
path that matches the repository being checked.

| Need                                                      | Read                                        |
| --------------------------------------------------------- | ------------------------------------------- |
| Choose language bundles and configure one profile         | [Consumer profiles](CONSUMER-PROFILES.md)   |
| Understand installed native tools and their configuration | [Subtools](SUBTOOLS.md)                     |
| Plan and apply available fixes                            | [Fixes](FIXES.md)                           |
| Check Python stubs in an isolated target                  | [Stub package CI](STUB-PACKAGE-CI.md)       |
| Check C++ source, builds, and artifacts                   | [C++ quality](CPP-QUALITY.md)               |
| Check Git ignores or historical repository artifacts      | [Repository hygiene](REPOSITORY-HYGIENE.md) |
| Understand shared text and file-size measurements          | [Source hygiene](SOURCE-HYGIENE.md)         |
| Review advisory test, input, and framework checks         | [Review checks](REVIEW-CHECKS.md)           |
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

C++ policy examples and the report contracts live in
[quality_gates](../quality_gates/README.md); their implementations ship in
`alphus.gates.cpp`. Tests for those engines live in `tests/` and run in the
same Alphus suite as the Python and repository gates.

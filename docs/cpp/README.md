# C++ quality gate references

Alphus implements its C++ checkers in `src/alphus/gates/cpp/`. This folder
contains their detailed guides and evidence contracts. The example JSON policy
inputs live in [`examples/cpp/policies/`](../../examples/cpp/policies/); each
consumer should copy and calibrate them for its own source tree and build.

| Guide                                               | Scope                                                      |
| --------------------------------------------------- | ---------------------------------------------------------- |
| [C++ quality overview](../CPP-QUALITY.md)           | Profiles and consumer workflow                             |
| [Common quality](CPP-COMMON-QUALITY.md)             | Source, graph, impact, test, package, and verdict evidence |
| [Artifact quality](CPP-ARTIFACT-QUALITY.md)         | Binary budgets and comparable-run baselines                |
| [Quality coverage](CPP-QUALITY-GATE-COVERAGE.md)    | Portable checks and provisional review signals             |
| [Portability contract](QUALITY-GATE-PORTABILITY.md) | Consumer adapters and report contracts                     |
| [Worktree hygiene](WORKTREE-HYGIENE.md)             | Local worktree inventory and budgets                       |

Install Alphus in the consumer's quality-tool environment to run the checkers:

```shell
python -m pip install -e /path/to/alphus
python -m alphus.gates.cpp.cpp_common_quality --help
python -m alphus.gates.cpp.cpp_advisory_quality --help
python -m alphus.gates.cpp.cpp_artifact_quality --help
python -m alphus.gates.vcs.worktree_hygiene --help
```

From the Alphus checkout, run the C++ tests:

```shell
python -m pytest tests/gates/cpp/test_cpp_quality_engine.py
python -m pytest tests/gates/cpp/test_cpp_quality.py
```

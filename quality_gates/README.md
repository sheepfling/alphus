# C/C++ quality gate examples

Alphus installs the C++ engines under `alphus.gates.cpp`. This directory holds
example policies and detailed evidence contracts; it contains no second copy
of the engines. Install Alphus in the consumer quality environment, then copy
and calibrate the JSON policies for that consumer. C++ build outputs and target
names remain consumer owned.

| Path                                | Purpose                                                   |
| ----------------------------------- | --------------------------------------------------------- |
| `examples/`                         | Policy examples that require consumer limits and evidence |
| `docs/CPP-COMMON-QUALITY.md`        | Source, graph, impact, test, package, and verdict inputs  |
| `docs/CPP-QUALITY-GATE-COVERAGE.md` | Portable checks and provisional C/C++ review signals      |
| `docs/CPP-ARTIFACT-QUALITY.md`      | Binary artifact budgets and baselines                     |
| `docs/WORKTREE-HYGIENE.md`          | Local worktree inventory and budgets                      |
| `docs/QUALITY-GATE-PORTABILITY.md`  | Consumer adapter and report contracts                     |

```shell
python -m pip install -e /path/to/alphus
python -m alphus.gates.cpp.cpp_common_quality --help
python -m alphus.gates.cpp.cpp_advisory_quality --help
python -m alphus.gates.cpp.cpp_artifact_quality --help
python -m alphus.gates.vcs.worktree_hygiene --help
```

From this checkout, run `python -m pytest tests/gates/cpp/test_cpp_quality_engine.py`
for the engine fixtures and `python -m pytest tests/gates/cpp/test_cpp_quality.py`
for profile integration.

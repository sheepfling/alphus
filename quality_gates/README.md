# Portable quality gates

This directory is the reusable unit. Copy the entire `quality_gates/` tree into
another repository, or invoke the scripts from this checkout. It contains only
standard-library Python checkers, example policies, their fixtures, and
consumer-neutral documentation.

| Path | Contents |
| --- | --- |
| `bin/` | Artifact, source/build/test/package, and worktree checkers |
| `examples/` | Illustrative policies that each consumer must calibrate |
| `docs/` | Input contracts, gate behavior, and integration guidance |
| `tests/` | Portable adversarial fixtures |

From a repository root containing this directory:

```powershell
python quality_gates/bin/cpp_common_quality.py --help
python quality_gates/bin/cpp_artifact_quality.py --help
python quality_gates/bin/worktree_hygiene.py --help
python -m unittest quality_gates.tests.test_cpp_quality_portable
```

Start with the [porting contract](docs/QUALITY-GATE-PORTABILITY.md). Keep
consumer-specific adapters, target names, test selectors, thresholds, CI
wiring, and generated reports outside this directory. The example policies
are templates; their paths and budgets are not ready-made approvals for a
new project.

# C++ quality gates

Alphus includes reusable C++ source/build/test/package and binary-artifact
checkers in `alphus.gates.cpp`. The language-neutral profile
runner coordinates their module entry points as command steps, keeping their machine-
readable reports and exit codes intact while C++ policy stays separate from
the TOML profile policy.

## Start with source and artifact profiles

Install Alphus, then copy `examples/cpp/quality-gates.toml` into the C++ repository. Copy and calibrate
`quality_gates/examples/cpp-common-quality.example.json` as
`cpp-common-quality.json`, and
`quality_gates/examples/cpp-artifact-policy.example.json` as
`cpp-artifact-policy.json`. The example JSON values are starting points; each
repository should set its own source scope, target counts, size limits, and
artifact paths.

Install Alphus in the repository's quality-tool environment and run the source
gate before building:

```sh
alphus --root . --config quality-gates.toml --run --profile cpp-source
```

After producing the configured build tree, run its artifact budget:

```sh
alphus --root . --config quality-gates.toml --run --profile cpp-artifacts
```

The composed `cpp` profile runs both. `--json` retains each checker report in
the command step's `stdout`, reports each exit code, and returns a combined
profile status. A nonzero native gate exit fails the profile.

The supplied source gate checks C/C++ file ownership, expanded implementation
size, and single-consumer fragments. The artifact gate inventories executables
and libraries and can enforce size budgets, debug-section limits, and
comparable-run growth. Start with the
[porting contract](../quality_gates/docs/QUALITY-GATE-PORTABILITY.md) and
[common checks guide](../quality_gates/docs/CPP-COMMON-QUALITY.md) before
enabling build-graph, test-traceability, package, or aggregate-verdict checks.
Those checks need evidence from the consumer's actual build, test, and package
commands; their example policies deliberately do not invent it.

## Add build and test evidence

The common checker exposes `manifest`, `run-build`, `graph`, `tests`,
`package`, and `verdict` subcommands. Add them as ordered command steps. For
example, once a CMake build and CTest run have produced fresh reports, a
consumer can add a step like this:

```toml
[[orchestration.steps]]
kind = "command"
name = "C++ target graph"
argv = [
  "{python}", "-m", "alphus.gates.cpp.cpp_common_quality", "graph",
  "{root}/build", "--config", "{root}/cpp-common-quality.json",
  "--manifest", "{root}/out/quality/build-manifest.json",
  "--output", "{root}/out/quality/graph.json",
]
```

Use one run ID and the same manifest across evidence-producing steps. The
portability guide describes CMake File API, CTest/JUnit, installed-package,
and verdict inputs, including the evidence required for them to pass.

The C++ engine fixture suite tests the installed modules directly. Run it with
`python -m pytest tests/test_cpp_quality_engine.py` from the
Alphus checkout. The Alphus integration tests exercise positive and negative
source and artifact profiles against consumer fixtures.

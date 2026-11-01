# C++ quality gates

Alphus includes reusable C++ source/build/test/package and binary-artifact
checkers in `alphus.gates.cpp`. The language-neutral profile
runner coordinates their module entry points as command steps, keeping their machine-
readable reports and exit codes intact while C++ policy stays separate from
the TOML profile policy.

## Start with source and artifact profiles

Install Alphus, then copy `examples/cpp/quality-gates.toml` into the C++
repository. Copy the [JSON policy examples](../examples/cpp/policies/) as
`cpp-common-quality.json`, `cpp-artifact-policy.json`, and
`cpp-static-archive-policy.json`. These are starting points; each repository
should set its own source scope, target counts, size limits, and artifact
paths. The commands below use the copied filenames in the consumer checkout.

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

Each installed C++ command supports `--format plain`, `--format rich`, and
`--format json`. Without an explicit format, commands print JSON when no
`--output` artifact path is given and a plain summary when a JSON artifact is
written. All three modes use the same report data and exit status. For example:

```shell
python -m alphus.gates.cpp.cpp_artifact_quality scan build --no-sections --format rich
python -m alphus.gates.cpp.cpp_artifact_quality scan build --no-sections --format json
```

## Keep a C++ report history

Set one history directory before running a C++ profile. This enables immutable
records for the common, artifact, and advisory C++ commands without adding a
history setting to every profile step. For local runs, the Git common directory
is shared by linked worktrees and is not part of the tracked source tree:

```powershell
$common = git rev-parse --path-format=absolute --git-common-dir
$env:ALPHUS_CPP_HISTORY_DIR = Join-Path $common "alphus/cpp-history"
alphus --root . --config quality-gates.toml --profile cpp
```

An individual command can use `--history-dir PATH` instead. If a build
directory lies outside the Git checkout, also pass `--history-root CHECKOUT`
so branch and worktree attribution comes from the intended source repository.
Each run writes a new JSON record under `PATH/YYYY/MM/`; the normal
`--output` report keeps its schema and location. Records include the complete
report, a SHA-256 of its JSON payload, a unique record ID, the run ID if
supplied, launch and completion timestamps in UTC with an explicit `Z` offset,
and a monotonic elapsed duration. Provenance records the checked out revision,
branch, worktree path, launch-time dirty state, and launcher. Branch is `null` for detached HEAD;
worktree is `null` outside Git, with `requested_root` retained. `actor_source` distinguishes an OS account from
`GITHUB_ACTOR`, `GITLAB_USER_LOGIN`, or an explicit `ALPHUS_RUN_ACTOR` override.
Git author identity is not treated as the person who launched the check.
Archive paths are printed to stderr when recording is enabled, including when
a quality gate reports a failure.

The `alphus-cpp-advisory-quality trend` command reads archived impact
reports. With `ALPHUS_CPP_HISTORY_DIR` set, the starter `cpp-trends` profile
reads that same directory. It compares runs on the same branch with matching
configuration, toolchain, target lists, and input paths. Input hashes and
source revisions stay in the snapshot trace so normal source changes can form
a trend. Worktree and actor
remain in each snapshot's trace. Use `--branch`, `--worktree`, or `--actor`
to select a narrower series. Older direct impact snapshots still work when they contain an explicit timezone-aware
`created_at_utc`. Missing or timezone-free timestamps are rejected rather than
silently replaced with file modification time.

The Git common directory survives branch changes and linked worktree removal
within the same clone. CI jobs and replacement clones need an external artifact
store or a retained `ALPHUS_CPP_HISTORY_DIR`; upload that directory after the
profile if those runs should remain in the historical series. The history
records contain local worktree paths and account names, so choose an artifact
store with appropriate access.

The supplied source gate checks C/C++ file ownership, expanded implementation
size, and single-consumer fragments. The artifact gate inventories executables
and libraries and can enforce size budgets, debug-section limits, and
comparable-run growth. Start with the
[porting contract](cpp/QUALITY-GATE-PORTABILITY.md) and
[common checks guide](cpp/CPP-COMMON-QUALITY.md) before
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
`python -m pytest tests/gates/cpp/test_cpp_quality_engine.py` from the
Alphus checkout. The Alphus integration tests exercise positive and negative
source and artifact profiles against consumer fixtures.

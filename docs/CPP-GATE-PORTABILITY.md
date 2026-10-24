# Using the gates in another C++ repository

Copy `portable_gates/cpp/` into the consumer repository; copy
`portable_gates/repository/` only if worktree hygiene is needed. The Python
files are organized as importable packages but can also run directly. They
accept consumer-supplied evidence and policy. Install Alphus in the consumer's
quality-tool environment to coordinate them through profile command steps.
Start from calibrated copies of
[`artifact-policy.example.json`](../examples/cpp/artifact-policy.example.json),
[`static-archive-policy.example.json`](../examples/cpp/static-archive-policy.example.json),
and [`common-quality.example.json`](../examples/cpp/common-quality.example.json).
The examples need the consumer's real evidence, paths, and limits. Keep build,
test, and package adapters in the consumer repository.

- **Source ownership:** the consumer supplies source include scope, size
  limits, and documented growth guards.
- **Artifact size:** the consumer supplies profile-specific byte and count
  budgets and a comparable baseline.
- **Build graph:** the consumer supplies target IDs, types, compiled source
  counts, dependencies, and optional compile fanout.
- **Test traceability:** the consumer supplies real selectors, source anchors,
  mapping IDs, or an internal-test classification.
- **Installed package:** the consumer supplies required files, package paths,
  and unchanged-binary result evidence.
- **Worktree hygiene:** the consumer supplies storage roots, workstation count
  and byte budgets, and known checkout locations.
- **Verdict:** the consumer supplies build and test outcomes, run ID, source
  root, evidence freshness, and exact coverage comparisons.

All policy checks report `schema: 1` and a pass result. The common and worktree
checkers use top-level `passed`, `findings`, `metrics`, and `run_id`. The
artifact policy result is currently under `gate.passed`; set that dotted
`pass_field` in the verdict policy. Exit codes are `0` for pass, `1` for a
quality finding, and `2` for invalid input or unreadable evidence. Treat `2`
as a failed pipeline step too.

## Consumer adapter boundary

Build-system adapters should emit the normalized report shapes documented in
[C++ common quality](CPP-COMMON-QUALITY.md), or use the built-in CMake/CTest
readers. An adapter may translate native names and output locations, but it
must not invent test execution, mapping, package binding, or a passing build
result. Use one run ID across its reports. Require fresh evidence and a
nonempty minimum count so a wrong or empty output directory fails closed.
The aggregate verdict should require each expected report's schema and gate
identity where available, and must use distinct paths for distinct checks.
The built-in manifest producer uses Git for revision and dirty-state evidence;
its schema contains no consumer names. A consumer using another source system
needs an adapter that emits an equivalent source snapshot and verifier before
claiming live source-state validation. The manifest input hashes and report
digest bindings work independently of the build system.

Keep budgets by build profile and toolchain. Compare Debug artifacts to Debug
artifacts, and compare the same target scope across runs. A first-party static
archive or executable count threshold from one project is a starting point,
not a universal C++ limit. Calibrate from a reviewed baseline, then add an
absolute cap so an already oversized baseline cannot bless further growth.

The worktree gate belongs on a developer host or scheduled local maintenance
run. Supply each dedicated storage root so the checker measures leftover
folders as well as registered checkouts, even if their `.git` marker is gone.
Its report is an inventory and budget signal; it never removes a checkout.
The owning app or a deliberate Git closeout handles preservation and cleanup.

## Hardening sequence

The portable checker now binds reports to a build manifest and compares exact
executable and test-selection sets in the aggregate verdict. Its small fixture
suite exercises the generic pass path and adversarial evidence. A consumer can
use `run-build` to capture the real build exit code, or emit the same report
from its CI runner. Each consumer still needs its actual selected targets and
an adapter fixture using its own build and test output formats.

Run `python -m pytest tests/test_cpp_quality_portable.py` before copying or changing the
checker. The fixtures cover normalized reports, CMake File API, CMake cache,
CTest/JUnit input, the build-command wrapper, and missing or contradictory
evidence. They use a synthetic source-state provider so they can run without
creating a test repository's Git metadata; the production manifest producer
uses Git directly.

The next increments are:

1. Capture toolchain identity directly from the compiler and linker invocation
   in each consumer adapter, then compare it with the manifest label. Also
   record the actual selected build targets rather than a manually typed list.
2. Add a verifier for non-Git source systems before claiming live source-state
   validation there. A dirty Git checkout is tracked by content hash, but a
   clean CI checkout remains the easiest reproducible baseline.
3. Add trend and anomaly review after deterministic coverage is trustworthy.
   Compare the same profile, target set, and toolchain; treat an AI explanation
   as a hypothesis until a measurement confirms it.

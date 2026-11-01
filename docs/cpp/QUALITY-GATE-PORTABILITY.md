# Porting the quality gates to another C++ consumer

For an overview of portable checks, advisory signals, and consumer-owned
architecture rules, see the [C/C++ quality-gate coverage map](CPP-QUALITY-GATE-COVERAGE.md).

The reusable checkers ship in the Alphus distribution under
`alphus.gates.cpp`. Install Alphus in the consumer quality environment and
copy calibrated copies of
[`cpp-artifact-policy.example.json`](../../examples/cpp/policies/cpp-artifact-policy.example.json),
[`cpp-static-archive-policy.example.json`](../../examples/cpp/policies/cpp-static-archive-policy.example.json),
and [`cpp-common-quality.example.json`](../../examples/cpp/policies/cpp-common-quality.example.json).
The examples intentionally fail until the consumer supplies real evidence,
paths, and limits. Keep each consumer's build, test, and package adapters outside this directory.

| Gate               | Portable input                                                            | Consumer supplies                                                                                               |
| ------------------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Source ownership   | Repository root and source policy                                         | Include scope, size limits, documented growth guards                                                            |
| Artifact size      | Output directory, optional `objdump`, size policy                         | Profile-specific byte and count budgets, comparable baseline                                                    |
| Build graph        | Normalized target JSON, or CMake File API                                 | Target IDs, types, compiled source counts, dependency IDs, optional compile fanout report                       |
| Include impact     | Selected source inventory, literal include edges, optional compile report | Source scope and calibrated caps for transitive dependents, dependency weight, hotspots, and measured TU fanout |
| C/C++ style review | Source inventory and local text                                           | Provisional include candidates, repeated text windows, file size, and regex complexity signals                  |
| Include trends     | Directory of impact reports bound to build manifests                      | Comparable configuration, toolchain, selected targets, and named input hashes                                   |
| Test traceability  | Case manifest, discovered-name JSON, JUnit or normalized execution JSON   | Real selectors, source anchors, mapping IDs or internal classification                                          |
| Installed package  | Install prefix, binding JSON or CMake cache, consumer result              | Required files, package path keys, unchanged binary hash and result evidence                                    |
| Worktree hygiene   | Git repository and labeled dedicated storage roots                        | Workstation count and byte budgets, known checkout locations, owner-specific archive procedure                  |
| Verdict            | Required gate reports and build manifest                                  | Build/test outcome report, run ID, source root, freshness window, exact coverage comparisons                    |

All policy checks report `schema: 1` and a pass result. The common and worktree
checkers use top-level `passed`, `findings`, `metrics`, and `run_id`. The
artifact policy result is currently under `gate.passed`; set that dotted
`pass_field` in the verdict policy. Exit codes are `0` for pass, `1` for a
quality finding, and `2` for invalid input or unreadable evidence. Treat `2`
as a failed pipeline step too.

The provisional C/C++ review commands are separate from pass/fail policy
checks. They emit `status: "provisional"`, informational findings, and
`blocking: false`; direct invocation exits successfully by default. Their
optional nonzero-on-finding flags belong in orchestration steps marked
`rollout = "provisional"`.

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

The installed checker binds reports to a build manifest and compares exact
executable and test-selection sets in the aggregate verdict. Its small fixture
suite exercises the generic pass path and adversarial evidence. A consumer can
use `run-build` to capture the real build exit code, or emit the same report
from its CI runner. Each consumer still needs its actual selected targets and
an adapter fixture using its own build and test output formats.

Run `python -m pytest tests/gates/cpp/test_cpp_quality_engine.py` before changing the
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
3. Build richer anomaly review on top of the provisional impact trend report.
   Keep configuration, targets, toolchain, and named inputs comparable; treat
   an explanation as a hypothesis until a measurement confirms it.

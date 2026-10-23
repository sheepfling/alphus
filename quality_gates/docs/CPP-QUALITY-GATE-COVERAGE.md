# C/C++ quality-gate coverage

This map describes the portable checks in Alphus, advisory signals that are
not suitable as pass/fail gates, and rules that belong in a consuming
repository's own policy. The aim is reusable C/C++ quality tooling; thresholds,
build adapters, and architecture rules remain consumer-owned.

## Portable checks in Alphus

| Quality concern | Portable signal | Alphus coverage |
| --- | --- | --- |
| Include dependency impact | Direct and transitive include reach, dependency weight, blast radius, hotspot and prioritization ratios, cycle participation, and optional measured translation-unit fanout | The `impact` command in [C++ common quality](CPP-COMMON-QUALITY.md) reads a selected source inventory and an optional build-system-neutral compile report. |
| Source size and fragment ownership | Physical and expanded lines/bytes, implementation fragments, and ownership exceptions | The `source` gate measures growth and guards fragment ownership. |
| Build graph and target fanout | Target identities, dependency edges, compiled source counts, executable coverage, and optional header fanout | The `graph` gate consumes normalized target data or CMake File API data. |
| Test traceability | Declared cases, discovered selectors, source anchors, mappings, and actual execution results | The `tests` gate accepts normalized evidence, CTest JSON, or JUnit. |

The impact gate keeps the useful include-graph signals together: direct and
transitive dependents, transitive dependencies, dependency weight, blast
radius, heaviness, hotspot score, indirectness, include amplification,
direct-use ratio, easy-win score, foundation score, cycle participation, and
optional measured translation-unit fanout. These values prioritize review;
consumers calibrate their own thresholds from comparable baselines.

## Advisory signals

These checks can help developers find cleanup opportunities, but their results
do not prove a defect and should not fail CI by themselves:

- Historical trends can identify worsening metrics once snapshots are bound to
  the same profile, targets, toolchain, source revision, and run identity.
- Include-name and token heuristics can suggest unused includes, but cannot
  account reliably for macros, templates, conditional compilation, or
  transitive declarations. Require a successful compile after removal.
- Repeated text windows can suggest shared logic, but similarity does not prove
  common ownership or behavior. Review the contexts before consolidation.
- Regex-based complexity estimates can miscount C++ syntax, comments, and
  macros. Use parser-backed metrics before making complexity a gate.

Alphus does not currently provide a longitudinal trend contract or these
heuristic reports. They remain possible follow-on utilities with report-only
semantics.

## Consumer-owned architecture rules

Rules about a particular variant schema, UI boundary, host-state ownership,
hardware behavior, exception policy, units, or concurrency model belong in the
consumer's policy or analyzer. The same is true for target names, build
options, compiler-specific suppressions, and documentation ownership. Alphus
accepts normalized build and test evidence so consumers can keep those details
in adapters without making them universal policy.

## Scope of the current change

The current feature branch adds the deterministic include-impact gate and
documents how it fits beside Alphus's existing generic C++ checks. It does not
claim that every possible C/C++ advisory tool or architecture rule has been
implemented.

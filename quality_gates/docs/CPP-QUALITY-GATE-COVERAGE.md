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

- Historical trends can identify worsening metrics when snapshots use the same
  configuration, targets, toolchain, and named input hashes. Each row records
  its own source revision and run identity for traceability.
- Include-name and token heuristics can suggest unused includes, but cannot
  account reliably for macros, templates, conditional compilation, or
  transitive declarations. Require a successful compile after removal.
- Repeated text windows can suggest shared logic, but similarity does not prove
  common ownership or behavior. Review the contexts before consolidation.
- Regex-based complexity estimates can miscount C++ syntax, comments, and
  macros. Use parser-backed metrics before making complexity a gate.

Alphus provides these as the `cpp_advisory_quality` command. Its `style`
subcommand emits low-confidence findings with `severity: info` and
`blocking: false`; the `trend` subcommand compares impact snapshots only when
their build context matches. The `examples/cpp/quality-gates.toml` file exposes
them through opt-in `cpp-style`, `cpp-trends`, and `cpp-advisory` profiles with
`rollout = "provisional"`. A provisional failure is visible in the profile
report and does not fail the aggregate run.

Run the style review directly to write a report; it exits successfully by
default even when candidates exist:

```shell
python -m alphus.gates.cpp.cpp_advisory_quality style . \
  --output out/quality/cpp-style.json
```

To make candidates show as a provisional failure in an Alphus profile, pass
`--fail-on-findings` and set the command step's `rollout` to `provisional`, as
the example profile does. The candidates remain informational and do not fail
the aggregate run.

For trends, retain each `impact` report under one snapshot directory. Include
the build manifest so Alphus records comparable build context:

```shell
python -m alphus.gates.cpp.cpp_common_quality impact . \
  --config cpp-common-quality.json --run-id "$RUN_ID" \
  --manifest out/quality/build-manifest.json \
  --output "out/quality/cpp-impact-snapshots/$RUN_ID.json"
python -m alphus.gates.cpp.cpp_advisory_quality trend \
  out/quality/cpp-impact-snapshots \
  --output out/quality/cpp-impact-trend.json
```

The trend command starts a new series when configuration, toolchain, selected
targets, expected executables, or named input hashes change. Source revisions
are expected to differ; the report records each revision and manifest digest.
With fewer than two compatible snapshots it reports `insufficient-history`.
`--fail-on-worsening` returns a provisional signal for increases in the latest
snapshot pair.

## Consumer-owned architecture rules

Rules about a particular variant schema, UI boundary, host-state ownership,
hardware behavior, exception policy, units, or concurrency model belong in the
consumer's policy or analyzer. The same is true for target names, build
options, compiler-specific suppressions, and documentation ownership. Alphus
accepts normalized build and test evidence so consumers can keep those details
in adapters without making them universal policy.

## Scope of the current change

The current feature branch adds the deterministic include-impact gate and
provisional style/trend utilities beside Alphus's existing generic C++ checks.
Consumer-specific architecture rules remain in the consuming repository.

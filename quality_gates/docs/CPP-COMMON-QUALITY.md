# Common C++ quality checks

`alphus.gates.cpp.cpp_common_quality` is the installed C++ common checker. It provides the `source`, `graph`, `impact`, `tests`, `package`, and `verdict` checks, which emit a common JSON result with `passed`, `findings`, `metrics`, and an optional `run_id`. Install Alphus and adapt [the example policy](../examples/cpp-common-quality.example.json) in a C++ repository. Values in that file are illustrative; its test and package sections intentionally need project-specific cases and paths before they can pass. Each command exits `0` for pass, `1` for a failed gate, and `2` for invalid configuration or unreadable evidence. See the [porting contract](QUALITY-GATE-PORTABILITY.md); consumer-specific producers and mappings belong in an adapter in the consuming repository.

Use one run ID across all commands, such as the CI build ID. For a local shell session, run `RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)` once before the commands below.

## Bind evidence to one build

Create a build manifest before building. The built-in producer records the Git
revision, a hash of tracked changes and nonignored untracked files, the build
configuration and toolchain label, selected targets, expected executable
targets, and SHA-256 hashes of named inputs. Supply meaningful configuration
and toolchain values from the actual build. Repeat `--input` for the build
definition, policy, toolchain file, and other inputs that must remain fixed.

```shell
python -m alphus.gates.cpp.cpp_common_quality manifest --source-root . --run-id $RUN_ID --configuration Debug --toolchain "compiler-version-and-flags" --artifact-root build --target consumer --expected-executable consumer --input quality_gates/examples/cpp-common-quality.example.json --require-clean --output out/quality/build-manifest.json
```

Pass `--manifest out/quality/build-manifest.json` to each source, graph, test,
package, and artifact command. Each output carries the SHA-256 of the exact
manifest bytes. The verdict checks that digest on every required report and
recomputes the Git source state and input file hashes. Keep the manifest and
reports in ignored build output so writing them does not change the recorded
source state. Omit `--require-clean` for a local dirty checkout; its recorded
state must still match at verdict time. The manifest binds the evidence, but
its toolchain label and selected targets are producer claims; the consumer
adapter must supply them from its actual build invocation.

The optional `run-build` wrapper executes a command without a shell and writes
the generic build report from its real exit code. For example:

```shell
python -m alphus.gates.cpp.cpp_common_quality run-build --manifest out/quality/build-manifest.json --run-id $RUN_ID --cwd . --output out/quality/build.json -- cmake --build build --target consumer
```

It exits nonzero when the build fails and still writes `passed:false`, the
command, exit code, duration, and manifest digest. Existing CI build runners
may instead emit the same schema from their captured process result.

## Source ownership and size

```shell
python -m alphus.gates.cpp.cpp_common_quality source . --config quality_gates/examples/cpp-common-quality.example.json --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/source.json
```

The source check inventories Git-tracked and nonignored untracked C/C++ files. Outside Git, it scans the supplied root. `include` and `exclude` glob lists define scope. It measures physical lines and bytes, then recursively adds locally included implementation fragments to the owning file's expanded totals. Both `hard_lines` and `hard_bytes` apply to the expanded owner, so splitting a large `.cpp` into a single included chunk does not lower its measured size.

The check fails on any `#include` of a `.c`, `.cc`, `.cpp`, or `.cxx` source, even if the included path cannot be resolved. It also fails on a `.inc`, `.inl`, `.ipp`, or `.tpp` fragment with fewer than two direct consumers. A large header with one direct consumer is a review warning; set `single_consumer_header_lines` to tune that signal. This is a structural check: a preprocessor branch may be inactive, and a single header may be a legitimate interface. Review findings in context.

`legacy` exceptions need a reason and `max_physical_lines`; they may also set `max_expanded_lines` and `max_expanded_bytes`. The old file cannot grow past its recorded bounds. A rare single-consumer fragment exception belongs in `fragment_exceptions` with a reason and `max_lines`. Such an exception documents ownership; it should not be used to justify moving ordinary code out of its sole owner. Warnings remain visible in JSON; errors fail the gate.

The installed checker covers `.inc`, `.inl`, `.ipp`, and `.tpp` fragments and reports large one-consumer headers for review. Project-specific source-size policies can run beside it.

## Build graph and fanout

The build-system-neutral input is `--graph-report` with this shape:

```json
{
  "schema": 1,
  "run_id": "build-123",
  "configuration": "Debug",
  "targets": [
    {
      "id": "core",
      "name": "core",
      "type": "static_library",
      "compiled_source_count": 20,
      "dependencies": []
    },
    {
      "id": "consumer",
      "name": "consumer",
      "type": "executable",
      "compiled_source_count": 2,
      "dependencies": ["core"],
      "artifacts": ["bin/consumer.exe"]
    }
  ]
}
```

Target `id` values must be unique. Dependencies reference those IDs. For each
executable, `artifacts` lists its output binary paths relative to the artifact
scanner's root, excluding symbol and import-library files. Set
`require_executable_artifacts:true` for a complete-build verdict. Produce this
report from any build system and pass the same run ID to the gate. The optional
`--compile-report` uses `{"records":[...],"header_fanout":[{"path":"...","translation_units":2}]}`. Each `records` entry represents one measured translation unit. Evidence older than `max_evidence_age_seconds` fails.

For CMake, the checker also reads its File API codemodel directly. Ask CMake for it before configuring:

```shell
mkdir -p build/.cmake/api/v1/query
touch build/.cmake/api/v1/query/codemodel-v2
cmake -S . -B build -G Ninja
python -m alphus.gates.cpp.cpp_common_quality graph build --config quality_gates/examples/cpp-common-quality.example.json --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/graph.json
```

The graph check counts executable targets and compiled sources per executable, and reports how many executables depend on each static-library target. Build-system dependency data may include ordering dependencies; a high fanout is a review signal and must be confirmed against link commands before claiming duplicate code. `max_executable_targets`, `max_executables_per_static_library`, and `max_sources_per_executable` are profile-specific limits. A missing or ambiguous report fails closed.

For header fanout after a Ninja build, supply a JSON report with `records` and `header_fanout` arrays. A repository adapter can produce it from compiler timing logs and dependency files:

```shell
python -m alphus.gates.cpp.cpp_common_quality graph --graph-report out/quality/targets.json --compile-report out/quality/compile.json --config quality_gates/examples/cpp-common-quality.example.json --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/graph.json
```

`min_measured_translation_units` guards against an empty timing sample. Compare fanout within the same target scope. Raw compile duration remains a trend and investigation trigger unless the machine, toolchain, profile, and target selection are controlled.

## Include dependency impact and blast radius

Run the impact command to scan selected C/C++ files and build a local include
graph. It reports direct and transitive dependents, transitive dependencies, a
hotspot score (blast_radius * heaviness), indirectness, include
amplification, direct-use ratio, easy-win and foundation scores, and cycle
participants. The static graph follows literal project includes that resolve
inside the selected source inventory. Preprocessor branches and generated headers
can make it approximate.

    python -m alphus.gates.cpp.cpp_common_quality impact . \
      --config quality_gates/examples/cpp-common-quality.example.json \
      --compile-report out/quality/compile.json --run-id $RUN_ID \
      --manifest out/quality/build-manifest.json --output out/quality/impact.json

The compile report uses the same records and header_fanout arrays as the graph
gate. Its header_fanout counts translation units that actually depend on each
project header, so it provides the measured compile blast radius; the source
graph's blast_radius counts transitive source/header dependents. The input format
is build-system neutral. A CMake/Ninja adapter, Make adapter, Bazel adapter, or
other compiler dependency collector can emit it. Paths in header_fanout are
relative to the source root (absolute paths inside it are also accepted). Run
IDs and evidence freshness are checked when a compile report is supplied.

The policy can cap max_blast_radius, max_heaviness, max_hotspot_score,
max_indirectness, max_include_amplification, and measured
max_translation_unit_fanout. Indirectness and include amplification surface
umbrella headers with broad transitive reach or dependency weight. These are
calibration points, not universal C++ limits; establish them from a reviewed
baseline, then retain an absolute ceiling so a poor baseline cannot
authorize unbounded growth. The report ranks the 20 largest combined hotspots
for review. A smaller graph score is useful only when the change preserves clear
ownership and interfaces.

Indirectness is transitive dependents divided by direct dependents.
Include amplification is transitive dependencies divided by direct includes.
Direct-use ratio is direct dependents divided by transitive dependents.
Easy-win score is dependency weight divided by blast radius; foundation score
is blast radius divided by dependency weight. Ratios use a denominator of at
least one. These are prioritization signals, not claims that a header should be
removed or split.

For each refactor batch, record a one-line hypothesis and baseline from the same
source/build snapshot, then measure the same scope afterward. Keep the batch
when it improves a named metric or has a documented ownership/interface reason;
revert churn-only changes, and never duplicate code merely to lower fanout.
Stop after two consecutive flat batches, or when the remaining work requires
intrusive API or ownership changes. Record the final measurements and follow-on
plan. These batch stop rules keep metric-driven refactors bounded and reviewable.

## Test selection and traceability

Fill `tests.cases` with entries such as:

```json
{
  "id": "case-1",
  "selector": "my.case.1",
  "source": "tests/case_1.cpp",
  "source_anchor": "TEST_CASE(\"my.case.1\"",
  "mappings": ["REQ-1"]
}
```

An internal test with no normative mapping uses `"classification":"internal"`. Set `known_mapping_ids` to reject misspelled mapping IDs, and `require_mappings` when every listed test must have one. With `require_source_anchor:true`, every row must name an exact string found in its source file; this catches stale pointers after extraction. The gate verifies identifiers, exact selectors, source paths, mappings or internal classification, discovered names, and executed cases. It cannot decide whether a requirement's text or section is semantically correct; that belongs to a project adapter and human review.

Any test runner can supply `{"run_id":"build-123","tests":[{"name":"my.case.1"}]}` as `--inventory-json` and `{"schema":1,"run_id":"build-123","cases":[{"name":"my.case.1","status":"passed"}]}` as `--execution-json`. Other statuses are `failed`, `error`, and `skipped`. A normalized execution report must carry the same run ID when one is passed to the gate. CTest's `--show-only=json-v1` output and JUnit XML are built-in alternatives:

```shell
ctest --test-dir build -R '^my[.]case[.]1$' --show-only=json-v1 > out/quality/ctest.json
ctest --test-dir build -R '^my[.]case[.]1$' --output-junit out/quality/ctest-junit.xml
python -m alphus.gates.cpp.cpp_common_quality tests . --config quality_gates/examples/cpp-common-quality.example.json --inventory-json out/quality/ctest.json --junit out/quality/ctest-junit.xml --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/tests.json
```

Use the same selector for discovery and execution. With `allow_extra_tests:false`, discovered and executed names must match the manifest exactly. This detects a reused build that silently expands a focused selection. `min_cases` prevents an empty declaration from passing; failures, errors, and skips fail the gate. Preserve the result from the same run as the inventory.

## Installed package and ABI smoke

Set `package.prefix` to the intended install tree. Use `binding_report` with `binding_keys`, or use a CMake consumer's `cache` with `cache_path_keys`. A normalized binding report has `{"schema":1,"run_id":"build-123","bindings":{"package_config":"<installed-config-directory>","api_include":"<installed-include-directory>"}}`. The checker rejects paths outside the install prefix and missing required installed artifacts. Add `package.consumer` with `executable`, `expected_sha256`, `result_json` or `junit`, and `min_cases` after building an external consumer once. Capture the SHA-256 before changing the provider, then run that unchanged consumer against the new shared library. The checker verifies the binary hash and passing, recent evidence; it does not itself prove which shared library the operating-system loader selected. Record the loader-resolved library path in the consumer test or package adapter when ABI compatibility is being claimed.

```shell
python -m alphus.gates.cpp.cpp_common_quality package . --config quality_gates/examples/cpp-common-quality.example.json --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/package.json
```

## One verdict for CI

Run [the artifact budget](CPP-ARTIFACT-QUALITY.md) with the same `--run-id`, then aggregate all required reports:

```shell
python -m alphus.gates.cpp.cpp_artifact_quality check build --policy quality_gates/examples/cpp-artifact-policy.example.json --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/artifacts.json
python -m alphus.gates.cpp.cpp_common_quality verdict --config quality_gates/examples/cpp-common-quality.example.json --run-id $RUN_ID --manifest out/quality/build-manifest.json --output out/quality/verdict.json
```

The `verdict.reports` list names required reports and the JSON field that means pass (`passed` by default, `gate.passed` for artifact reports). `min_reports` counts required entries; optional entries cannot fill the minimum. Two entries cannot reuse the same resolved report path. Set `expected_schema` and, where the producer emits a string gate name, `expected_gate` so a report for one check cannot stand in for another. Missing, stale, failed, wrong-run, wrong-manifest, or wrong-identity evidence fails the aggregate. A legacy report can set `require_run_id:false` or `require_manifest:false` explicitly; keep a short `max_age_seconds` when weakening either binding. Keep build/test outcome separate from quality outcome; the aggregate is the CI quality verdict. Wire it after each producer has created its report, and archive all input reports with the verdict.

`verdict.set_checks` compares string-array fields as exact sets. The example
compares the manifest's expected executables with selected graph targets,
graph output paths with scanned executable paths, and declared test selectors
with discovery and execution. The graph and artifact scans must cover the same
build root and target scope; use a different policy for a first-executable
checkpoint. The `@manifest` report name refers to the supplied manifest.
Missing fields, duplicates, and set differences fail. This is how a partial
build that satisfies a low minimum count is caught. The verdict records the
SHA-256 of each report it read, so an archived verdict identifies the exact
evidence bytes it evaluated.

`verdict.value_checks` compares scalar fields with matching types. The example
checks the graph configuration and artifact scan root against the manifest.

The build report has `{"schema":1,"gate":"build","run_id":"build-123","passed":true,"manifest_sha256":"<digest>"}` after a successful command. A caller-supplied build label alone must not make a quality result pass. The project adapter defines any additional required reports.

## AI-assisted smell review

Give the reviewer the JSON gate reports, the changed-file diff, effective compile and link flags, and the relevant build target graph. Ask it to return a short table with **observation**, **source or artifact evidence**, **likely cause**, **disproving measurement**, and **proposed owner**. Require exact paths and numbers. A claim about duplicate code needs link-command or binary-section evidence; target dependency fanout alone is insufficient.

Review these recurring patterns together:

| Signal                                                          | Follow-up question                                                                                                                                      |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Large owner shrinks while an included fragment appears          | Was cohesive code extracted into a separately compiled `.cpp`, or merely moved behind `#include`? Do all claimed fragment consumers compile and use it? |
| Executable count, archive fanout, or total output bytes jumps   | Which targets and link commands added the copies? Are symbols or DWARF sections duplicated across products?                                             |
| Header fanout or measured translation units jumps               | Which include or target change broadened the dependency graph? Is the timing comparison on the same toolchain and profile?                              |
| Test plan row, discovered selector, or execution case disagrees | Which exact case ran, and which source anchor and requirement mapping prove its scope?                                                                  |
| Package smoke passes after a provider change                    | Was the external consumer binary unchanged, did its bindings select the installed package, and which shared library did the loader resolve?             |

AI findings are review input; deterministic checks decide CI status. Static consumer counts do not prove a fragment is genuinely shared, and file size alone does not prove a source split is cohesive. Keep the specific evidence in the review record.

Worktree buildup is a workstation quality signal. Run the separate read-only
[worktree hygiene gate](WORKTREE-HYGIENE.md) at the end of an isolated work stream
and during periodic local cleanup; with configured storage roots, it measures
ignored build outputs and leftover folders as well as registered checkouts.

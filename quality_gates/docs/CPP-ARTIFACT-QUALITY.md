# C++ artifact quality gate

For source ownership, build-graph, test-selection, package-provenance, and aggregate checks, see [Common C++ quality checks](CPP-COMMON-QUALITY.md).

`alphus.gates.cpp.cpp_artifact_quality` is the installed C++ artifact checker. Install Alphus in the consumer environment and supply a calibrated policy. It inventories executables, shared and static libraries, and separate symbol files under any build directory. File size is always measured; `objdump -h` measures debug and text sections when available.

## Add the gate to a build

After the main static library is built, run the archive policy on its output directory. This catches excessive archive growth before any executable links:

```shell
python -m alphus.gates.cpp.cpp_artifact_quality check build/lib --policy quality_gates/examples/cpp-static-archive-policy.example.json --output build/archive-quality.json
```

After the **first representative executable** links, run the executable policy on its output directory:

```shell
python -m alphus.gates.cpp.cpp_artifact_quality check build/tests --policy quality_gates/examples/cpp-artifact-policy.example.json --output build/artifact-quality.json
```

Run the executable check after the full build to enforce fleet totals. A policy should be copied into the consuming project and calibrated for each build profile; the example's 512 MiB archive, 128 MiB executable, and 64 MiB debug limits are starting values, not universal limits. Use separate policies for Debug, RelWithDebInfo, and release or distribution builds. The check exits `0` on pass, `1` on a budget violation, and `2` on invalid input or a scanning error. An unavailable debug measurement violates any debug byte limit, so it fails closed with exit `1`. The checker prints each failed budget even when writing JSON to a file. Put these commands in CI after their respective build steps; CI should fail on either nonzero exit code.

For a first look without a policy:

```shell
python -m alphus.gates.cpp.cpp_artifact_quality scan build/tests --output build/artifact-inventory.json
```

On Unix, the default scan also recognizes extensionless native executables with the executable bit set. Pass `--include` / `--exclude` glob patterns to narrow a scan; the scanner treats an explicit include list as authoritative. On Windows, `.exe` files are recognized by extension. The default inventory includes macOS `.dSYM` DWARF files. If `objdump` is not on `PATH`, pass `--objdump` with the tool's path. `--no-sections` gives a fast file-size-only inventory. A policy that sets `max_executable_debug_bytes` fails closed when section measurement is unavailable.

For an aggregate build verdict, pass the same `--run-id` and
`--manifest path/to/build-manifest.json` used by the common gates. The artifact
report then carries `manifest_sha256`. Its `totals.executable_paths` list can
be compared with the graph gate's selected executable output paths. Scan the
same build root and target scope for both lists.

The JSON report contains artifact paths and byte counts, debug and text section sizes, build totals, and review signals. Artifact paths are relative to the scanned root. Symbolic-link aliases are skipped so they do not double-count the same file. The `debug_dominant_executables` signal means at least 64 MiB of debug sections and at least half of an executable's bytes are debug sections. This signal is review evidence; the project's policy sets the actual budgets.

Policy values are nonnegative integer bytes, except count limits. The schema 1 `limits` object accepts:

| Limit                                                        | Scope                                                    |
| ------------------------------------------------------------ | -------------------------------------------------------- |
| `min_executable_count`, `max_executable_count`               | Detect a missing output tree or target proliferation     |
| `min_static_library_count`                                   | Detect a missing prelink archive                         |
| `max_static_library_bytes`, `max_total_static_library_bytes` | Bound one archive and all archives                       |
| `max_executable_bytes`, `max_executable_debug_bytes`         | Bound one executable and its measured debug sections     |
| `max_total_executable_bytes`, `max_total_artifact_bytes`     | Bound the executable fleet and all inventoried artifacts |

An archive budget measures archive file bytes; it does not attribute those bytes to debug sections. Inspect representative member objects or their build flags before claiming a cause.

## Detect regressions against a baseline

Store a report from a known good run as a CI artifact and compare a new run with `--baseline path/to/baseline.json`. Add any of these integer byte limits to the policy:

| Limit                               | Detects                                                  |
| ----------------------------------- | -------------------------------------------------------- |
| `max_new_executable_bytes`          | A newly introduced executable that is unexpectedly large |
| `max_executable_growth_bytes`       | Growth in an executable with the same relative path      |
| `max_total_executable_growth_bytes` | Growth across the whole executable fleet                 |

Absolute caps remain useful even with a baseline: a baseline from an already oversized build must not bless the problem. Use `min_executable_count` so a missing or wrong output directory cannot silently pass. Keep baseline and current scan patterns identical. Compare equivalent profiles, platforms, toolchains, and output trees; a changed build configuration needs its own baseline. A baseline is an artifact report, not a policy check result requirement.

Project adapters can record executable count, executable bytes, all artifact bytes, and the largest executables beside compile and link timing history. Run `python -m alphus.gates.cpp.cpp_artifact_quality` when section attribution or a hard budget is needed. Keep the adapter in the consuming repository.

## Common C++ quality sequence

1. **Before linking:** inspect target topology and flags. Flag a large number of small test executables that each link the same static library, especially when the library is built with full debug information. Check the effective compiler flags for the library and each test, not only the test source or link command. Enforce the static archive budget as soon as the archive is built. Keep timing, target count, and configuration in the build record.
2. **After the first link:** measure that executable's total bytes, debug bytes, and text bytes. Enforce the per-executable policy now, while the cause is still local to a small build. A large `-g` static archive can inject its debug sections into each executable. Compiling only the test runner with `-g0` does not remove debug data already in linked objects.
3. **After the full build:** enforce executable count, individual and total byte budgets. Record the largest artifacts, the combined footprint, and the change from a comparable baseline. This catches repeated costs that appear harmless when each target is reviewed alone.
4. **On a schedule or a significant toolchain change:** compare Debug, release, and distributed artifacts separately. Check whether debug symbols are embedded, externalized, compressed, or stripped as intended. External symbol files still consume storage, so include `.pdb`, `.debug`, and `.dwp` in the total artifact budget where applicable. Track compile and link time alongside disk use.

## AI assisted smell review

Give the reviewer the machine-readable report, the policy and baseline, the effective CMake/toolchain configuration, representative compile and link commands, and a target dependency graph or link response file. Ask it to:

- Point to exact artifact paths, byte counts, section measurements, flags, and linked libraries for every finding.
- Separate observed facts from a suspected cause. Similar file sizes alone do not prove duplicate code. Verify repeated static linkage or common debug sections from link commands and section data.
- Identify whether the cost is in executable code, embedded debug sections, static archives, separate symbols, or the number of targets.
- Propose the smallest build change with an expected size effect, then request a before/after measurement under the same configuration.
- Flag suspicious gate configuration: missing minimum count, a stale baseline, mismatched build profiles, debug section budgets with no section tool, or an exclusion broad enough to hide outputs.

The deterministic policy decides CI pass/fail. AI review explains the evidence and suggests changes; it does not override the measured gate. If debug sections dominate executable bytes, investigate compile flags and static linkage before claiming machine-code duplication. Treat a lower-debug-information build, debug section compression, or distribution stripping as separate experiments and retain a full-symbol configuration where development requires it.

A reusable review request is:

> Review the attached artifact report and build evidence as a C++ build-quality smell check. List each observed issue with its exact artifact path, measured bytes, policy limit, effective compile or link flag, and source of evidence. Distinguish observations from hypotheses. Prioritize the earliest gate that could have caught each issue. Recommend one controlled build change per hypothesis and specify the before/after measurements needed to confirm it. Call out missing evidence or gate blind spots. Do not mark a deterministic gate as passed without its actual result.

Trigger this review when a budget fails, a debug-dominant signal appears, the executable count jumps, or the combined footprint grows materially. Archive the report and review beside the build timing record so the next change can be compared under the same profile.

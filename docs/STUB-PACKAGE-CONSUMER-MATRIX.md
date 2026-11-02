# Installed stub consumer calibration

This is one local, installed-wheel calibration row for the `mdutils-stubs`
consumer. It records both the unmodified outcome and a temporary reviewed
fixture adjustment; the adjusted run is not a claim that the unmodified
consumer suite passes three checkers.

| Evidence | Identity |
| --- | --- |
| Consumer source | `sheepfling/mdutils-stubs` commit `777b4b600e128721493999ed48867fa664f1a573` |
| Runtime contract | `mdutils==1.8.1`; upstream source commit `170f7d040ea598672c53015a5db4fab868dacba0` |
| Alphus implementation | PR #68 head `78822f071c0680b68852a2fc6cc9ba2944e14ea2` |
| Checker interpreter | Python 3.11.16, macOS `darwin` arm64; MyPy 2.4.1, Pyright 1.1.414, ty 0.0.91 |
| Target interpreter | Python 3.11.16, macOS `darwin` arm64; `mdutils==1.8.1`, `mypy==2.4.1` |
| Built stub artifact | `mdutils_stubs-1.8.1.0-py3-none-any.whl` |
| Artifact SHA-256 | `90ff56bfe8a1c73c32c45f62abaeda36633c7701b2a9fb99c4c6f31e155fc97f` |

The checker and target environments were separate. The target preinstalled the
runtime and native stubtest tool; Alphus built and installed the consumer wheel
there, then ran all three type checkers from the checker environment. Stubtest
and the runtime smoke ran against the target installation. The artifact
contained the unchanged stub package tree; fixture changes described below
were made only in a disposable source copy.

## Unmodified consumer result

The original positive fixture has three `assert_type(..., type[TextUtils])`
checks for class-object re-exports. MyPy and Pyright accept them, but ty 0.0.91
reports `assert-type-unspellable-subtype` for the class-object form. The
consumer's negative fixture also has no Alphus `# expect-error` location
markers, so the shared runner rejected it before the native stubtest and
runtime-smoke lanes. This was an early-stop result, not a consumer pass or a
stub incompatibility finding.

## Temporary calibrated fixture result

In a disposable copy, the three class-object assertions were expressed as
explicit `type[TextUtils]` variable assignments. The four invalid calls in the
negative fixture received `# expect-error` markers. This preserves the static
class-object compatibility check while using an assertion form accepted by all
three tools; it does not change the consumer repository or published stubs.

On that copy, MyPy, Pyright, and ty each accepted the positive fixture and
rejected the four marked invalid lines with their configured checker-specific
diagnostics. The installed-wheel build, dependency check, native `mypy.stubtest`,
and runtime API smoke all passed. The report records the exact executable paths,
Python prefixes, tool versions, commands, lane outcomes, and artifact digest.

This single Python 3.11.16 macOS arm64 run does not cover the consumer's declared
Python 3.10–3.14 range, other operating systems, or other runtime versions. The
original fixture's ty class-object assertion limitation remains an explicit
compatibility deviation to review with the consumer; no consumer source, pin,
workflow, or release was changed.

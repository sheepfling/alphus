# Shared test gate migration

The migration extracts the repeated checking mechanisms from
SnakeMD and mdutils into the installed Alphus distribution. Consumer adapters
retain package facts and behavioral assertions.

The following modules are under `alphus_stub_quality`.

| Mechanism | Shared module | Consumer responsibility |
| --- | --- | --- |
| Positive/negative examples | `typing_fixtures` | Files, marker/count contracts, diagnostic fragments |
| AST inspection | `api_audit_support` | Module inventory and allowed annotation widenings |
| Runtime facade matching | `runtime_audit` | Facade, non-API bindings, logger allowlist |
| API and example coverage | `api_contracts.ApiCoverageTests` | Version, paths, runtime modules, exports, examples |
| Isolated build/install | `verify` | Runtime pin, allowlist, API/runtime adapter modules |

The installed entrypoints are `alphus-typing-fixtures` and
`alphus-stub-quality`. The GitHub Action installs the same pinned Alphus code.
The consumer distributions acquire no Alphus runtime dependency. Native Mypy,
Pyright, stubtest, Ruff, build, Twine, mdrepo and rumdl retain their domains.

From a dedicated verification environment with the reviewed Alphus wheel and
consumer tools installed, run this outside either source checkout:

```shell
alphus-stub-quality --root /path/to/stub-repo \
  --config stub-quality.json --with-twine
```

See [the shared gate guide](STUB-PACKAGE-CI.md) for setup and interfaces.

## Preserved contracts

mdutils retains its exact seven-diagnostic contract and checker-specific
fragments. SnakeMD retains exact marked failing lines, including multiple
native diagnostics on one marked line. Positive examples must pass cleanly.
Tool startup failures, timeouts, diagnostic exits other than one, and unrelated
errors cannot establish a marked expected-negative result.

mdutils's source comparison retains AST default-expression structure and
property/setter/deleter distinctions. SnakeMD's runtime comparison retains its
separate normalization of runtime defaults, decorators, enums and annotations.
The generic runtime API result is a read-only mapping; its contained runtime
classes and functions are not made immutable.

Regression counterexamples cover wrong declaring-class probes, missing return
annotations, changed defaults/decorators/definitions, unexpected diagnostics,
tool failure, and invalid configuration. The crawler still has its original
static limits: direct imports, configured re-exports, constructor assignments,
and direct calls. It does not prove runtime branch coverage or infer arbitrary
alias/data flow or complete type semantics.

## Published migration acceptance checkpoint

The following results describe published migration commit `d613d28`, before
the separately approved local runtime-type correction.

The installed-wheel verifiers pass against both actual consumer candidates on
Python 3.11 and 3.12. The Alphus self-profile passes nine of ten steps on both.
`Runtime type usage` reports 104 findings in the newly included inspection code
because its unchanged rule requires an explicit union annotation for every
`isinstance` check. The remaining steps, including the regression suite, pass.
Strict Pyright reports zero errors, warnings and informational diagnostics.

This was the self-application blocker at that historical checkpoint. The migration has not added an
exclusion, changed a failure threshold, or modified that rule to accept its own
code. A policy decision about nominal AST/library introspection remains before
this candidate can be declared ready. Other Python/runtime matrix combinations
and hosted execution are separate evidence; prior runs do not verify this
revision.

## Explicit consumer composition

Both consumer `check` profiles include `stubs`, `python`, and `markdown`.
The local CLI runs that full selection; hosted quality and target jobs select its parts explicitly. The stub
verifier owns one isolated build/install stage, with Twine selected in the
consumer's argv. The other profiles retain native tool ownership. mdutils's
previous `stub-package` source-policy profile and `markdown-quality` selection
remain available by name; its default is now the full `check` composition.

The 104 self-profile findings comprise 95 AST subclass-dispatch checks and nine
runtime-reflection checks. These violate the literal explicit-union convention;
they do not alone establish a runtime or typing defect. The heuristic does not
model nominal AST inheritance, inferred child types, prior narrowing, or
attribute types. Finite unions would misrepresent the arbitrary runtime
reflection boundaries. A semantic policy decision remains necessary; consumer
profile selection does not silently exempt this source from self-application.

The subsequent approved correction supports typed AST subtype dispatch
and value-specific reflection contracts. Its semantics, counterexamples and
remaining inference limits are documented in [Runtime type checks](RUNTIME-TYPES.md).
It adds no file exclusions and preserves the existing object-facing adapters.
The results below remain the historical migration checkpoint; local correction
verification and the interpreter split are recorded below for this candidate.

## Composition verification

The extraction and composition were verified with an installed Alphus wheel
on Python 3.11.16 and 3.12.14, invoking the profiles from outside the source
checkouts with `PYTHONPATH` unset:

| Check | Result on both interpreters |
| --- | --- |
| Alphus regression suite | 374 passed |
| Native Ruff lint and format | Passed |
| Native strict Pyright over both shipped packages | 0 errors, warnings, information |
| SnakeMD `check` (`stubs`, `python`, `markdown`) | 8/8 stages passed |
| mdutils `check` (`stubs`, `python`, `markdown`) | 5/5 stages passed |
| mdutils optional `stub-package` source policy | 6/6 stages passed |
| Portable consumer positive / expected negative | 12/12 / 10/12; only native Markdown checks failed |
| Markdown-only positive / missing-link counterexample | 2/2 / 1/2; native link check failed |
| Alphus established self-profile | 9/10; 104 runtime-type findings remain |

Each consumer stub stage builds wheel and sdist, checks both with Twine,
installs the wheel, checks dependencies, runs its API adapter, requires clean
positive and the configured expected-negative Mypy/Pyright examples, then runs
stubtest and runtime smoke. These are real consumer runs, separate from the
shared engines' synthetic regression cases. A fresh Python 3.12 environment
also verified mdutils using only its declared verification/runtime requirements
and the installed Alphus wheel, including its non-isolated build prerequisites.

For a reusable local command, install `requirements-quality.txt` from either
consumer repository root and run:

```shell
alphus --root /path/to/stub-repository \
  --config quality-gates.toml --run --profile check
```

Both the local requirement and hosted quality action select the same immutable
Alphus revision. Hosted workflow execution and the broader release matrix are
not established by this local evidence. Existing merged-PR/manual triggers
remain unchanged.

## Checker/target acceptance

The current candidate includes the approved runtime-type correction and the
separate checker/target execution contract. The unchanged established Alphus
self-profile now passes **10/10 with zero findings** on Python 3.11.16 and
3.12.14. No self-policy exclusions, scope, severity or threshold were changed.
The shared source-scanner alias-resolution module is unchanged by this follow-up.

An installed wheel was invoked outside the source checkouts, with inherited
package-path variables removed. The clean checker is Python **3.12.14**, with
Mypy **2.4.0**, Pyright **1.1.414** and Twine **7.0.0**. It has neither consumer
runtime nor stub distribution installed. Each target is a separate venv with
build **1.6.1**, setuptools **84.2.0**, setuptools-scm **10.3.4**, wheel **0.48.0**
and Mypy **2.4.0** for native stubtest. Alphus is absent from all target
distributions. Runtime baselines remain SnakeMD **2.4.1** and mdutils **1.8.1**.

| Actual target | SnakeMD installed-wheel gate | mdutils installed-wheel gate |
| --- | --- | --- |
| 3.10.22 | 8/8 stages passed | 8/8 stages passed |
| 3.11.16 | 8/8 stages passed | 8/8 stages passed |
| 3.12.14 | 8/8 stages passed | 8/8 stages passed |
| 3.13.15 | 8/8 stages passed | 8/8 stages passed |
| 3.14.7 | 8/8 stages passed | 8/8 stages passed |

Every row includes native target build, installation, pip check, API audit,
stubtest and smoke; native Twine and both positive/expected-negative static
checkers run in the checker. All configured marker/count/diagnostic-fragment
contracts remain enforced. These ten runs establish the exact pinned runtimes,
not every release inside a package's advertised dependency range.

Additional boundary evidence:

- Five opt-in integration cases prove both checkers discover packages installed
  only in each target. A `typing.Self` fixture fails for target 3.10 and passes
  for 3.11–3.14 despite deliberately conflicting consumer language defaults.
- A temporary consumer copy with smoke exiting 7 only on target 3.10 passes its
  first seven stages, including both static checkers, then fails stage eight
  with exit 7 and `passed=false`.
- A target without build tools fails its first native stage with exit 1. Later
  stages are absent; no checker fallback occurs.
- Both checker-side suites pass **485 cases**, including the five explicitly
  provisioned native integration cases. Without their environment variables,
  480 regular cases run and the opt-in group skips.
- Native configured Ruff lint and formatting pass; strict Pyright over both
  shipped source packages reports **0 errors, warnings and information**.
- Full consumer profiles pass SnakeMD **8/8**, mdutils **5/5**, and mdutils's
  optional source selection **6/6**, on Python 3.11.16 and 3.12.14.
- Portable examples pass **12/12** positive and the intended **10/12** negative;
  only the native Markdown checks fail. Markdown-only examples pass **2/2**
  positive and **1/2** for the missing-link counterexample on both interpreters.

Use the reusable commands in [the shared gate guide](STUB-PACKAGE-CI.md) and
[Alphus self-check guide](SELF-CHECK.md). To rerun the native integration cases,
set `ALPHUS_TEST_CHECKER_PYTHON` to a clean checker executable and
`ALPHUS_TEST_TARGET_PYTHONS` to the path-separator-delimited target executables
before `python -m pytest -q tests`. Provision both installed consumer wheels in
the targets using the documented verifier first.

Hosted workflows retain merged-PR/manual triggers and read-only repository
permissions. They run one `quality` selection and five target compatibility
legs with a 3.12 checker. No ordinary PR/push trigger or dispatched hosted run
was added by this verification. Hosted Ubuntu execution remains unverified;
these local results use macOS arm64. No release or merge is part of this work.

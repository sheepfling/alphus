# Shared test gate migration

The local migration candidates extract the repeated checking mechanisms from
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

## Acceptance blocker

The installed-wheel verifiers pass against both actual consumer candidates on
Python 3.11. The Alphus self-profile currently passes nine of ten steps.
`Runtime type usage` reports 104 findings in the newly included inspection code
because its unchanged rule requires an explicit union annotation for every
`isinstance` check. The remaining steps, including the regression suite, pass.
Strict Pyright reports zero errors, warnings and informational diagnostics.

This is a remaining self-application blocker. The migration has not added an
exclusion, changed a failure threshold, or modified that rule to accept its own
code. A policy decision about nominal AST/library introspection remains before
this candidate can be declared ready. Other Python/runtime matrix combinations
and hosted execution are separate evidence; prior runs do not verify this
revision.

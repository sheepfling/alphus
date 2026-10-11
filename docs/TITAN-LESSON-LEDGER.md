# TITAN lesson and rule ledger

This ledger separates reusable checker families from their predicates, the
policy instances that configure them, and TITAN cleanup milestones that apply
the checks to new code. A QG milestone is not a new checker rule.

## Evidence snapshot

The source-side inventory is Alphus commit
[`35b2924`](https://github.com/sheepfling/alphus/tree/35b2924da7a689d0f9b3986b8306a5ea479295f1),
which adds module-level assignment detection to the reusable module-role
engine. The TITAN policy and representative tests are pinned to pushed TITAN
commit [`66ac4a9`](https://github.com/hawkeye1111/Titan/tree/66ac4a9)
(QG-468). Its policy has 17 `[checks.*]` sections, 25 step definitions, and
nine profiles. The default `check` profile selects 23 steps; `lint` selects
14. Across all profiles there are 44 profile-to-step references.

The 17 TITAN policy sections comprise 14 public Alphus selectors plus three
sub-engines under `package-boundaries`: `architecture_graph`, `version_sync`,
and `callable_registry`. These have source diagnostics but are not separate
`QualityRuleName` selectors. The 25 configured steps comprise 13 direct
Alphus rule steps and 12 commands. One command is TITAN's
`titan-dev gate module-roles` adapter; the others call project-owned tools
such as mdrepo, rumdl, Ruff, npm, and JavaScript formatters. Thus 13 of the 14
selectors are direct rule steps in that plan. TITAN's module-role step adds
its installed-server inventory and operation-catalog checks around the
reusable scanner.

The QG-468 policy configures 340 module-role targets. Those targets contain
12,234 forbidden-import, forbidden-pattern, forbidden-call,
forbidden-definition, and forbidden-module-assignment entries (5,053, 1,499,
5,592, 88, and 2, respectively). Across these entries there are 445 distinct
values across the five fields. For example, 5,592 configured forbidden calls
reduce to 67 distinct call names; 5,053 forbidden imports reduce to 274
distinct imports. Repetition is largely the application of common role policy
to many distinct modules, not thousands of different reusable rules. Alphus
emits eight stable module-role finding IDs regardless of how many modules or
names a consumer configures.

## Reusable families and diagnostics

Alphus has 14 public selectors. Source inspection finds 64 literal
`Finding.rule_id` values plus eight dynamic module-role IDs: **72 stable
machine finding IDs**. Five other families report typed categories or
human-readable diagnostics without stable `rule_id` values; their categories
are listed below rather than presented as IDs.

### `file-size`

Stable IDs: `source.code-file-size`, `source.hard-file-size`,
`source.initializer-definition`, `source.initializer-size`, and
`source.initializer-wildcard-import`.

### `line-length`

Stable ID: `source.line-length`.

### `json-structure`

Stable ID: `data.json-structure`.

### `output-escaping`

Stable ID: `output.manual-escaping`.

### `path-discovery`

Stable ID: `paths.implicit-discovery`.

### `shared-utilities`

Typed report fields, not IDs: `duplicate_groups` and
`file_hash_implementations`. The checks identify repeated top-level helper
bodies and separate file SHA-256 implementations outside the configured
canonical helper.

### `python-style`

Category keys, not IDs: `bare_containers`, `bare_tuples`, `concrete_inputs`,
`local_imports`, `opaque_mappings`, `unslotted_dataclasses`, `quoted_types`,
`type_checking_imports`, `os_path`, `main_module_imports`,
`legacy_pydantic_fields`, and `pydantic_collection_contracts`.

### `runtime-types`

One ID-less diagnostic: `runtime type check requires an explicit union
annotation`.

### `cli`

ID-less categories: Typer entrypoint, Rich human output, explicit `--json`,
JSON serializer use, explicit `--verbose`, and configured Node CLI endpoints.

### `script-policy`

ID-less categories: a non-Python launcher (`launcher_message`) and a
nonconforming CMD router (`cmd_message`).

### `module-roles`

Stable IDs: `module-role.syntax`, `module-role.path`, `module-role.read`,
`module-role.forbidden-import`, `module-role.forbidden-import-pattern`,
`module-role.forbidden-call`, `module-role.forbidden-definition`, and
`module-role.forbidden-assignment`.

### `package-boundaries`

The public selector combines four source engines. Package IDs:
`package.contract-missing`, `package.dependency-cycle`,
`package.dependency-forbidden`, `package.dependency-missing`,
`package.dependency-unknown`, `package.file-backed-loading`,
`package.import-forbidden`, `package.import-forbidden-root`,
`package.import-loose-module`, `package.import-opaque-dynamic`,
`package.import-root-duplicate`, `package.import-root-missing`,
`package.import-undeclared`, `package.metadata`, `package.metadata-path`,
and `package.sys-path-mutation`.

Nested architecture-graph IDs: `architecture.edge-forbidden`,
`architecture.edge-missing`, `architecture.graph-missing`, and
`architecture.node-missing`. Version ID: `metadata.version-mismatch`.
Callable-registry IDs: `registry.callable-duplicate`, `registry.file-missing`,
`registry.key-not-literal`, `registry.key-target-mismatch`,
`registry.mapping-missing`, `registry.mapping-not-literal`,
`registry.mapping-untyped`, `registry.protocol-untyped`,
`registry.public-callable-unregistered`, and `registry.unknown-callable`.

### `dependency-locks`

Stable IDs: `dependency-lock.include-cycle`,
`dependency-lock.include-invalid`, `dependency-lock.input-missing`,
`dependency-lock.pin-not-exact`, `dependency-lock.pin-unsatisfied`,
`dependency-lock.requirement-invalid`,
`dependency-lock.requirement-unlocked`, and
`dependency-lock.source-mismatch`.

### `repository-layout`

Stable IDs: `layout.bridge-area-missing`,
`layout.bridge-root-marker-missing`, `layout.bridge-root-missing`,
`layout.bridge-router-import-missing`, `layout.bridge-scope-missing`,
`layout.glob-forbidden`, `layout.json-array-value-required`,
`layout.path-forbidden`, `layout.path-required`,
`layout.python-symbol-required`, `layout.root-document-forbidden`,
`layout.router-area-missing`, `layout.router-root-missing`,
`layout.toml-table-required`, `layout.tracked-path-forbidden`, and
`layout.tracked-suffix-forbidden`.

The five ID-less families currently expose 23 report/category variants:
12 Python-style keys, six CLI conditions, two script-policy messages, two
shared-utility report fields, and one runtime-type diagnostic. Stable IDs for
these families remain a product gap when consumers need cross-version,
machine-level reporting.

## From lessons to configured instances

The relation is many-to-many:

- **14 checker families** are reusable policy capabilities in Alphus.
- **72 stable IDs** describe concrete findings; five other families expose
  **23 report/category variants** without stable IDs.
- **17 TITAN policy sections** configure the 14 public selectors and three
  nested package-boundary engines.
- **340 module-role target records** instantiate one family across selected
  TITAN modules. Their thousands of forbidden names are configuration values,
  not unique reusable rules.
- **25 step definitions and nine profiles** select rule and command instances.
- TITAN QG identifiers reach **QG-468** in this evidence snapshot. They are
  remediation and gate-evolution identifiers, not 468 checker types. Repeated
  QG-00 work reuses `module-roles` and the same eight finding IDs while adding
  targets, moving code across a boundary, or strengthening positive and
  negative tests. QG-468's action-history snapshot work is a later application
  of that family. The next cursor at this snapshot was QG-401.

TITAN's `quality-gates.toml` is authoritative for the configured rules and
commands. `docs/quality/REVIEW-BACKLOG.md` and
`docs/quality/EXECUTION-HISTORY.md` describe remediation instances and
verification outcomes. See also
[`CONSUMER-PROFILES.md`](CONSUMER-PROFILES.md) for tool ownership and
orchestration.

## Extraction boundary and remaining work

The former TITAN-local portable package has been extracted to
`sheepfling/alphus`; TITAN's layout rule rejects a restored `tools/alphus`
source directory. QG-459 added generic module-level assignment scanning for
provider aliases and `TypeAlias` declarations. TITAN still owns the
`titan-dev` adapter, which adds its installed-server module inventory and
operation-catalog checks. That consumer-specific behavior should remain in
TITAN unless another repository demonstrates the same reusable contract.

The evidence supports these concrete product gaps:

1. Before this ledger, Alphus had no source-backed index separating its 14
   selectors from nested engines, stable IDs, TITAN target instances, and QG
   remediation history.
2. Before the consumer example, a new user had no single profile example
   coordinating mdrepo, rumdl, and Python lint, typing, and tests. The example
   now fills that gap without copying upstream rules.
3. Five families still lack stable IDs for their current diagnostics.
4. TITAN's backlog lists potential future reusable checks for deterministic
   TOML/JSON/YAML formatting, test ownership/tag validation, and TODO-marker
   inventory. They are not shipped Alphus checks. Treat them as extraction
   candidates only after their policy contracts and positive/negative tests
   are established.

The recorded PR #1 snapshot is 47 inline threads (23 resolved, 24 open) as of
2026-10-10, but no raw comment-dump path or artifact URL is present in the
checkout or task attachments. GitHub PR reads were unavailable during the
prior review. This ledger reconciles against the checked-in backlog and
execution history; it cannot claim a comment-by-comment reconciliation to an
unattached dump.

## Bounded test and policy critique (QG-468)

This is a read-only source review of the pinned TITAN commit and representative
tests. No TITAN tests were run as part of this critique, and the active TITAN
branch was not changed. The task API's QG-468 report records the focused owner
gate as passing while the wider Python suite remained red on other open DIS
gates; that report is distinct from this static review.

### Keep these behavioral invariants

- Capture a coherent action-history view while holding the session lock, then
  render documents after releasing it. The snapshot must detach nested decoded
  messages, entity bindings, and runtime results from mutable retained state.
- Preserve action policy and identity semantics: observe/review disposition,
  trusted-source and allow-list decisions, deduplication keys, rejection
  reasons, and action document fields. Concrete expected identity strings and
  JSON values are justified where they are the current contract.
- Keep package and dependency direction enforceable. The projection layer
  should not acquire session mutation, transport, or infrastructure duties;
  the TITAN adapter may retain its installed-server inventory and
  operation-catalog checks.

The owner tests exercise behavior as well as source shape. In
`apps/titan-server/tests/test_dis_inbound_action_projection_snapshots.py`,
nested decoded message, binding, and runtime-result values are mutated after
capture and the snapshot is checked for independence. In
`apps/titan-server/tests/test_dis_inbound_action_read_snapshot.py`,
projection is blocked while a concurrent resolution proceeds: the in-flight
result remains the captured `pending` view and the next read observes
`acknowledged`. That blocking wrapper is a targeted concurrency probe, not a
brittle call-count mock; it tests lock release and snapshot isolation.

### Separate invariant, consumer policy, and implementation shape

**Reusable mechanism:** lock-scoped capture, detached immutable values,
post-lock batch projection, typed inputs and outputs, and dependency direction.
These can be expressed as reusable typed contracts and policy predicates. A
checker should reject projection while the lock is held, discarded projection
results, direct rendering of mutable records, and snapshots that retain aliases
to mutable state.

**TITAN policy:** which concrete modules own contracts, operations, and
projection; which imports and calls are forbidden for each module; and which
named application operations appear in the operation catalog. The consumer
owns these values. Alphus and the generic scanner should not hard-code TITAN
paths, DIS names, or the installed-server inventory.

**Incidental implementation detail:** several source gates bind invariants to
exact paths, class and method names, function names, import forms, and local
call names. For example,
`tools/titan-dev/tests/test_dis_action_history_snapshot_gate.py`
requires `DisInboundActionProjectionSnapshot`,
`prepare_inbound_action_projection_snapshots`,
`project_inbound_action_documents`, and a particular manager `actions` method;
its source-string fixtures assume exact spelling. The operation-wiring gate
enumerates exact method-to-call-name sets, and the binding gate reserves the
name `inbound_action_entity_bindings` for one module. Renaming a private helper
or moving an equivalent operation can fail those gates even when behavior is
unchanged. Keep public or catalogued names stable where they are truly
contracts; otherwise prefer typed operation-role metadata and behavioral
checks over AST name bans.

The exact snapshot field list is useful as a typed projection contract, but it
can also make equivalent representations fail source fixtures. If field names
are internal, validate that the snapshot carries the semantic inputs needed
for projection and that later mutations cannot leak, rather than freezing
every internal spelling.

### Simplify policy without losing coverage

The 340 target records are meaningful coverage: they identify which TITAN
modules the architecture gate scans. The 12,234 name entries are not 12,234
distinct rules:

| Policy list | Entries | Distinct values | Repeated entries |
| --- | ---: | ---: | ---: |
| Forbidden calls | 5,592 | 67 | 5,525 |
| Forbidden imports | 5,053 | 274 | 4,779 |
| Forbidden import patterns | 1,499 | 25 | 1,474 |
| Forbidden definitions | 88 | 78 | 10 |
| Forbidden module assignments | 2 | 2 | 0 |

The call lists have 22 distinct list shapes across 339 configured targets; one
exact shape is reused by 165 targets. Import-pattern lists have 35 shapes
across 334 targets; one shape is reused by 83. This supports typed declarative
role presets or inherited common predicates, with small per-module additions
and explicit exceptions. Keep the 340 selected paths and module-specific
edges visible; do not replace them with a vague global denylist.

For future work, favor a few tests per checker engine for parsing, matching,
positive and negative cases, malformed configuration, and stable diagnostics;
consumer tests for policy selection and representative gates; and behavior or
integration tests at important runtime boundaries. Replace repeated
source-string fixtures with tables of typed policy invariants where equivalent
semantics permit it. Keep concurrency, transport and serialization, security,
output-contract, and representative cross-package tests. These are review
recommendations, not edits to TITAN policy or gates.

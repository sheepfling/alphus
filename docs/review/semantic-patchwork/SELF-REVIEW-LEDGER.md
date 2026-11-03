# PR #76 self-review coverage ledger

This ledger separates each finding's underlying defect from the reason the
root self-review did not report it. A regression test run by the package test
step guards a case now; it does not mean the corresponding advisory was
selected against Alphus source.

## Codex review findings

Most of the 22 inline findings were **functional implementation gaps** in
opt-in semantic detectors. The root `review` profile omitted those detectors
because their contracts describe consumer behavior (rendering, ownership,
repair order, parsing, or normalization) that is not grounded in Alphus's own
source. That profile exclusion explains why the default self-review did not
report the bugs; it does not change their classification as detector defects.
Each regression below runs in the `Python tests` step of the root `check`
profile. A few exceptions concern policy validation or runner configuration
and are classified individually.

### [4438791524](https://github.com/sheepfling/alphus/pull/76#discussion_r4438791524)

**Finding:** Multiline protocol strings in literal allowlists

**Underlying defect:** The allowlist validator mishandled multiline protocol
  literals. The affected prose detector is opt-in; root review had neither a
  policy fixture for this case nor that consumer-specific contract.

**Coverage now:** LF/CR multiline allowlist tests in `test_prose_as_control.py`.

### [4444796711](https://github.com/sheepfling/alphus/pull/76#discussion_r4444796711)

**Finding:** Evaluate configured functions independently per file

**Underlying defect:** The detector incorrectly required configured function
  names to be co-located in one file. The detector is opt-in because selected
  functions require a consumer contract.

**Coverage now:** Multi-file selector regression in `test_semantic_work_presentation.py`.

### [4445891743](https://github.com/sheepfling/alphus/pull/76#discussion_r4445891743)

**Finding:** Avoid dispatching rendered feedback twice in an example profile

**Underlying defect:** The example profile composed overlapping feedback
  runners. That is a configuration/runner composition issue requiring an
  example-profile test; the generic registry cannot infer semantic duplication.

**Coverage now:** Explicit static runner manifest, catalog-coverage and stale-manifest
  tests; no semantic duplicate-feedback oracle.

### [4445891758](https://github.com/sheepfling/alphus/pull/76#discussion_r4445891758)

**Finding:** Invalidate rendered bindings overwritten by match captures

**Underlying defect:** Match captures were not included in rendered-binding
  invalidation. The detector is opt-in because renderer and predicate identities
  require a caller-declared contract.

**Coverage now:** Match-capture overwrite positive/negative regressions in
  `test_rendered_value_reparsed.py`.

### [4445995592](https://github.com/sheepfling/alphus/pull/76#discussion_r4445995592)

**Finding:** Invalidate overwritten bindings before exception handlers

**Underlying defect:** Possible writes before exception handlers were not
  propagated into handler analysis. Root review omits the detector because its
  renderer/predicate names are consumer-configured.

**Coverage now:** Try/handler binding-survival regressions in
  `test_rendered_value_reparsed.py`.

### [4445995612](https://github.com/sheepfling/alphus/pull/76#discussion_r4445995612)

**Finding:** Include non-assignment helper bindings in shadowing checks

**Underlying defect:** Imports, class definitions, and deletion bindings were
  missing from parser/helper shadowing analysis. The detector requires configured
  parser/helper identities, so root review does not select it.

**Coverage now:** Import, class, deletion, function, and parameter rebindings in
  `test_patch_cascade.py`.

### [4446024849](https://github.com/sheepfling/alphus/pull/76#discussion_r4446024849)

**Finding:** Invalidate rendered bindings assigned in conditional expressions

**Underlying defect:** Conditional-expression writes were not propagated to
  rendered-binding analysis. The detector is absent from root review because it
  requires consumer renderer/predicate identities.

**Coverage now:** Conditional/walrus overwrite regressions in
  `test_rendered_value_reparsed.py`.

### [4446024864](https://github.com/sheepfling/alphus/pull/76#discussion_r4446024864)

**Finding:** Count class rebindings before comparing normalizers

**Underlying defect:** Class rebindings were omitted from normalizer identity
  checks. This detector is not in root review because comparing outputs requires
  a caller-declared equivalence contract.

**Coverage now:** Class and other rebindings plus equal/drift controls in
  `test_parallel_normalization.py`.

### [4446093114](https://github.com/sheepfling/alphus/pull/76#discussion_r4446093114)

**Finding:** Preserve regex semantics for zero-count quantifiers

**Underlying defect:** This was a functional gap in the opt-in prose-as-control detector; no
  root profile selected it against Alphus.

**Coverage now:** Python-behavior regressions for zero-count and identity regexes in
  `test_prose_as_control.py`.

### [4446093123](https://github.com/sheepfling/alphus/pull/76#discussion_r4446093123)

**Finding:** Track renderer calls with keyword-only inputs

**Underlying defect:** Renderer calls with keyword-only inputs were not
  recognized. The root review profile omits this caller-configured advisory.

**Coverage now:** Keyword-only renderer input regression in
  `test_rendered_value_reparsed.py`.

### [4446261470](https://github.com/sheepfling/alphus/pull/76#discussion_r4446261470)

**Finding:** Invalidate rendered bindings overwritten in while tests

**Underlying defect:** Binding invalidation missed the stated control-flow
  write. The root review profile omits this caller-configured advisory.

**Coverage now:** While-test/body/else overwrite controls in
  `test_rendered_value_reparsed.py`.

### [4446261476](https://github.com/sheepfling/alphus/pull/76#discussion_r4446261476)

**Finding:** Check enclosing zero-count quantifiers before reporting digits

**Underlying defect:** Functional gap in an unselected, opt-in regex advisory.

**Coverage now:** Enclosing quantifier controls in `test_prose_as_control.py`.

### [4446299019](https://github.com/sheepfling/alphus/pull/76#discussion_r4446299019)

**Finding:** Invalidate loop-overwritten bindings before for-else

**Underlying defect:** Binding invalidation missed the stated control-flow
  write. The root review profile omits this caller-configured advisory.

**Coverage now:** For-loop target/else survival regressions in
  `test_rendered_value_reparsed.py`.

### [4446342193](https://github.com/sheepfling/alphus/pull/76#discussion_r4446342193)

**Finding:** Account for loop-body overwrites before while-else

**Underlying defect:** Binding invalidation missed the stated control-flow
  write. The root review profile omits this caller-configured advisory.

**Coverage now:** While-else overwrite/preservation controls in
  `test_rendered_value_reparsed.py`.

### [4446342208](https://github.com/sheepfling/alphus/pull/76#discussion_r4446342208)

**Finding:** Skip verbose-mode trivia before zero-quantifier checks

**Underlying defect:** Functional gap in the unselected regex advisory; Python regex syntax
  semantics were not modeled by root self-review.

**Coverage now:** Verbose-mode whitespace/comment regressions in `test_prose_as_control.py`.

### [4446396718](https://github.com/sheepfling/alphus/pull/76#discussion_r4446396718)

**Finding:** Count import and class rebindings of selected functions

**Underlying defect:** Import and class bindings were missing from selected
  function identity checks. The root profile omits this detector because its
  function identities are caller-configured.

**Coverage now:** Import/class rebinding regressions in
  `test_heuristic_total_consumption.py`.

### [4446396725](https://github.com/sheepfling/alphus/pull/76#discussion_r4446396725)

**Finding:** Invalidate rendered bindings reassigned in expression statements

**Underlying defect:** Binding invalidation missed the stated control-flow
  write. The root review profile omits this caller-configured advisory.

**Coverage now:** Expression-statement and walrus regressions in
  `test_rendered_value_reparsed.py`.

### [4446451187](https://github.com/sheepfling/alphus/pull/76#discussion_r4446451187)

**Finding:** Limit rebinding suppression to affected function

**Underlying defect:** Functional scope gap in the opt-in total-consumption detector.

**Coverage now:** Per-function rebinding isolation regression in
  `test_heuristic_total_consumption.py`.

### [4446451201](https://github.com/sheepfling/alphus/pull/76#discussion_r4446451201)

**Finding:** Recognize verbose mode among combined inline flags

**Underlying defect:** Functional regex-parser gap in the unselected prose-as-control
  detector.

**Coverage now:** Combined inline flag and verbose syntax regressions in
  `test_prose_as_control.py`.

### [4446518359](https://github.com/sheepfling/alphus/pull/76#discussion_r4446518359)

**Finding:** Exclude comprehension-local targets from module binding counts

**Underlying defect:** Shared module-binding analysis counted comprehension-local
  targets as module rebindings. This is an implementation gap; the affected
  semantic consumers are opt-in in the root profile.

**Coverage now:** Comprehension target versus walrus binding tests in
  `test_module_bindings.py`.

### [4446518369](https://github.com/sheepfling/alphus/pull/76#discussion_r4446518369)

**Finding:** Verify path-comprehension attribute root is the target

**Underlying defect:** The provenance matcher failed to verify that the
  comprehension's attribute root was its loop target. Root review omits the
  detector because path/ownership semantics require consumer configuration.

**Coverage now:** Correct-root and wrong-root cases in `test_provenance_ownership.py`.

### [4446603568](https://github.com/sheepfling/alphus/pull/76#discussion_r4446603568)

**Finding:** Invalidate walrus writes in assignment values

**Underlying defect:** Binding invalidation missed the stated control-flow
  write. The root review profile omits this caller-configured advisory.

**Coverage now:** Assignment-value walrus mutation regressions in
  `test_rendered_value_reparsed.py`.


The root profile also omits all consumer-specific semantic rule selectors by
design. Enabling them for Alphus without a contract would create unsupported
claims, not improve self-review coverage. The package test step does execute
the detector regression suite, which protects implementation behavior without
pretending those detectors have an Alphus-specific runtime policy.

The three named-result policy fixes have behavioral integration coverage in
`test_self_profile_python_style_runner_catches_historical_tuple_shapes`. It
loads the self-policy, invokes the registered `python-style` runner on historical
tuple-return fixtures at those configured paths, asserts findings for all
three, then asserts the current source files are clean through the same runner.

## Author/editor comments

### [4447793392](https://github.com/sheepfling/alphus/pull/76#discussion_r4447793392)

**Concern:** Explain mapping keys in provenance ownership

**Classification and disposition:** Human-judgment/documentation concern: no static rule can
  determine whether a local mapping key has adequate domain meaning. The detector now
  documents key names as local identifiers and its configured `_OwnerPathSet` values.

### [4447797498](https://github.com/sheepfling/alphus/pull/76#discussion_r4447797498)

**Concern:** Replace heterogeneous provenance tuples

**Classification and disposition:** **Self-review policy gap fixed:** the named-result rule
  had omitted this detector file. It now uses semantic record types and
  `provenance_ownership.py` is included in `semantic_result_paths`.

### [4447799970](https://github.com/sheepfling/alphus/pull/76#discussion_r4447799970)

**Concern:** Extract hard-coded AST cap

**Classification and disposition:** Unsupported by the current repeated-literal
  rule, which looks for long strings occurring at least three times. It would not
  detect two repeated numeric caps, even if this file were selected. The cap is
  now a named constant, but that is a manual fix, not self-review coverage. A
  numeric repetition rule would need a bounded contract and false-positive study;
  none is implemented or claimed here.

### [4447807922](https://github.com/sheepfling/alphus/pull/76#discussion_r4447807922)

**Concern:** Replace rendered-value tuples

**Classification and disposition:** **Self-review policy gap fixed:**
  `rendered_value_reparsed.py` now participates in `semantic_result_paths`, and the API uses
  a named result record.

### [4447810502](https://github.com/sheepfling/alphus/pull/76#discussion_r4447810502)

**Concern:** Clarify dict semantics and add a docstring

**Classification and disposition:** Documentation/human-judgment concern; no selected static
  rule can prove that a dictionary's semantics are sufficiently documented. The binding
  map's purpose is documented, but semantic adequacy remains review work.

### [4447816919](https://github.com/sheepfling/alphus/pull/76#discussion_r4447816919)

**Concern:** Make the runner export intentional

**Classification and disposition:** No existing self-review rule checks intended `__all__`
  policy. Fixed with an explicit `__all__` and a test asserting the public runner export.

### [4447821432](https://github.com/sheepfling/alphus/pull/76#discussion_r4447821432)

**Concern:** Avoid manual runner/registry coupling

**Classification and disposition:** The intended catalog is explicit configuration, but
  dispatch is now generated deterministically at build time as static imports.
  Duplicate/catalog-coverage/stale-manifest tests run in package tests. Runtime
  discovery/import scanning is intentionally unsupported to preserve static package
  boundaries.

### [4447825152](https://github.com/sheepfling/alphus/pull/76#discussion_r4447825152)

**Concern:** Replace unexplained-empty-result tuples

**Classification and disposition:** **Self-review policy gap fixed:**
  `unexplained_empty_results.py` now participates in `semantic_result_paths` and uses named
  result records.

### [4447831171](https://github.com/sheepfling/alphus/pull/76#discussion_r4447831171)

**Concern:** Make consumer fixture paths independent of CWD

**Classification and disposition:** Test-source path inspection is intentionally excluded by
  `inspection_exclude = ["tests/**"]`; generic path text cannot establish the intended base
  directory. The fixture now supplies `examples_root`, and a changed-CWD regression guards
  it.

### [4447633045](https://github.com/sheepfling/alphus/pull/76#discussion_r4447633045)

**Concern:** Give calibration documentation durable purpose and hierarchy

**Classification and disposition:** Documentation review concern, not a selected executable
  rule. Addressed by placing the calibration record in the review documentation hierarchy
  with purpose, boundaries, and extension guidance.


The repeated-literal rule is deliberately not selected for
`parallel_normalization.py`: its implementation currently targets long strings
used at least three times, not duplicated numeric limits. Adding this source path
would imply coverage it cannot provide. The AST node cap is a named constant,
but numeric-constant repetition remains an explicit self-review limitation and
follow-on candidate.

## Validation boundary

The local installed `check` profile completed with 26 passed, 0 failed, and 3
provisional checks. Its package-test step reported 1365 passed and 23 skipped
in this local environment; its Markdown line-length check passed on this ledger.

Hosted checks for PR head `c567c14d65211162ef0ec9b771ba84ec5123772d` all
passed, except `history-audit`, which was skipped. The hosted Python 3.11 log
reported 1376 passed and 12 skipped, and the hosted profile reported 26 passed,
0 failed, and 3 provisional checks. See the [exact-head hosted log][hosted-log].

[hosted-log]: https://github.com/sheepfling/alphus/actions/runs/41536409507/job/125589246807

These results show the selected policy and regression suite pass. They do not
establish that opt-in semantic detectors were run against Alphus source, nor
that static analysis can decide human questions such as intended registry
semantics or documentation quality.

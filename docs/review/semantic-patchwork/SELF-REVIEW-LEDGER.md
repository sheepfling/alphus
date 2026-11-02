# PR #76 self-review coverage ledger

This ledger explains why the substantive PR #76 review findings were not
reported by Alphus self-review. It separates checks selected by the repository
`check` profile from opt-in semantic detectors that require consumer-specific
contracts. A regression test run by the package test step is evidence that a
case is guarded now; it does not mean the corresponding advisory was selected
against Alphus source.

## Codex review findings

The 22 inline findings below concerned newly added, opt-in semantic detectors.
The root `review` profile does not select these detectors, and their contracts
describe consumer behavior (rendering, ownership, repair order, parsing, or
normalization) that is not grounded in Alphus's own source. Thus these were
**unconfigured/contract-dependent**, not claims that the self-review engine
ran and missed every pattern. Their unit regressions run under the `Python
tests` step of the root `check` profile. The “coverage now” column names the
regression area; profile selection remains intentionally unchanged.

| Review comment | Finding | Why self-review did not report it | Coverage now |
| --- | --- | --- | --- |
| [4438791524](https://github.com/sheepfling/alphus/pull/76#discussion_r4438791524) | Multiline protocol strings in literal allowlists | No selected rule validates this specific policy-validator contract; the consumer detector is opt-in. | LF/CR multiline allowlist tests in `test_prose_as_control.py`. |
| [4444796711](https://github.com/sheepfling/alphus/pull/76#discussion_r4444796711) | Evaluate configured functions independently per file | `semantic-work-presentation` is not selected by the root review profile; selector behavior is contract-specific. | Multi-file selector regression in `test_semantic_work_presentation.py`. |
| [4445891743](https://github.com/sheepfling/alphus/pull/76#discussion_r4445891743) | Avoid dispatching rendered feedback twice in an example profile | The generic runner registry does not infer whether two review rules produce duplicate feedback; this is example-profile configuration/human judgment. | Explicit static runner manifest, catalog-coverage and stale-manifest tests; no semantic duplicate-feedback oracle. |
| [4445891758](https://github.com/sheepfling/alphus/pull/76#discussion_r4445891758) | Invalidate rendered bindings overwritten by match captures | Rendered-value detector is opt-in and requires configured renderer/predicate contracts. | Match-capture overwrite positive/negative regressions in `test_rendered_value_reparsed.py`. |
| [4445995592](https://github.com/sheepfling/alphus/pull/76#discussion_r4445995592) | Invalidate overwritten bindings before exception handlers | Same opt-in rendered-value contract; the root profile does not select it. | Try/handler binding-survival regressions in `test_rendered_value_reparsed.py`. |
| [4445995612](https://github.com/sheepfling/alphus/pull/76#discussion_r4445995612) | Include non-assignment helper bindings in shadowing checks | Patch-cascade detector is opt-in and needs configured parser/helper identities. | Import, class, deletion, function, and parameter rebindings in `test_patch_cascade.py`. |
| [4446024849](https://github.com/sheepfling/alphus/pull/76#discussion_r4446024849) | Invalidate rendered bindings assigned in conditional expressions | Opt-in rendered-value contract, not in root review selection. | Conditional/walrus overwrite regressions in `test_rendered_value_reparsed.py`. |
| [4446024864](https://github.com/sheepfling/alphus/pull/76#discussion_r4446024864) | Count class rebindings before comparing normalizers | Parallel-normalization is opt-in and requires an explicitly configured output-equivalence contract. | Class and other rebindings plus equal/drift controls in `test_parallel_normalization.py`. |
| [4446093114](https://github.com/sheepfling/alphus/pull/76#discussion_r4446093114) | Preserve regex semantics for zero-count quantifiers | This was a functional gap in the opt-in prose-as-control detector; no root profile selected it against Alphus. | Python-behavior regressions for zero-count and identity regexes in `test_prose_as_control.py`. |
| [4446093123](https://github.com/sheepfling/alphus/pull/76#discussion_r4446093123) | Track renderer calls with keyword-only inputs | Opt-in rendered-value rule, absent from root review selection. | Keyword-only renderer input regression in `test_rendered_value_reparsed.py`. |
| [4446261470](https://github.com/sheepfling/alphus/pull/76#discussion_r4446261470) | Invalidate rendered bindings overwritten in while tests | Opt-in rendered-value contract. | While-test/body/else overwrite controls in `test_rendered_value_reparsed.py`. |
| [4446261476](https://github.com/sheepfling/alphus/pull/76#discussion_r4446261476) | Check enclosing zero-count quantifiers before reporting digits | Functional gap in an unselected, opt-in regex advisory. | Enclosing quantifier controls in `test_prose_as_control.py`. |
| [4446299019](https://github.com/sheepfling/alphus/pull/76#discussion_r4446299019) | Invalidate loop-overwritten bindings before for-else | Opt-in rendered-value contract. | For-loop target/else survival regressions in `test_rendered_value_reparsed.py`. |
| [4446342193](https://github.com/sheepfling/alphus/pull/76#discussion_r4446342193) | Account for loop-body overwrites before while-else | Opt-in rendered-value contract. | While-else overwrite/preservation controls in `test_rendered_value_reparsed.py`. |
| [4446342208](https://github.com/sheepfling/alphus/pull/76#discussion_r4446342208) | Skip verbose-mode trivia before zero-quantifier checks | Functional gap in the unselected regex advisory; Python regex syntax semantics were not modeled by root self-review. | Verbose-mode whitespace/comment regressions in `test_prose_as_control.py`. |
| [4446396718](https://github.com/sheepfling/alphus/pull/76#discussion_r4446396718) | Count import and class rebindings of selected functions | Heuristic-total-consumption is opt-in and selector identity is caller-configured. | Import/class rebinding regressions in `test_heuristic_total_consumption.py`. |
| [4446396725](https://github.com/sheepfling/alphus/pull/76#discussion_r4446396725) | Invalidate rendered bindings reassigned in expression statements | Opt-in rendered-value contract. | Expression-statement and walrus regressions in `test_rendered_value_reparsed.py`. |
| [4446451187](https://github.com/sheepfling/alphus/pull/76#discussion_r4446451187) | Limit rebinding suppression to affected function | Functional scope gap in the opt-in total-consumption detector. | Per-function rebinding isolation regression in `test_heuristic_total_consumption.py`. |
| [4446451201](https://github.com/sheepfling/alphus/pull/76#discussion_r4446451201) | Recognize verbose mode among combined inline flags | Functional regex-parser gap in the unselected prose-as-control detector. | Combined inline flag and verbose syntax regressions in `test_prose_as_control.py`. |
| [4446518359](https://github.com/sheepfling/alphus/pull/76#discussion_r4446518359) | Exclude comprehension-local targets from module binding counts | Functional scope gap in shared module-binding analysis; the semantic consumers are opt-in. | Comprehension target versus walrus binding tests in `test_module_bindings.py`. |
| [4446518369](https://github.com/sheepfling/alphus/pull/76#discussion_r4446518369) | Verify path-comprehension attribute root is the target | Provenance ownership is opt-in and requires configured path/ownership semantics. | Correct-root and wrong-root cases in `test_provenance_ownership.py`. |
| [4446603568](https://github.com/sheepfling/alphus/pull/76#discussion_r4446603568) | Invalidate walrus writes in assignment values | Opt-in rendered-value contract. | Assignment-value walrus mutation regressions in `test_rendered_value_reparsed.py`. |

The root profile also omits all consumer-specific semantic rule selectors by
design. Enabling them for Alphus without a contract would create unsupported
claims, not improve self-review coverage. The package test step does execute
the detector regression suite, which protects implementation behavior without
pretending those detectors have an Alphus-specific runtime policy.

## Author/editor comments

| Review comment | Concern | Classification and disposition |
| --- | --- | --- |
| [4447793392](https://github.com/sheepfling/alphus/pull/76#discussion_r4447793392) | Explain mapping keys in provenance ownership | Human-judgment/documentation concern: no static rule can determine whether a local mapping key has adequate domain meaning. The detector now documents key names as local identifiers and its configured `_OwnerPathSet` values. |
| [4447797498](https://github.com/sheepfling/alphus/pull/76#discussion_r4447797498) | Replace heterogeneous provenance tuples | **Self-review policy gap fixed:** the named-result rule had omitted this detector file. It now uses semantic record types and `provenance_ownership.py` is included in `semantic_result_paths`. |
| [4447799970](https://github.com/sheepfling/alphus/pull/76#discussion_r4447799970) | Extract hard-coded AST cap | A lone numeric cap was not covered by the repeated-literal rule; that rule only reports duplication. The cap is now a named constant. No general magic-number rule is claimed. |
| [4447807922](https://github.com/sheepfling/alphus/pull/76#discussion_r4447807922) | Replace rendered-value tuples | **Self-review policy gap fixed:** `rendered_value_reparsed.py` now participates in `semantic_result_paths`, and the API uses a named result record. |
| [4447810502](https://github.com/sheepfling/alphus/pull/76#discussion_r4447810502) | Clarify dict semantics and add a docstring | Documentation/human-judgment concern; no selected static rule can prove that a dictionary's semantics are sufficiently documented. The binding map's purpose is documented, but semantic adequacy remains review work. |
| [4447816919](https://github.com/sheepfling/alphus/pull/76#discussion_r4447816919) | Make the runner export intentional | No existing self-review rule checks intended `__all__` policy. Fixed with an explicit `__all__` and a test asserting the public runner export. |
| [4447821432](https://github.com/sheepfling/alphus/pull/76#discussion_r4447821432) | Avoid manual runner/registry coupling | The intended catalog is explicit configuration, but dispatch is now generated deterministically at build time as static imports. Duplicate/catalog-coverage/stale-manifest tests run in package tests. Runtime discovery/import scanning is intentionally unsupported to preserve static package boundaries. |
| [4447825152](https://github.com/sheepfling/alphus/pull/76#discussion_r4447825152) | Replace unexplained-empty-result tuples | **Self-review policy gap fixed:** `unexplained_empty_results.py` now participates in `semantic_result_paths` and uses named result records. |
| [4447831171](https://github.com/sheepfling/alphus/pull/76#discussion_r4447831171) | Make consumer fixture paths independent of CWD | Test-source path inspection is intentionally excluded by `inspection_exclude = ["tests/**"]`; generic path text cannot establish the intended base directory. The fixture now supplies `examples_root`, and a changed-CWD regression guards it. |
| [4447633045](https://github.com/sheepfling/alphus/pull/76#discussion_r4447633045) | Give calibration documentation durable purpose and hierarchy | Documentation review concern, not a selected executable rule. Addressed by placing the calibration record in the review documentation hierarchy with purpose, boundaries, and extension guidance. |

Repeated-literal coverage had also omitted `parallel_normalization.py`, where
the AST node cap occurred twice. That path is now included in
`repeated_literal_paths`; a self-profile configuration regression asserts both
the three named-result paths and the repeated-literal path are selected.

## Validation boundary

The repository `check` profile is the self-review entry point. At this audit it
completed with 26 passed, 0 failed, and 3 provisional checks; its package test
step reported 1364 passed and 23 skipped. These results show the selected
policy and regression suite pass. They do not establish that opt-in semantic
detectors were run against Alphus source, nor that static analysis can decide
human questions such as intended registry semantics or documentation quality.

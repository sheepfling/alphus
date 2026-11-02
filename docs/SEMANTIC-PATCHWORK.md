# Prose-as-control review

The `prose-as-control` advisory detects long, sentence-like string literals
used in `if`, `while`, or conditional-expression comparisons within explicitly
selected Python paths. It is a review candidate: prose may be part of a stable
external protocol, compatibility behavior, or a deliberate content predicate.
List known protocol/compatibility literals in `allowed_literals` and narrow the
source scope. The rule has no default profile selection.

The [consumer example](../examples/review/prose-as-control.toml) selects one
renderer path and opts into the provisional rule. Consider whether behavior
could instead branch on a named mode/state while keeping full prose as data;
review the protocol contract before changing code.

This rule does not infer AI authorship, prove a defect, or detect the other
semantic-patchwork patterns in issue #50. It does not cover long strings that
flow through variables or helpers, or comparisons outside supported branch
tests. Allowlisting and scope are explicit consumer decisions.

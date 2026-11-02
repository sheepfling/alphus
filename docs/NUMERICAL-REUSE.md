# Numerical reuse review

`manual-matrix-kernels` is an opt-in advisory for one narrow syntax: an outer
list comprehension over `range`, containing an inner list comprehension over
`range`, whose elements sum `left[i][k] * right[k][j]` over one more `range`.
It only scans explicitly configured source paths. Shadowed `sum` or `range`
names suppress the file because their semantics are unknown.

A match is a review prompt. It does not establish that the code is incorrect,
slow, or equivalent to a library implementation. Dtype, precision, shapes,
output layout, summation order, exceptions, and mutation behavior can all
matter. There is no automatic rewrite or dependency suggestion. Educational
examples, reference oracles, custom arithmetic and small fixed-size formulas
may be intentional; exclude them or keep the advisory disabled.

The first-slice example is [`manual-matrix-kernels.toml`](../examples/numerics/manual-matrix-kernels.toml).
It selects `src/numerics/*.py` only; adapt that path to a consumer-owned numeric
module. Other proposed families in issue #58—array conversion churn,
Cholesky-like recurrences, handwritten elimination, rotations and quaternion
math—are not covered by this rule.

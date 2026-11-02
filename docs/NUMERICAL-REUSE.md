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

The consumer example also offers an independent `array-representation-churn`
advisory. It recognizes only a direct, same-expression call such as
`np.asarray(values.tolist())`, and only when the outer constructor is explicitly
configured. It excludes control-flow-contained expressions, unknown helpers,
keywords, and intermediate assignments by requiring the direct nested-call
form. This is a review prompt, not a measured performance claim; the list may
be an intentional serialization or API boundary.

The profile selects `src/numerics/*.py` only; adapt that path to a
consumer-owned numeric module. Cholesky-like recurrences, handwritten
elimination, rotations, and quaternion math remain unimplemented and are not
implied by these two narrow detectors.

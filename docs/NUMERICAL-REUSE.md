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

The profile selects `src/numerics/*.py` only for numeric kernels; adapt those
paths to consumer-owned modules.

The separate opt-in `cholesky-recurrence` advisory recognizes one coordinated
lower-triangular recurrence shape: prior-factor product reduction, a configured
square-root helper in the diagonal branch, and division by the earlier
diagonal in the off-diagonal branch. It reports syntax evidence only; it does
not judge whether an input is SPD or PSD, prove the recurrence correct, or
recommend removing consumer validation. The configured square-root helper and
source paths are required. Conjugate/Hermitian arithmetic and other recurrence
forms remain unknown.

`manual-quaternion-products` is a separate, consumer-configured detector for
one scalar-first Hamilton product form. The policy names the exact function and
the four left, four right, and four output component identifiers. One tuple
assignment must match all four bilinear equations, including signs; four-vector
arithmetic or a function name alone does not trigger. This does not resolve
quaternion types, aliases, scalar-last layouts, separate assignments,
conjugation, inversion, normalization, sandwich rotation, or matrix conversion.
Review any reuse proposal for composition order, handedness, active/passive
convention, unit-norm behavior, zero and non-finite handling, dtype, shape, and
returned representation. A match says nothing about correctness or speed.

Handwritten elimination and frame-transform recognition remain unimplemented.
So do the other quaternion fingerprints and Cholesky covariance/domain checks.
The current examples demonstrate only the explicitly documented syntax
families above.

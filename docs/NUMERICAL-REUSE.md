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
quaternion types, aliases, scalar-last layouts, or separate assignments.
Review any reuse proposal for composition order, handedness, active/passive
convention, unit-norm behavior, zero and non-finite handling, dtype, shape, and
returned representation. A match says nothing about correctness or speed.

`manual-quaternion-conjugation` recognizes one additional exact function form:
a configured function with four configured scalar parameter names and a single
direct return `(w, -x, -y, -z)` (optionally preceded by a docstring). It does not
infer quaternion identity from a tuple or function name; the configured path,
function, and component names supply that contract. Branching, reassignment,
attribute-based components, and aliases are skipped. The rule does not
recognize general inversion, normalization, sandwich rotation, or matrix
conversion.

Handwritten elimination and frame-transform recognition remain unimplemented.
So do the other quaternion fingerprints and Cholesky covariance/domain checks.
The current examples demonstrate only the explicitly documented syntax
families above.

An elimination recognizer would need a consumer contract that identifies the
matrix representation and then match, within one configured function, pivot
selection, a row swap, diagonal normalization, and elimination updates that use
the same row and pivot indices. A row update or call to `max` alone is not
enough. The result should be described as a review of a handwritten elimination
kernel; it must not infer that a true inverse is needed or that a solve routine
is equivalent.

A frame-transform recognizer would additionally need the consumer's configured
preferred helper and an explicit equivalence contract for frame, origin,
latitude type, angle and length units, axis order, handedness, rotation
composition, vector-versus-position semantics, and output shape. Trigonometric
calls or a 3x3-looking assignment do not establish equivalence. Until a
candidate grammar can bind those details to a tested consumer contract, it
should remain unknown rather than produce a confident duplicate-transform
finding.

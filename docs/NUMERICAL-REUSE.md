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
advisory. Outside the contracted loop mode below, it recognizes only a direct,
same-expression call such as
`np.asarray(values.tolist())`, and only when the outer constructor is explicitly
configured. It excludes control-flow-contained expressions, unknown helpers,
keywords, and intermediate assignments by requiring the direct nested-call
form. This is a review prompt, not a measured performance claim; the list may
be an intentional serialization or API boundary.

For a possible per-iteration repetition, `loop_contracts` can select one exact
path, function, and array variable. The detector requires a direct assignment
such as `rebuilt = np.asarray(batch.tolist())` in a simple `for` body, a
constructor resolved through a module import, and a later straight-line use of
`rebuilt` in that same iteration. The contract supplies the array identity; a
name or `.tolist()` call alone is insufficient. Nested branches, local aliases,
reassignment, shadowed or unresolved constructors, and unused reconstructed
values stay unknown. This reports a representation change written inside a
loop, not that the loop is hot or that the code is slower. Check representative
workloads and preserve dtype, shape, output type, ownership and serialization
behavior before considering a change.

Example selector:

```toml
[[checks.array_representation_churn.loop_contracts]]
path = "src/numerics/kernels.py"
function = "process_batches"
array_variable = "batch"
```

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

`manual-quaternion-normalization` recognizes one strict direct-return sequence
in a consumer-configured function:

```python
norm = math.sqrt(w * w + x * x + y * y + z * z)
unit = (w / norm, x / norm, y / norm, z / norm)
return Rotation.from_quat(unit)
```

The configured four scalar parameters must form the sum of four squares under
the configured square-root helper; each parameter must be divided by that same
local norm in one tuple assignment; and that tuple must be passed immediately
to a configured rotation consumer. The rule does not infer
quaternion identity or import aliases. It skips separate statements, branches,
intervening work, generic vector normalization, nonmatching square forms, and
unknown consumers. It does not prove that the operation is unnecessary or slow;
preserve zero/near-zero and non-finite behavior, ordering, dtype, and the
consumer's normalization contract.

`manual-quaternion-inversion` recognizes one exact function body in a configured
scope: a local sum of all four configured component squares followed by a tuple
return that divides the scalar component by that sum and the three vector
components negated over that same sum. This is the general conjugate-over-norm
squared inverse shape; it is distinct from unit-quaternion conjugation. It skips
branches, aliases, reassignment, attributes and alternate algebraic forms. It
does not establish that a dependency is suitable or that the kernel is wrong or
slow. Preserve zero and non-finite behavior, component convention, dtype,
returned representation, and non-unit semantics.

`manual-elimination` recognizes one configured direct-list Gauss-Jordan shape:
maximum-absolute pivot selection over the current column, an in-place row swap,
pivot-row normalization by its diagonal, then elimination of every other row
using the same pivot column. It requires those operations in one top-level or
class method with direct matrix indexing and no intervening statements. Aliases,
other matrix representations, separate RHS vectors, alternate pivot APIs,
branches and factorization variants are out of scope. The finding identifies a
handwritten elimination candidate; it does not imply that a matrix inverse is
needed or that a library routine preserves representation, pivoting, stability,
dtype or failure behavior.

`manual-quaternion-vector-rotation` recognizes a configured direct expression
`multiply(multiply((w, x, y, z), (0, vx, vy, vz)), conjugate((w, x, y, z)))`.
The configured component order and helper spellings are required; aliases,
separate statements, alternate multiplication APIs and matrix-conversion forms
are not followed. The configured helper names are syntactic evidence, not
interprocedural proof of their implementations. This reports a review candidate,
not a defect or speedup; conjugation is the inverse only for unit quaternions, so
normalization, handedness, active/passive convention, dtype, failures, and output
shape remain consumer contracts.

`manual-quaternion-matrix-conversion` matches one configured scalar-first,
active column-vector formula returned directly as a 3×3 nested list or tuple.
It skips transposed/sign-alternate formulas, intermediate assignments, aliases,
branches, and different layouts. The configured convention describes the
recognized syntax; it does not establish that a consumer documents or intends
that convention. Review handedness, active/passive semantics, vector orientation,
normalization, dtype, failures, and output shape before considering reuse. The
finding does not establish a defect or performance gain.

`ecef-enu-transform` is an opt-in exact fingerprint for one direct tuple return
that rotates an ECEF **displacement vector** into right-handed ENU at an anchor
point. Its policy must declare geodetic latitude, radians, meters, the
east/north/up tuple layout, reference ellipsoid, and a preferred helper name.
The only supported grammar uses `math.sin`/`math.cos` with the configured
`(dx, dy, dz, latitude, longitude)` signature and the exact basis signs and
products. It rejects imported aliases, local aliases, shadowed `math`, matrix
outputs, positions with translation, intermediates, branches, alternate
formulas, and other axis orders. The configured helper is a maintainer-provided
review target; its existence or semantic equivalence is not verified. This
detector does not cover NED, geocentric latitude, degree inputs, other datums or
ellipsoids without explicit policy support, batches, covariance, positions, or
quaternion composition. The finding is only a candidate to review against the
declared origin/datum, vector semantics, shape, dtype, and failure behavior; it
does not establish a defect or performance gain.

`ecef-ned-matrix-transform` is a separate opt-in fingerprint for a geodetic
ECEF-to-NED row-major 3×3 matrix applied to column displacement vectors at an
anchor. Its policy declares the reference ellipsoid, geodetic latitude, radian
inputs, length units, N/E/D order, right-handedness, matrix layout, and
preferred helper. The supported grammar requires `math` trigonometric
assignments and the exact signed matrix passed to a configured `numpy.array`
import. It does not match ENU, geocentric latitude, a tuple of basis vectors,
positions with translation, row-vector application, or another matrix layout.
In particular, pytaos's geocentric basis is not interchangeable with its
geodetic basis. A match identifies syntax under declarations; it cannot prove
the declarations describe runtime behavior or that the preferred helper exists.

### Bounded source calibration (2026-11-02)

I inspected committed source snapshots only. The local Odonata, pytaos, and
QuatOps worktrees had unrelated uncommitted changes; those changes were not
read for this sample. No consumer repository was modified and no consumer code
was executed. The frame rule was evaluated under the example's exact contract:
ECEF displacement to ENU at an anchor, geodetic latitude in radians, meters,
WGS84, right-handed east/north/up, direct tuple3; candidate selector names were
adapted in memory to inspected function names. This adaptation does not assert
that the ENU example's preferred helper exists in those projects. The separate
NED matrix rule was evaluated against Titan's geodetic ECEF-to-NED row-major
matrix contract with its configured selector names.

#### `sheepfling/Titan`

- Revision: `76c9a8d7fd542296c28ec9da58355f58e34176af`.
- Paths: `packages/titan-simulation/src/titan_simulation/coords.py`, lines
  50–58, 61–78, and 130–139.
- Candidate: `ecef_to_ned_matrix` returns an ECEF-to-NED matrix, used for
  velocity conversion and transposed for NED-to-ECEF. The file documents
  WGS-84 and the matrix formula's radian inputs.
- ECEF-to-ENU result: no match because NED matrix output differs from its
  configured ENU displacement tuple.
- ECEF-to-NED result: one exact matrix site at return line 54 with policy names
  adapted to `lat_rad`, `lon_rad`, `slat`, `clat`, `slon`, and `clon`. The helper
  is already reused at the inspected call sites. This is a syntactic match,
  not independent verification of matrix semantics.

#### `sheepfling/pytaos`

- Revision: `331c0848032bfc01ab87fd5f27b73776fbac88c9`.
- Paths: `src/taoryx/equations/geodesy.py`, lines 143–174, 336–367, and
  395–411; `src/taoryx/contracts/frames.py`, lines 12–22.
- Candidate: geocentric and geodetic north/east/down basis builders return
  three `CartesianVector3` values; velocity transforms compose/decompose
  through those helpers. Frame names distinguish ECFC from geocentric and
  geodetic horizon frames.
- Result: no match for either rule. This is a tuple of named N/E/D basis
  vectors, not the configured direct ENU vector or row-major ECEF-to-NED
  matrix. Geocentric and geodetic bases remain separate contracts; no
  equivalence is inferred. The basis helpers are already composed by the
  inspected velocity transforms.

#### `sheepfling/odonata`

- Revision: `b04351e3c8f6f589fceeb781d1ad142f1ff4d7ac`.
- Path: `src/odonata/frames/astropy_transform.py`, lines 17–54.
- Candidate: the transformer delegates TEME-to-ITRS-to-GCRS position and
  velocity conversion to Astropy with epoch/EOP and unit handling.
- Result: no match. This is a library-backed position-and-differential
  transformation with different frames, shape, and contracts.

#### `sheepfling/quatops`

- Revision: `541edb9362b14469e98501894cc85757b062de48`.
- Paths: `src/quatops/scalar.py`, lines 135–162, and
  `src/quatops/numpy/hamilton/wxyz.py`, lines 98–129.
- Candidate: scalar and NumPy quaternion rotations use a non-unit-safe active
  rotation, scaled arithmetic, and return vectors; the NumPy form supports
  batches.
- Result: no frame match. The six configured quaternion matchers also returned
  no sites on these modules with selectors adapted to `multiply`, `conjugate`,
  `inverse`, `normalize`, and `rotate`. This is an existing quaternion library
  and expected negative control; its representation and robust numerical path
  differ from the configured scalar-parameter/tuple kernels.

Observed sample result: the ECEF-to-ENU rule returned zero sites across the
three geodesy snapshots. The ECEF-to-NED matrix rule returned one site in Titan
and no site in pytaos's distinct basis-vector functions. This selected sample
is too small to estimate precision or recall; no downstream duplicate-helper
case was present. Helper equivalence and detector behavior across consumer
conventions remain uncalibrated.

Other frame-transform conventions and basis-vector return forms remain
unimplemented, as do Cholesky covariance and domain checks. The numerical
examples demonstrate only their explicitly configured syntax families. The quaternion normalization,
inversion, sandwich, matrix-conversion, and ECEF-to-ENU grammars have synthetic
positive/negative coverage but no reviewed downstream reimplementation
calibration or production precision estimate yet.

An elimination recognizer would need a consumer contract that identifies the
matrix representation and then match, within one configured function, pivot
selection, a row swap, diagonal normalization, and elimination updates that use
the same row and pivot indices. A row update or call to `max` alone is not
enough. The result should be described as a review of a handwritten elimination
kernel; it must not infer that a true inverse is needed or that a solve routine
is equivalent.

A broader frame-transform recognizer would additionally need the consumer's
configured preferred helper and an explicit equivalence contract for frame,
origin, latitude type, angle and length units, axis order, handedness, rotation
composition, vector-versus-position semantics, and output shape. The shipped
ECEF-to-ENU fingerprint binds these as policy declarations and exact syntax,
but cannot prove that the declarations describe runtime behavior. Trigonometric
calls or a 3x3-looking assignment do not establish equivalence; unsupported
forms remain unknown.

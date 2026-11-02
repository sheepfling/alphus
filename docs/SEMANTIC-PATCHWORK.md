# Semantic patchwork review

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

The same opt-in rule can separately enable `lossy_text_rewrite`. Regex calls
must name an explicitly configured `regex_sub_helpers` entry, such as `re.sub`,
and use a literal `\d` outside lookarounds and negated character classes, with
an empty or space replacement. This lexical check does not evaluate arbitrary
regex matching behavior or prove a match removes text. Literal
`.replace` calls are also reported when they erase a token containing digits
or semantic punctuation such as signs and delimiters. A nonzero constant `count`
argument is supported; `count=0` and unknown counts are left unreported. Ordinary
word replacement, whitespace cleanup, and non-erasing replacements are outside
this detector. The receiver type is not inferred, so a custom `.replace` API can
be an intentional match. A consumer can add an exact `allowed_literal_rewrites`
item with a path pattern and the displayed `replace(...)` expression for a
reviewed format-specific rewrite. This suppresses only that expression under
matching paths. The check does not trace aliases, establish actual input values,
or prove meaningful content is lost. Numeric text may be intentionally removed
under a declared input contract; exclusions, exceptions, and helper names are
consumer decisions.

For configured regex substitutions, the digit-token scanner ignores zero-only
quantifiers such as `\d{0}` (including verbose-mode spacing), lookaround-only
digit assertions, negated digit classes, and `\d` text inside verbose-mode
comments. This is a narrow lexical
boundary check, not a complete regular-expression semantic analyzer.

`rendered-value-reparsed` uses a separately configured list of rendering helper
names. It detects a local result assigned from one of those calls when the same
value is used in the narrow `rstrip().endswith(<non-empty literal>)` condition
shape. This captures one form of rendered feedback into later branching. It
does not follow aliases, method wrappers, interprocedural data flow, or other
predicates; output-only rendering is intentionally outside the rule.

The separate `positional-semantic-overrides` rule can be scoped with explicit
position-variable names and semantic output fields. It recognizes only literal
integer comparisons or membership tests followed immediately in the branch by
a configured mapping-field assignment with a long string value. It does not
resolve whether the mapping row corresponds to that position, and it abstains
on indirect assignments and other control flow. A match is a review prompt;
some source formats legitimately require documented position-specific fixes.

`unexplained-empty-results` detects only an explicitly configured
`if records and not inferred_schema: return []` shape. It requires consumer
names for a truthy input collection and an unavailable-inference flag. It does
not trace aliases, infer collection truthiness, inspect filters or nested
returns, or conclude that an empty result is always wrong. Valid empty input
remains a negative case.

`embedded-semantic-overrides` looks for a configured mapping call assigned to a
local, an `is not None` branch, and a return that adds that local replacement
to a configured source-anchor helper result. It does not determine whether
source wording was discarded or whether the anchor is stale; it flags this
specific combination for provenance review. Aliases, other control flow, and
other ways to generate replacement content are outside the detector.

`heuristic-total-consumption` requires an explicit contract that configured
top-level functions preserve unmatched input spans, plus configured token-matcher names.
It reports only a direct return of the matcher's results, or a single local
capture followed by its direct return. This does not resolve helper aliases,
infer the consumer's real output contract, or prove that omitted spans matter.
Legitimate lossy extractors should not be configured under the preserving
contract; unmatched-span and multi-step reconstruction patterns are outside
the supported grammar.

These checks do not infer AI authorship or prove a defect.

## Issue #50 delivery boundary

The four P0 checks are implemented as opt-in advisories: prose-as-control,
lossy-text-rewrite, rendered-value-reparsed, and positional-semantic-override.
Four narrow P1 shapes are also implemented: unexplained-empty-result,
embedded-semantic-override, heuristic-total-consumption, and
provenance-as-ownership. These are
consumer-configured syntactic candidates, not proof that output is wrong. The
embedded rule only recognizes the configured replacement-map/source-anchor
shape; the total-consumption rule only recognizes the two direct-return forms
described above. Provenance-as-ownership requires an explicit exact-source-span
contract and only recognizes a path set built from configured owner records
that is used to exclude configured candidate records by `source.path`.
Consumers that intentionally define file-level ownership can declare
`ownership_basis = "file-scope"`; the rule then abstains. A finding asks whether
same-file distinct spans should remain eligible. It does not establish record
ownership, source overlap, or a defect.

The remaining P1 proposal is the consumer-scoped
semantic-work-in-presentation boundary. It needs independently declared
module-role and operation contracts before a useful composite can be calibrated.
The P2 proposals are also deferred: evaluate
parallel-normalization through the existing duplication capabilities and issue
[#33](https://github.com/sheepfling/alphus/issues/33), and do not ship a
patch-cascade heuristic without reviewed real clusters and actionable
remediation. None of these deferred patterns is implied to be covered. The new
P1 rule has synthetic boundary tests but no positive production calibration;
its precision is not estimable.

The [calibration note](SEMANTIC-PATCHWORK-CALIBRATION.md) records both the
reviewed synthetic boundary corpus and a small non-fixture source sample. The
synthetic labels validate detector behavior, not production precision. Public
scans produced no reviewed positive candidates, so precision is not estimable.

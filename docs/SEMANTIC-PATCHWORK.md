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
Five P1 shapes are also implemented: unexplained-empty-result,
embedded-semantic-override, heuristic-total-consumption,
provenance-as-ownership, and semantic-work-in-presentation. These are
consumer-configured syntactic candidates, not proof that output is wrong. The
embedded rule only recognizes the configured replacement-map/source-anchor
shape; the total-consumption rule only recognizes the two direct-return forms
described above. Provenance-as-ownership requires an explicit exact-source-span
contract and only recognizes a path set built from configured owner records
that filters configured candidate records by `source.path` when that filtered
list is returned directly or assigned and immediately returned. An unused
filter result is ignored.
Consumers that intentionally define file-level ownership can declare
`ownership_basis = "file-scope"`; the rule then abstains. A finding asks whether
same-file distinct spans should remain eligible. It does not establish record
ownership, source overlap, or a defect.

The presentation-boundary rule requires a consumer to declare the selected
paths as `presentation`, list exact functions, and configure distinct helpers
for source-layout reconstruction, content correction, semantic ownership, and
serialization. It reports only when all four configured call-name groups occur
within one selected function. It does not resolve aliases, prove data flow or
coupling between operations, or claim that any presentation transformation is
wrong. Calls in defaults, annotations, decorators, or nested function/class
bodies are ignored. Co-location is a prompt to review the declared
responsibility boundary.
The narrow parallel-normalization rule is implemented only for a
consumer-declared pair of equivalent `str` functions, each returning a direct
`join(split(input))` expression. It reports differing literal split or join
separators under an explicit same-output contract. Existing shared-utility
fingerprinting groups identical AST bodies and therefore does not cover this
separator-drift case. The rule does not infer that two helpers are equivalent;
aliases, multi-step transformations, and unconfigured functions are outside
its grammar. A pair must be defined in the same selected file; cross-file
pairing is unsupported and currently produces no finding rather than a
cross-file coverage diagnostic. This P2 advisory lacks positive production
calibration.

The opt-in `patch-cascade` advisory requires the consumer to identify a
top-level function as a `general-parser`, enumerate its repair selector and
source-specific repair IDs, and list normalization helper names. It recognizes
only at least two separate equality branches comparing that selector with
configured string IDs, where each branch calls a configured helper. It
abstains if the selected parser is rebound or a configured helper root is
locally rebound. Nested functions do not contribute. The finding asks whether
the declared repair cluster belongs in shared parsing policy; it does not
prove the repairs are unrelated, unnecessary, or incorrect. A legitimate
parser may require exactly these exceptions. The detector does not prove call
effects, trace helper aliases or data flow, recognize compound guards, or
calibrate production precision. No positive production calibration has been
performed; this advisory currently has synthetic boundary tests only.

Example opt-in configuration:

```toml
[checks.patch_cascade]
extensions = [".py"]
exclude = []
source_paths = ["src/parser.py"]

[[checks.patch_cascade.functions]]
function_name = "parse_document"
selector_names = ["repair_id"]
repair_ids = ["vendor-a", "vendor-b"]
normalization_helpers = ["normalize_text"]
function_contract = "general-parser"
```

The P1
rules have synthetic boundary tests but no positive production calibration;
their precision is not estimable.

The [calibration note](SEMANTIC-PATCHWORK-CALIBRATION.md) records both the
reviewed synthetic boundary corpus and a small non-fixture source sample. The
synthetic labels validate detector behavior, not production precision. Public
scans produced no reviewed positive candidates, so precision is not estimable.

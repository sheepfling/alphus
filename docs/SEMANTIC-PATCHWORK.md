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

The same opt-in rule can separately enable `lossy_text_rewrite` with explicit
`regex_sub_helpers`, such as `re.sub`. That narrow check reports a configured
regex call with a literal `\d` pattern and an empty or space replacement. It
does not trace aliases, establish actual input values, or prove meaningful
content is lost. Numeric text may be intentionally removed under a declared
input contract; exclusions and helper names are consumer decisions.

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

These checks do not infer AI authorship or prove a defect. Other patterns in
issue #50, including source
replacement/provenance, heuristic unmatched-span loss, empty-result handling,
ownership, module boundaries, and patchwork clusters remain uncovered.

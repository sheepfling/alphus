# Argparse destination precedence

Selector: `argparse-precedence`. Risk ID:
`alphus/python/none/correctness/argparse-default-overwrite`. Coverage ID:
`alphus/python/none/correctness/argparse-precedence-unassessed`.

This opt-in advisory reviews explicitly selected Python parser declarations
without importing or executing consumer code. It is separate from the existing
CLI contract and presentation policy, which is unchanged. No existing default
profile enables it. See the standalone
[argparse policy](../examples/review/argparse-precedence.toml).

Argparse parses subcommands into a separate namespace, then copies the child
namespace into the ancestor namespace. If both parsers declare an optional
store action for the same destination, omitting the child option can therefore
replace an explicitly supplied ancestor value with the child's default. Even
an implicit `None` default can cause the overwrite. Matching uses the parsed
namespace destination, including literal `dest`, rather than option spelling.
Nested subcommands can repeat the problem at each level.

For example, a root `--output selected.txt` followed by `export` can select the
child's `default.txt` rather than `selected.txt`. Equal root and child defaults
do not make this safe: an explicit root value can still be different. Where
absence should preserve the ancestor value, review using
`default=argparse.SUPPRESS` on the child action. This does not remove the
legitimate ability for an explicit later child option to override an ancestor
option. Check the actual produced output in isolated temporary directories,
including both documented option placements and omitted options, rather than
asserting only on parser namespaces. No automatic rewrite is offered.

## Supported declarations and coverage limits

The static model is intraprocedural and straight-line. It recognizes unshadowed
direct `argparse` imports and aliases, literal optional store-action declarations,
root and nested subparser relationships, literal defaults,
`argparse.SUPPRESS`, and declaration-order effects of `set_defaults`.
Only module bodies and top-level function bodies are assessed; nested functions
and classes are unassessed. The first `parse_args`, `parse_known_args`, or return
of the parser ends the construction scope. Later construction or another parse
boundary is unassessed rather than silently skipped. An unshadowed `type=str` is
supported; other conversion types, `nargs`, `choices`, and argument groups are unassessed.
A literal required child option cannot be omitted and is not this default
precedence risk. `set_defaults` can replace an action's suppressed default.
A parser-level default installed before an action also persists even if the
later action specifies `default=argparse.SUPPRESS`. Crucially,
`set_defaults(output=argparse.SUPPRESS)` does not remove the parser default:
it assigns the literal suppression-marker string as a value. Remove the
parser-level destination default when absence should preserve the ancestor
value, and verify the resulting behavior with an executable regression.

Unknown parser construction, helper factories, `parents`, custom actions or
parser classes, parser mutation or escape, and branches or loops are outside
the bounded model. Unknown or unsupported argument option fields invalidate
the affected scope rather than proving it safe. Coverage notes always use
`info`, even when the risk policy uses a stricter severity. Unassessed means
manual review or an executable regression is needed, not absence of a bug.
The analysis does not prove runtime output routing, wrapper behavior, or the
correctness of custom namespace merging. It assumes the standard library's
`argparse` implementation, not replacement modules or invisible monkey patches
in uninspected dependencies. Known local rebinding or mutation is unassessed.
Synthetic executable and differential tests establish the supported mechanics;
they are not a real-world calibration set or a measured precision score.

The existing CLI selector inventories endpoint contracts and presentation.
Its broader name-resolution logic is not reused as proof of parser identity.
This advisory has an independent AST model and normal review-runner, policy,
selector, and catalog registration; it does not alter CLI enforcement behavior.

## Intentional precedence and policy scope

A command-specific default may intentionally supersede an ancestor option.
Custom merge logic or wrappers may implement a different contract. Separate
destinations can distinguish global defaults from command-specific choices;
required child options can make omission impossible. Review these designs
against the documented CLI rather than mechanically adding suppression.

`checks.argparse_precedence` requires `extensions = [".py"]` and a nonempty
`source_paths` pattern list. `exclude` defaults to empty and risk `severity`
defaults to `info`. Consumer selection is deliberate: enabling the selector
without its policy is a configuration error. The optional `exceptions` array
acknowledges an intentional overwrite using an exact repository-relative
`path`, a nonempty namespace `destination`, and a specific `reason` of at
least 20 characters. Each path/destination pair must be unique. Exceptions
suppress only matching risk advice, not uncertainty about unsupported code.

```toml
[[checks.argparse_precedence.exceptions]]
path = "src/cli/export.py"
destination = "output"
reason = "Export intentionally ignores the global output when its option is omitted."
```

Use the example as a separate consumer-owned profile. Do not replace existing
CLI policies or enable this advisory globally on the strength of a catalog tag.

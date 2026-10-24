# Source text and file hygiene

Alphus provides shared `line-length` and `file-size` checks for consumers that
want a simple, language-neutral limit. These checks measure text and bytes;
they do not parse every language or try to reproduce each native linter's
exceptions.

## Measurements

| Policy        | Measurement                               | Boundary behavior                                |
| ------------- | ----------------------------------------- | ------------------------------------------------ |
| `line-length` | Unicode code points per physical line     | Excludes terminator; equal passes.               |
| Code lines    | Physical lines for code suffixes          | Blank and comment lines count.                   |
| Hard lines    | Physical lines in each selected file      | Blank and comment lines count.                   |
| Raw bytes     | Raw bytes, including BOM and newlines     | Equal passes; over limit reports measured bytes. |
| Initializer   | Physical lines in the package initializer | Blank and comment lines count.                   |

Physical lines use LF, CRLF, or CR separators. An empty file has zero physical
lines. A line ending terminates one line and does not create a synthetic extra
line; unterminated content at EOF is one line. CRLF counts as one separator.
File-size checks count the bytes directly, so binary content and invalid text
encodings do not change the physical-line or raw-byte measurement. The
package-initializer AST checks still need Python-readable source; an unknown or
invalid encoding fails that check instead of passing.

`line-length` reads selected files as strict UTF-8. A UTF-8 BOM is retained and
counts as one code point. Tabs count as one code point; combining marks count
individually; trailing spaces count. Visual terminal columns, grapheme clusters,
and tab-expanded widths are not inferred. An invalid UTF-8 sequence produces an
`invalid-text-encoding` finding instead of a clean result.

File suffix selection is case-normalized to lowercase. The shared checks do not
guess whether a file is generated or binary. Use `[files].exclude` to keep those
paths out of the repository inventory, or the rule's `exclude` list to narrow a
single check. The built-in Git inventory skips symlinks and paths that resolve
outside the checkout. Consumers that supply a custom inventory should apply
the same boundary before calling the checks.

## Backward compatibility and configuration

The original `code_limit` and `hard_limit` keys remain accepted and continue to
mean physical lines. New policies can use the explicit names. If both a legacy
name and its explicit equivalent are set, they must have the same value.
`[checks.line_length.limits]` remains the legacy extension table; new policies
can use `[checks.line_length.codepoint_limits]`. When both tables define the
same extension, the values must agree.

Extension defaults can be narrowed by path overrides. For line length, a
matching `path_codepoint_limits` entry wins over `codepoint_limits` or the
legacy `limits` table. For raw bytes, the order is:

1. A matching `path_raw_byte_limits` entry.
2. A matching `raw_byte_limits` extension entry.
3. `raw_byte_limit`, when configured.

For path overrides, an exact path wins over a glob. Among globs, the pattern
with more literal path segments wins, then the one with more literal
characters, then the one with fewer wildcard characters. If those measures
tie, the lexicographically first pattern wins. This makes the result
independent of TOML table order. Exclusions are applied before limit selection.

```toml
# Relevant overrides only; required baseline fields are omitted.
[checks.file_size]
raw_byte_limit = 500000
raw_byte_severity = "warning"

[checks.file_size.path_raw_byte_limits]
"schemas/**" = 100000
"schemas/public.json" = 200000

[checks.line_length.path_codepoint_limits]
"docs/api/**" = 140
```

The optional byte metric is advisory by default. Set `raw_byte_severity =
"error"` or set the selected rule step's `severity = "error"` to make byte
findings fail the profile's default `error` threshold. Existing physical-line
and line-length findings keep their prior error severity. A rule step can set
`severity = "warning"` while a consumer evaluates existing line limits; the
profile's default `failure_threshold = "error"` leaves those findings
non-blocking. Promotion is a consumer policy decision.

## Native tools and ownership

Use a maintained native tool for language-aware whitespace, encoding, and
syntax-specific exemptions. Alphus does not add a syntax-aware line counter or
a shared whitespace fixer.

**Python whitespace and final newline:** Ruff `W291`, `W293`, and `W292`, or
Pylint `C0303` and `C0304` in its [format checker][pylint-format], should own
these concerns. Alphus only measures line length and does not remove whitespace.

**Python line length:** Ruff `E501` deliberately exempts selected URLs,
single-word lines, pragma comments, and license lines. Alphus counts every
configured UTF-8 code point.

**JavaScript and TypeScript whitespace:** Keep these checks in the consumer's
ESLint Stylistic rules and formatter so syntax-aware fixes have one owner.
Alphus does not remove whitespace.

**JavaScript and TypeScript file line count:** ESLint `max-lines` can skip blank
lines and comments, so its result differs from Alphus physical-line counts.

**JavaScript and TypeScript line length:** Use `@stylistic/max-len` when a hard
maximum is needed. ESLint core `max-len` is deprecated; exemptions remain
tool-specific.

**Preferred wrapping:** Prettier's width is a wrapping target, not a hard
maximum. Formatted output can exceed a separate Alphus hard limit.

Do not configure two tools to own the same blocking rule without reviewing
their counting and exemptions. Keep native formatter checks and Alphus hard
limits as separate profile steps when both intents are useful. A native
formatter can pass while a long string or comment still exceeds the shared
hard limit.

The ordinary Alphus checks are read-only. This feature adds no rewriting,
tool installation, or CI trigger changes.

## References

- [Prettier print width](https://prettier.io/docs/options#print-width)
- [Ruff `E501`](https://docs.astral.sh/ruff/rules/line-too-long/)
- [Ruff `W291`](https://docs.astral.sh/ruff/rules/trailing-whitespace/)
- [ESLint `max-lines`](https://eslint.org/docs/latest/rules/max-lines)
- [ESLint core `max-len` deprecation](https://eslint.org/docs/latest/rules/max-len)
- [ESLint Stylistic `max-len`](https://eslint.style/rules/max-len)

[pylint-format]: https://pylint.readthedocs.io/en/latest/user_guide/checkers/features.html

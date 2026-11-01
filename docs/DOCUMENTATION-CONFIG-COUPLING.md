# Documentation/configuration coupling review

`documentation-config` is an opt-in advisory for manually repeated Python
configuration defaults in Markdown. It belongs to the repository gate theme
because it compares files across a repository. It does not add a default check
or change a consumer's existing profile.

```toml
[checks.documentation_config]
source_patterns = ["src/**/*.py"]
documentation_patterns = ["docs/**/*.md"]
exclude = ["tests/**", "examples/**", "docs/archive/**"]

[[checks.documentation_config.suppressions]]
path = "docs/limits.md"
symbol = "IncludeLimits.legacy_limit"
reason = "This historical compatibility value is intentionally kept visible."

[orchestration]
default_profile = "docs-review"

[[orchestration.steps]]
kind = "rule"
name = "Documentation/configuration review"
rule = "documentation-config"
rollout = "provisional"

[[orchestration.profiles]]
name = "docs-review"
steps = ["Documentation/configuration review"]
```

Run the selected profile with `alphus --profile docs-review`. The rule inspects
tracked and non-ignored untracked files under the configured patterns. Findings
point to the Markdown claim and include the Python path and line, symbol, both
values, and the textual matching reason. Same-value claims are labeled as likely
manual duplication; unequal values are conflicts. Both are warnings. Dynamic,
repeated, or unit-ambiguous claims are `info` findings and are not turned into
guessed values.

## Supported evidence

The initial extractor parses Python source with `ast`; it never imports a target
module or evaluates a factory, expression, or annotation. It recognizes scalar
literal assignments to uppercase module names and scalar defaults in
configuration-shaped classes (`*Config`, `*Settings`, `*Options`, `*Limits`,
`*Parameters`, `BaseModel`, `BaseSettings`, `TypedDict`, and matching dataclasses).
An alias is followed only when it names a preceding literal binding in the same
module or class scope. Rebinding and conditional writes are treated
conservatively.

Markdown matching requires the exact, case-sensitive setting name in the same
line as a value relation such as `max_files is 64`, `MAX_FILES: 64`, or an
adjacent table cell. A class field can be named as `IncludeLimits.max_files`;
an unqualified field shared by multiple classes is reported as ambiguous.
Unrelated numbers and unknown names do not create claims. Fenced code,
blockquotes, and lines marked as examples, overrides, or historical text are
skipped.

Numbers compare directly when the document omits units. Byte-unit conversion is
limited to integer settings whose names include `byte`: `KiB`/`MiB`/`GiB` use
binary factors, while `KB`/`MB`/`GB` use decimal factors and remain distinct.
Explicit file-count units are accepted only for names containing `file` or
`count`. Other unit combinations stay unknown. For example, `1 MB` is not
treated as `1 MiB`.

The scanner does not prove that equal prose is generated from, linked to, or
validated against code. Equal values remain suspected manual duplication, even
when a source link or generated-document marker is present. Suppress only a
known intentional pair with a path, symbol, and reason; exclusions can narrow
either side of the scan.

## Coverage limits

This is a narrow first pass, not universal documentation validation. It does
not resolve imports, inheritance, Pydantic `Field` metadata, factories, computed
expressions, environment-variable overlays, framework-specific precedence,
Markdown spanning multiple lines, or semantic synonyms such as “maximum uploads”
for `max_files`. Unsupported values are never executed or guessed; an explicit
claim about one is reported as unknown. Syntax errors or unreadable files are
skipped and should be handled by the repository's normal source/document
validators.

Future work should add separately tested adapters for typed configuration
frameworks and explicit derivation/check evidence. Until then, use the rule to
find a small set of named, change-sensitive facts for human review rather than
to establish that all documentation is current.

# Positional interface safety

Alphus keeps parameter counts, same-type interface shape, and call-site order as
separate review intents. The counts are useful design signals, but a short
signature can still expose two easy-to-swap values. This feature starts with
native diagnostics and an opt-in Python advisory for the narrow gap described
below. It does not rewrite signatures or normalize native diagnostics.

## Capability matrix

| Intent | Python | C/C++ | JavaScript / TypeScript |
| --- | --- | --- | --- |
| Total parameter count | Ruff PLR0913 or Pylint R0913 | No universal clang-tidy parameter-count check is selected here | ESLint `max-params` |
| Positional parameter count | Ruff PLR0917 or Pylint R0917 | Use a backend-specific native rule if configured | `max-params` counts declared parameters; it does not detect same-type swaps |
| Easily swappable definition | Alphus advisory for directly annotated builtin primitives; native Ruff/Pylint count rules do not identify same-type pairs | clang-tidy `bugprone-easily-swappable-parameters` | No Alphus check in this release; ESLint core `max-params` is count-only |
| Suspicious call order | Pylint W1114 compares argument names with parameter names | clang-tidy `readability-suspicious-call-argument` compares names; `bugprone-swapped-arguments` focuses on suspicious conversions | No Alphus check in this release; no custom ESLint rule is enabled |

These mappings express related intent, not equal measurements. Ruff PLR0917
was added in Ruff 0.16.0; Pylint R0917 is available from Pylint 3.3.0. Keep
each consumer's current version pins and native configuration, then enable only
rules supported by that installed version. `max-params` counts declarations
and has TypeScript-specific handling for the `this` parameter. Named options
objects are an architectural option for APIs where call-site names improve
clarity; the ESLint count rule does not enforce or prove that remedy.

The clang-tidy definition check uses the compiler's type system, including
convertible adjacent parameter types, and applies its own filtering and
suppression heuristics. The name-based call-site check is separate. The
conversion-based swapped-arguments check intentionally does not diagnose swaps
between two integral values or between two floating-point values. Run clang-tidy
with the consumer's compilation database and existing compiler flags; a missing
or different compilation context can change coverage. No Alphus command
replaces `.clang-tidy`, the compiler database, or the native output.

## Alphus Python pilot

Selector: `positional-interfaces`. Finding ID:
`alphus/python/none/correctness/confusable-positional-parameters`.

```toml
[checks.positional_interfaces]
extensions = [".py"]
exclude = [
  "src/compatibility/**", # preserves inherited or published call contracts
  "src/symmetric_operations.py", # same-type order is intentional in this module
]
severity = "info"
report_same_type_primitives = true

[orchestration]
default_profile = "argument-review"
failure_threshold = "warning"

[[orchestration.steps]]
kind = "rule"
name = "Positional interface review"
rule = "positional-interfaces"
rollout = "provisional"

[[orchestration.profiles]]
name = "argument-review"
steps = ["Positional interface review"]
```

The checker reports runs of adjacent positional parameters whose annotations
are directly written as the same unshadowed builtin `bool`, `bytes`, `complex`,
`float`, `int`, or `str`. It reports the parameter names and explicitly says
that it has not identified a bad call. Change `severity` to `warning` or `error`
only after reviewing findings for the consumer. The normal finding JSON keeps
the existing `rule_id`, `path`, `message`, `line`, and `severity` fields.

Unknown annotations, type aliases, attributes, forward-reference strings,
decorated functions, nested functions, and methods on classes with explicit base
classes are outside this pilot. Positional-only and positional-or-keyword
parameters count; keyword-only parameters do not. Defaults do not change the
classification. The checker does not synthesize dataclass constructors, inspect
call sites, prove semantic meaning, or decide whether two parameters are
commutative. It never suggests an automatic signature change. Use documented
path exclusions for symmetric APIs, callback/FFI contracts, generated code,
and compatibility interfaces; keep the reason beside each exclusion.

The class deliberately avoids importing consumer code and does not resolve
names through aliases or type-checker state. A plain alias of `float` is not
treated as evidence, and any builtin name rebound in the visible module or
class namespace is ignored. A meaningful distinct domain type such as
`Latitude` and `Longitude` is not compared as a primitive pair.

The policy validator accepts only `.py` inputs. Selecting JavaScript,
TypeScript, C, or C++ for this Python AST rule is a configuration error; those
languages use their native bindings in the matrix above, or are reported as
unsupported in Alphus when no suitable native tool is configured.

## Remedies

Python APIs can make optional arguments keyword-only or use a record with
meaningful fields. JavaScript and TypeScript APIs can accept a named or
destructured options object. C and C++ APIs can use a record with named field
initialization or distinct strong types. A positional tuple, array, or record
constructor containing several same-typed values may move the same ordering
risk into the constructor, so review the call pattern before choosing a
container. Plain type aliases do not necessarily prevent swaps.

## Initial advisory sample

A scoped sweep on 2026-10-23 found 17 candidate signatures in this checkout's
`src/alphus` Python source, zero in the existing FastAPI consumer example, and
zero in the existing Pydantic-practices consumer example. The new controlled
example produces one intended finding and excludes its symmetric and
compatibility APIs by path. These example trees are small and do not establish
production precision. The result supports keeping this checker opt-in,
informational, and provisional; it does not support a blocking default.

## Native configuration examples

Merge these settings into the consumer's existing files; do not replace its
selected checks or versions.

For Ruff, add PLR0917 to the existing selection and choose its native positional
limit. PLR0913 remains the separate total-argument rule:

```toml
[tool.ruff.lint]
extend-select = ["PLR0917"]

[tool.ruff.lint.pylint]
max-positional-args = 5
```

For Pylint, enable the positional-count and call-order messages in the existing
message configuration. The native thresholds stay in Pylint's design section:

```ini
[MESSAGES CONTROL]
enable = too-many-positional-arguments,arguments-out-of-order

[DESIGN]
max-positional-arguments = 5
```

Alphus also has an explicit `pylint` command recipe for consumers that want to
run their already-installed tool through orchestration. Select it with
`tools = ["pylint"]`; it is intentionally absent from the Python language
bundle. The recipe does not install Pylint or enable rules by itself; the
consumer's Pylint configuration remains authoritative.

In an existing ESLint flat config, add a `max-params` rule such as
`["warn", { max: 5 }]`. It reports function declarations above the configured
count and does not analyze whether two same-type parameters or call arguments
were swapped.

In an existing `.clang-tidy`, merge the native checks into its current `Checks`
pattern. This minimal selection is for a project without an existing pattern;
append these entries to an existing value rather than replacing it:

```yaml
Checks: >-
  bugprone-easily-swappable-parameters,
  readability-suspicious-call-argument,
  bugprone-swapped-arguments
```

The exact enabled checks and `CheckOptions` must match the project's selected
clang-tidy version. Keep its compile database path, target flags, and warning
policy in the native invocation. `bugprone-easily-swappable-parameters` has
configurable minimum sequence length, ignored names/types, and body-use
suppression; review those native options rather than treating the Alphus Python
pilot's primitive list as a shared C++ type policy.

## Runnable consumer example

The [consumer example](../examples/consumer/confusable-positional/README.md)
contains a complete Alphus policy, a pair of directly typed coordinates, native
configuration snippets, and a separate optional Pylint profile. The Pylint
profile runs only when selected and only when Pylint is already available in the
consumer environment. Alphus does not install tools or change CI configuration.

## Native references

- [Ruff PLR0913: total argument count](https://docs.astral.sh/ruff/rules/too-many-arguments/)
- [Ruff PLR0917: positional argument count](https://docs.astral.sh/ruff/rules/too-many-positional-arguments/)
- [Pylint R0917: positional argument count](https://pylint.readthedocs.io/en/v3.3.9/user_guide/messages/refactor/too-many-positional-arguments.html)
- [Pylint W1114: arguments out of order](https://pylint.readthedocs.io/en/stable/user_guide/messages/warning/arguments-out-of-order.html)
- [clang-tidy easily swappable parameters](https://clang.llvm.org/extra/clang-tidy/checks/bugprone/easily-swappable-parameters.html)
- [clang-tidy suspicious call argument](https://clang.llvm.org/extra/clang-tidy/checks/readability/suspicious-call-argument.html)
- [clang-tidy swapped arguments](https://clang.llvm.org/extra/clang-tidy/checks/bugprone/swapped-arguments.html)
- [ESLint `max-params`](https://eslint.org/docs/latest/rules/max-params)

# Runtime type checks

The `runtime-types` gate reports runtime discrimination without a supported
type contract. It keeps the configured Python inventory, exclusions, error
severity and failure threshold. It does not import or execute inspected code.
Native type checkers retain responsibility for full typing correctness.

## Supported contracts

The gate accepts three forms:

- An explicit finite union with the checked class among its members. Qualified
  identities matter; two modules' classes with the same terminal name are not
  interchangeable. `object | T` and `Any | T` are not useful closed unions.
- A proven standard-library AST family checked against a compatible subtype.
  For example, `ast.expr` may narrow to `ast.Name`, but not `ast.Assign`.
- An explicitly annotated inspection value, restricted to the fixed predicates
  described below. The declaration applies to that value, not an entire function.

Imports and aliases are resolved lexically through the shared source scanner.
AST-looking variable names and fake or shadowed imports grant no permission.
Proven AST origins include annotations, standard AST constructors and `ast.parse`.
The model propagates selected AST fields, typed sequences/mappings, local helper
return annotations, assignments, comprehensions and traversal results. `ast.walk`
and `ast.iter_child_nodes` require an AST input. Arbitrary attributes, including
`ast.Constant.value`, do not acquire AST provenance.

Branches conservatively join possible values. Rebinding, capture targets, imports,
known container writes and uncertain exception paths invalidate stale facts.
Loops use bounded joins and discard written facts when those joins do not
stabilize. Deferred scopes cannot inherit unstable captured facts or class-local
bindings that Python would not resolve there.

## Deliberate runtime inspection

Use standard `typing.Annotated` metadata at an actual inspection boundary:

```python
from typing import Annotated

def inspect_member(
    value: Annotated[
        object,
        "alphus:class-member",
        "Value read from the inspected runtime class namespace",
    ],
) -> bool:
    return isinstance(value, (staticmethod, classmethod, property))
```

The underlying public type remains `object`. Neither annotation metadata nor a
read-only interface makes the inspected object immutable. The reason must be a
literal string with at least twelve non-padding characters. Unknown purposes,
malformed metadata and missing reasons grant no permission.

| Purpose | Permitted canonical checked classes |
| --- | --- |
| `alphus:signature-default` | `enum.Enum` |
| `alphus:class-member` | Builtin `staticmethod`, `classmethod`, `property` |

`list`, `dict`, `int`, arbitrary application classes and mixed tuples such as
`(property, list)` still produce errors, even on an annotated inspection value.
A signature-default declaration does not allow descriptor checks, or vice versa.
Unannotated `object` inputs retain the original enforcement.

This metadata records reviewed semantic intent. It does not prove that a value
actually came from `inspect.signature` or a class dictionary. The existing
adapters retain their callable checks, missing-getter rejection, signature-error
handling and callable/data mismatch validation.

## Limits and regression evidence

This is a bounded source convention, not a replacement type checker. It models
selected ASDL fields and local flow; unsupported producers remain unknown.
Imported helper return types are not loaded from arbitrary modules. General
alias mutation, effects of arbitrary calls, complete exception reachability,
interprocedural flow and dynamic imports are not proved. Reflection declarations
are checked syntactically and remain reviewable boundary assertions.

Regression cases cover valid AST families and aliases, nullable parent walks,
unrelated application-data probes, wrong families and fields, default-value
contamination, shadowing, loop-carried writes, lambda/class/deferred scopes,
exception and context-manager captures, short-circuit assignment, container
writes, invalid metadata, unauthorized predicates and public adapter behavior.
Real installed consumer verification remains separate from these synthetic cases.

## Local correction verification

The approved correction was checked with the same installed wheel on Python
3.11.16 and 3.12.14, running the CLI outside the source checkouts with
`PYTHONPATH` unset:

| Check | Result on both interpreters |
| --- | --- |
| Full suite, including 90 added regression cases | 464 passed |
| Ruff lint and format | Passed |
| Native strict Pyright | 0 errors, warnings, information |
| Established Alphus self-profile | 10/10; zero findings |
| SnakeMD consumer `2728a48` | 8/8 |
| mdutils consumer `2bd771e` | 5/5; optional source policy 6/6 |
| Portable positive / expected negative | 12/12 / 10/12; intended Markdown failures |
| Markdown-only positive / missing-link negative | 2/2 / 1/2; intended link failure |

Each real consumer stub stage built wheel and sdist, passed Twine, installed
the wheel, checked dependencies and API expectations, required clean positive
and exact expected-negative Mypy/Pyright results, and passed stubtest/runtime
smoke. Public adapter tests also confirm that `get_type_hints` still sees
`object` and that invalid callable/property inputs retain their rejection.

This correction remains local for review. Consumer source, requirements and
workflow pins are unchanged at the published migration revision. The local
verification overrides Alphus with the correction wheel; it does not claim that
the published pins already contain this correction. No new exclusions, severity
overrides, threshold changes or hosted runs were introduced.

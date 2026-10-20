"""Positive and negative contracts for AST dispatch and reflection values."""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from alphus.runtime_types import type_check_findings
from alphus_stub_quality.api_audit_support import (
    runtime_decorators,
    runtime_default,
    runtime_parameters,
)
from alphus_stub_quality.runtime_audit import visible_class_member


@pytest.mark.parametrize(
    "source, allowed",
    [
        (
            "from typing import Optional\ndef f(value: Optional[str]):\n"
            " return isinstance(value, str)",
            True,
        ),
        (
            "class C:\n def f(self):\n  self.value: int | str\n"
            "  return isinstance(self.value, int)",
            False,
        ),
        (
            "from typing_extensions import Any\ndef f(value: Any | int):\n"
            " return isinstance(value, int)",
            False,
        ),
        (
            "import ast\ndef f(value: ast.expr, name: str):\n"
            " return isinstance(value, getattr(ast, name))",
            False,
        ),
        (
            "class C:\n def f(self, raw: object):\n  self.value: int | str\n"
            "  self.value = raw\n  return isinstance(self.value, int)",
            False,
        ),
        (
            "class C:\n def f(self, raw: object):\n  self.value: int | str\n"
            "  self = raw\n  return isinstance(self.value, int)",
            False,
        ),
    ],
)
def test_explicit_contract_boundaries(source: str, allowed: bool) -> None:
    assert bool(type_check_findings(source)) is not allowed


@pytest.mark.parametrize(
    "source",
    [
        "import ast\ndef f(x: ast.expr):\n return isinstance(x, ast.Name)",
        (
            "import ast as syntax\nfrom ast import Name as N\ndef f(x: syntax.expr | None):\n"
            " return isinstance(x, N)"
        ),
        (
            "import ast\ndef f(tree: ast.Module):\n return [x.name for x in tree.body if isin"
            "stance(x, ast.ClassDef)]"
        ),
        (
            "import ast\ndef f(tree: ast.Module):\n return [x.id for x in ast.walk(tree) if i"
            "sinstance(x, ast.Name)]"
        ),
        "import ast\ndef f(xs: list[ast.expr]):\n for x in xs:\n  if isinstance(x, ast.Name): pass",
        (
            "import ast\nfrom collections.abc import Mapping\ndef f(xs: Mapping[str, ast.Clas"
            "sDef]):\n for k,v in xs.items():\n  if isinstance(v, ast.ClassDef): pass"
        ),
        (
            "import ast\ndef nodes() -> list[ast.expr]:\n return []\ndef f():\n for x in node"
            "s():\n  if isinstance(x, ast.Name): pass"
        ),
        (
            "import ast\ndef f():\n tree = ast.parse('x', mode='eval')\n return isinstance(tr"
            "ee.body, ast.Name)"
        ),
        (
            "import ast\ndef f():\n tree = ast.parse('x')\n for x in tree.body:\n  if isinsta"
            "nce(x, ast.Expr): pass"
        ),
        "import ast\ndef f(x: ast.expr):\n y = x\n return isinstance(y, ast.Name)",
        (
            "import ast\ndef f(x: ast.AST):\n if not isinstance(x, ast.Call):\n  return\n ret"
            "urn isinstance(x.func, ast.Name)"
        ),
        (
            "import ast\ndef f(x: ast.AST):\n if not isinstance(x, ast.Call) or not isinstanc"
            "e(x.func, ast.Name):\n  return\n return x.func.id"
        ),
        (
            "import ast\ndef f(x: ast.AST):\n return isinstance(x, ast.Attribute) and isinsta"
            "nce(x.value, ast.Name)"
        ),
        (
            "import ast\ndef f(x: ast.Assign | ast.AnnAssign):\n ts = x.targets if isinstance"
            "(x, ast.Assign) else [x.target]\n return [t.id for t in ts if isinstance(t, ast."
            "Name)]"
        ),
        (
            "from typing import TypeAlias, Union\nU: TypeAlias = Union[int,str]\ndef f(x: U):"
            "\n return isinstance(x,int)"
        ),
        "def f(x: list[int] | dict[str,int]):\n return isinstance(x,list)",
        (
            "from builtins import isinstance as check\nimport ast\ndef f(x: ast.expr):\n retu"
            "rn check(x,ast.Name)"
        ),
    ],
)
def test_typed_dispatch_is_supported(source: str) -> None:
    assert type_check_findings(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "import ast\ndef f(node: object):\n return isinstance(node, ast.Name)",
        "import ast\ndef f(x: ast.expr):\n return isinstance(x, ast.Assign)",
        "import ast\ndef f(x: ast.Constant):\n return isinstance(x.value, ast.Name)",
        "import ast\ndef f(x: ast.Name):\n return isinstance(x.id, ast.Name)",
        "import ast\ndef f(x: ast.expr):\n return isinstance(x.lineno, ast.Name)",
        (
            "import ast\ndef f(payload: object):\n for node in ast.walk(payload):\n  if isins"
            "tance(node, ast.Name): pass"
        ),
        (
            "import ast\ndef f(payload: object):\n node = ast.parse('x')\n node = payload\n r"
            "eturn isinstance(node, ast.Module)"
        ),
        "import ast\ndef f(ast, node: object):\n return isinstance(node, ast.Name)",
        "from ast import Name as N\nimport ast\ndef f(N, x: ast.expr):\n return isinstance(x,N)",
        (
            "import ast\ndef f(node: ast.expr, payload: object):\n for node in payload:\n  if"
            " isinstance(node,ast.Name): pass"
        ),
        (
            "import ast\ndef f(x: ast.expr, payload: object, flag: bool):\n if flag:\n  y = x"
            "\n else:\n  y = payload\n return isinstance(y,ast.Name)"
        ),
        "import ast\ndef f(x: ast.expr | object):\n return isinstance(x,ast.Name)",
        "def f(x: object | int):\n return isinstance(x,int)",
        "import builtins\ndef f(x:object):\n return builtins.isinstance(x,list)",
        "from builtins import isinstance as check\ndef f(x:object):\n return check(x,list)",
        "def f(x:object):\n return dict is type(x)",
        "import a,b\ndef f(x:a.Node | a.Other):\n return isinstance(x,b.Node)",
        "x: int | str\ndef f(x):\n return isinstance(x,int)",
        (
            "import ast, builtins\ndef f(x: ast.expr, isinstance):\n if isinstance(x,ast.Call"
            "):\n  return builtins.isinstance(x.func,ast.Name)"
        ),
        "import ast\nfrom other import ast\ndef f(x: ast.expr):\n return isinstance(x,ast.Name)",
        (
            "import ast\ndef f(x: ast.expr):\n x.value = object()\n return isinstance(x.value"
            ",ast.Name)"
        ),
    ],
)
def test_unproven_or_unrelated_probing_stays_reported(source: str) -> None:
    assert type_check_findings(source)


def reflection_source(
    kind: str,
    checked: str,
    reason: str = "Inspected runtime value from a deliberate adapter",
) -> str:
    return (
        "from typing import Annotated\nfrom enum import Enum\n"
        f"def f(value: Annotated[object, {kind!r}, {reason!r}]):\n"
        f" return isinstance(value, {checked})\n"
    )


@pytest.mark.parametrize(
    "kind, checked",
    [
        ("alphus:signature-default", "Enum"),
        ("alphus:class-member", "staticmethod"),
        ("alphus:class-member", "classmethod"),
        ("alphus:class-member", "property"),
        ("alphus:class-member", "(staticmethod, classmethod, property)"),
    ],
)
def test_explicit_inspection_contract_permits_only_its_predicates(
    kind: str, checked: str
) -> None:
    assert type_check_findings(reflection_source(kind, checked)) == []


@pytest.mark.parametrize(
    "kind, checked, reason",
    [
        ("alphus:signature-default", "list", "Inspected signature default"),
        ("alphus:class-member", "dict", "Inspected runtime member"),
        ("alphus:class-member", "int", "Inspected runtime member"),
        ("alphus:class-member", "(property, list)", "Inspected runtime member"),
        ("alphus:class-member", "Enum", "Inspected runtime member"),
        ("alphus:signature-default", "property", "Inspected signature default"),
        ("alphus:anything", "property", "Inspected runtime member"),
        ("alphus:class-member", "property", " "),
    ],
)
def test_inspection_metadata_is_not_a_general_waiver(
    kind: str, checked: str, reason: str
) -> None:
    assert type_check_findings(reflection_source(kind, checked, reason))


@pytest.mark.parametrize(
    "source",
    [
        (
            "from typing import Annotated as A\nfrom enum import Enum as E\ndef f(x:A[object,"
            "'alphus:signature-default','Default from inspected signature']):\n return isinst"
            "ance(x,E)"
        ),
        (
            "from typing import Annotated,TypeAlias\nT:TypeAlias=Annotated[object,'alphus:cla"
            "ss-member','Member from inspected runtime class']\ndef f(x:T):\n return isinstan"
            "ce(x,property)"
        ),
    ],
)
def test_real_import_and_type_aliases_preserve_inspection_contract(source: str) -> None:
    assert type_check_findings(source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "from other import Annotated",
        "from typing import Annotated\nAnnotated = object",
    ],
)
def test_fake_or_shadowed_annotated_cannot_grant_inspection(replacement: str) -> None:
    source = reflection_source("alphus:class-member", "property")
    assert type_check_findings(
        source.replace("from typing import Annotated", replacement)
    )


def test_inspection_contract_does_not_leak_to_siblings_attributes_or_reassignment() -> (
    None
):
    source = reflection_source("alphus:class-member", "property").replace(
        " return isinstance(value, property)",
        (
            " isinstance(value.other, property)\n sibling = object()\n isinstance(sibling, pr"
            "operty)\n value = sibling\n return isinstance(value, property)"
        ),
    )
    assert [line for line, _ in type_check_findings(source)] == [4, 6, 8]


def test_inspection_contract_keeps_native_object_api_and_rejections() -> None:
    for function in (
        runtime_default,
        runtime_parameters,
        runtime_decorators,
        visible_class_member,
    ):
        assert get_type_hints(function)["value"] is object
    with pytest.raises(SystemExit, match="not callable"):
        runtime_parameters(object())
    with pytest.raises(SystemExit, match="no runtime getter"):
        runtime_parameters(property())

    def example(value: int = 3) -> int:
        return value

    assert runtime_parameters(staticmethod(example)) == [
        ("value", "positional-or-keyword", "3")
    ]
    assert runtime_decorators(staticmethod(example)) == {"staticmethod"}
    assert inspect.signature(runtime_default).parameters["value"].name == "value"

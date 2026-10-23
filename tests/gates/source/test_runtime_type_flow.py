"""Binding and branch counterexamples must invalidate inspection provenance."""

from __future__ import annotations

import pytest

from alphus.gates.source.runtime_types import type_check_findings


@pytest.mark.parametrize(
    "source",
    [
        (
            "def f(xs: dict[str,ast.expr], payload: object):\n node=xs.get('missing',payload)"
            "\n return isinstance(node,ast.Name) # forbidden"
        ),
        (
            "def f(tree:ast.Module,payload:object):\n node=next(ast.walk(tree),payload)\n ret"
            "urn isinstance(node,ast.Name) # forbidden"
        ),
        (
            "def f(node:ast.expr,payload:object):\n for _ in range(2):\n  isinstance(node,ast"
            ".Name) # forbidden\n  node=payload"
        ),
        (
            "def f(a:ast.expr,b:ast.expr,payload:object):\n for _ in range(4):\n  isinstance("
            "a,ast.Name) # forbidden\n  a=b\n  b=payload"
        ),
        "def f(node:ast.expr):\n return lambda node:isinstance(node,ast.Name) # forbidden",
        "node=ast.Name()\ndef f():\n return isinstance(node,ast.Name) # forbidden\nnode=raw()",
        (
            "def f(node:ast.expr,payload:object):\n (node:=payload) and predicate()\n return "
            "isinstance(node,ast.Name) # forbidden"
        ),
        (
            "def f(node:ast.expr,payload:object,flag:bool):\n flag and (node:=payload)\n retu"
            "rn isinstance(node,ast.Name) # forbidden"
        ),
        "def f(node:ast.BoolOp):\n return isinstance(node.op,ast.Add) # forbidden",
        (
            "def f(xs:dict[str,ast.expr],payload:object):\n xs['x']=payload\n return isinstan"
            "ce(xs['x'],ast.Name) # forbidden"
        ),
        "def f(node:ast.expr):\n with context() as node:\n  isinstance(node,ast.Name) # forbidden",
        (
            "def f(node:ast.expr):\n try:\n  action()\n except Exception as node:\n  isinstan"
            "ce(node,ast.Name) # forbidden"
        ),
        (
            "def f(node:ast.expr,payload:object):\n try:\n  node=payload\n except Exception:"
            "\n  node=ast.Name()\n return isinstance(node,ast.Name) # forbidden"
        ),
        "def f(member:M):\n with context() as member:\n  isinstance(member,property) # forbidden",
        (
            "async def f(member:M):\n async with context() as member:\n  isinstance(member,pr"
            "operty) # forbidden"
        ),
        (
            "def f(member:M):\n try:\n  action()\n except Exception as member:\n  isinstance("
            "member,property) # forbidden"
        ),
        (
            "def f(member:M,other:object):\n match other:\n  case member:\n   isinstance(memb"
            "er,property) # forbidden"
        ),
        (
            "def f(member:M):\n import other as member\n return isinstance(member,property) #"
            " forbidden"
        ),
        (
            "def f(member:M):\n from other import value as member\n return isinstance(member,"
            "property) # forbidden"
        ),
        "def f(member:M):\n return lambda member:isinstance(member,property) # forbidden",
        (
            "def f(member:M):\n (member:=raw()) and predicate()\n return isinstance(member,pr"
            "operty) # forbidden"
        ),
        (
            "def f(member:M,flag:bool):\n flag and (member:=raw())\n return isinstance(member"
            ",property) # forbidden"
        ),
        (
            "def f(member:object,trusted:M):\n try:\n  action()\n  member=trusted\n except Ex"
            "ception:\n  pass\n return isinstance(member,property) # forbidden"
        ),
        (
            "member:object\nclass Audit:\n member:M\n def f(self):\n  return isinstance(membe"
            "r,property) # forbidden"
        ),
        "member:M\ndef f():\n return isinstance(member,property) # forbidden\nmember=raw()",
        (
            "def f(member:M):\n def inner():\n  return isinstance(member,property) # forbidde"
            "n\n member=raw()"
        ),
        (
            "def nodes()->list[ast.expr]:\n return []\ndef f():\n for x in nodes():\n  isinst"
            "ance(x,ast.Name) # forbidden\nnodes=other"
        ),
        (
            "def f(member:M,flag:bool):\n (member:=raw()) if flag else None\n return isinstan"
            "ce(member,property) # forbidden"
        ),
        (
            "def f(member:M):\n [(member:=raw()) for _ in items]\n return isinstance(member,p"
            "roperty) # forbidden"
        ),
        "member:M\nfrom foreign import *\nisinstance(member,property) # forbidden",
        (
            "def f(member:M):\n def inner(x=(member:=raw())): pass\n return isinstance(member"
            ",property) # forbidden"
        ),
        (
            "def f(member:M):\n handler=lambda x=(member:=raw()): None\n return isinstance(me"
            "mber,property) # forbidden"
        ),
    ],
)
def test_control_flow_cannot_retain_stale_permission(source: str) -> None:
    prelude = (
        "import ast\nfrom typing import Annotated,TypeAlias\n"
        "M:TypeAlias=Annotated[object,'alphus:class-member','Runtime class member inventory']\n"
    )
    source = prelude + source
    expected = {
        line
        for line, text in enumerate(source.splitlines(), 1)
        if "# forbidden" in text
    }
    actual = {line for line, _ in type_check_findings(source)}
    assert expected <= actual


def test_nullable_parent_walk_retains_ast_shape_across_loop_iterations() -> None:
    source = """
import ast
def audit(tree: ast.Module):
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(tree):
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
                break
            parent = parents.get(parent)
"""
    assert type_check_findings(source) == []

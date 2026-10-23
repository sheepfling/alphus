"""Protect the Python structure gate against false positives and bypasses."""

import ast

from alphus.config import PythonStylePolicy
from alphus.gates.source.python_style import StyleVisitor, is_boundary_file

POLICY = PythonStylePolicy(
    extensions=[".py"],
    exclude=[],
    opaque_boundary_paths=["src/adapters/**"],
    opaque_boundary_marker_prefix="# opaque-boundary: ",
    opaque_boundary_min_reason_chars=12,
    forbidden_main_imports=["main", "service.app"],
)


def findings(source: str, *, boundary_file: bool = False) -> set[str]:
    """Return the violation categories found in a tiny Python module."""
    visitor = StyleVisitor(POLICY, source=source, boundary_file=boundary_file)
    visitor.visit(ast.parse(source))
    return {kind for kind, lines in visitor.findings.items() if lines}


def test_concrete_collection_inputs_and_quoted_types_are_detected() -> None:
    assert findings('def f(x: list["Widget"]) -> None: pass') == {
        "concrete_inputs",
        "quoted_types",
    }
    assert findings(
        "from typing import Set as MutableSet\ndef f(x: MutableSet[str]): pass"
    ) == {
        "concrete_inputs",
    }


def test_typer_option_collection_is_a_framework_boundary() -> None:
    assert (
        findings(
            "import typer\n"
            "from typing import Annotated\n"
            "def cli(names: Annotated[list[str], typer.Option('--name')]): pass"
        )
        == set()
    )
    assert findings(
        "from typing import Annotated\n"
        "def internal(names: Annotated[list[str], 'ordinary metadata']): pass"
    ) == {"concrete_inputs"}


def test_covariant_abstract_set_and_literal_values_are_allowed() -> None:
    source = (
        "from collections.abc import Set\n"
        "from typing import AbstractSet, Annotated, Literal\n"
        "def f(x: Set[str], y: AbstractSet[str], z: frozenset[str], "
        "t: tuple[str, ...], v: Literal['a'], w: Annotated[int, 'label']): pass"
    )
    assert findings(source) == set()
    assert findings("def f(x: set[str]): pass") == {"concrete_inputs"}
    assert findings("from typing import Set\ndef f(x: Set[str]): pass") == {
        "concrete_inputs",
    }


def test_bare_tuple_annotations_are_reported_without_rejecting_explicit_elements() -> (
    None
):
    assert findings("def f(signature: tuple) -> tuple: pass") == {"bare_tuples"}
    assert findings("class Cache:\n signature: list[tuple]") == {"bare_tuples"}
    assert findings("from typing import Tuple as T\ndef f(x: T): pass") == {
        "bare_tuples",
    }
    assert findings("import typing as t\ndef f(x: t.Tuple): pass") == {
        "bare_tuples",
    }
    assert findings("def f(x: tuple[tuple, ...]): pass") == {"bare_tuples"}
    assert (
        findings(
            "from typing import Any, Annotated, Literal\n"
            "def f(x: tuple[object, ...], y: tuple[Any, ...], "
            "z: Annotated[tuple[int, str], 'pair'], q: Literal['tuple']) -> tuple[()]: pass"
        )
        == set()
    )


def test_bare_container_annotations_are_reported_at_all_annotation_sites() -> None:
    assert findings("def public_pack(info: dict) -> dict: return info") == {
        "bare_containers",
        "concrete_inputs",
        "opaque_mappings",
    }
    assert findings("class Cache:\n items: list[dict]") == {
        "bare_containers",
        "opaque_mappings",
    }
    assert findings("class Cache:\n items: dict[str, list]") == {
        "bare_containers",
    }
    assert findings("def f(x: set, y: frozenset) -> Sequence: pass") == {
        "bare_containers",
        "concrete_inputs",
    }
    assert findings(
        "from typing import Mapping as M, List as L\n"
        "from collections.abc import Sequence as S\n"
        "def f(x: M, y: L, z: S): pass"
    ) == {"bare_containers", "opaque_mappings", "concrete_inputs"}
    assert findings("from collections import deque as D\nclass Cache:\n items: D") == {
        "bare_containers",
    }
    assert findings("import typing as t\ndef f(x: t.Mapping): pass") == {
        "bare_containers",
        "opaque_mappings",
    }


def test_parameterized_containers_and_explicit_unknown_elements_pass() -> None:
    assert (
        findings(
            "from collections.abc import Mapping, Sequence\n"
            "def f(x: Sequence[object], y: frozenset[object]) -> list[str]: pass"
        )
        == set()
    )
    assert (
        findings(
            "# opaque-boundary: raw HTTP map before model validation\n"
            "def decode(payload: Mapping[str, object]) -> dict[str, object]: pass",
            boundary_file=True,
        )
        == set()
    )
    assert (
        findings("from typing import Literal\ndef f(x: Literal['dict']): pass") == set()
    )


def test_pathlib_is_preferred_over_os_path() -> None:
    assert findings("import os\ndef f(): return os.path.basename('a/b')") == {"os_path"}
    assert findings("from os import path") == {"os_path"}
    assert findings("import os.path") == {"os_path"}
    assert (
        findings("from pathlib import Path\ndef f(path: Path): return path.name")
        == set()
    )


def test_function_local_and_type_checking_imports_are_detected() -> None:
    assert findings("def f():\n import os") == {"local_imports"}
    assert findings("from typing import TYPE_CHECKING as TC\nif TC:\n import os") == {
        "type_checking_imports",
    }
    assert findings("import typing as t\nif t.TYPE_CHECKING:\n import os") == {
        "type_checking_imports",
    }


def test_configured_application_entrypoint_imports_are_reported() -> None:
    assert findings("from service.app import app") == {"main_module_imports"}
    assert findings("import service.app as main") == {"main_module_imports"}
    assert findings("import main") == {"main_module_imports"}
    assert findings("from .main import app") == set()


def test_opaque_mapping_signatures_require_an_approved_boundary() -> None:
    assert (
        findings("import ast\ndef f(node: ast.Dict) -> ast.Dict | None: pass") == set()
    )
    source = (
        "from typing import Any\ndef f(x: Mapping[str, Any]) -> dict[str, object]: pass"
    )
    assert findings(source) == {"opaque_mappings"}
    assert findings(
        "from collections.abc import Mapping as M\n"
        "from typing import Any as Unknown\n"
        "def f(x: M[str, Unknown]): pass"
    ) == {"opaque_mappings"}
    assert findings("def f(x: Mapping[str, int]) -> dict[str, float]: pass") == set()
    assert findings("class Bus:\n payload: list[dict[str, object]]") == {
        "opaque_mappings",
    }
    marked = (
        "# opaque-boundary: raw HTTP document before model validation\n"
        "def decode(payload: Mapping[str, object]): pass"
    )
    assert findings(marked) == {"opaque_mappings"}
    assert findings(marked, boundary_file=True) == set()


def test_mutable_module_constants_are_reported_without_flagging_local_values() -> None:
    assert findings("NAMES = {'a', 'b'}") == {"mutable_module_constants"}
    assert findings("NAMES: set[str] = set()") == {"mutable_module_constants"}
    assert findings("NAMES = frozenset({'a', 'b'})") == set()
    assert findings("def f():\n    NAMES = {'a'}") == set()
    assert findings("cache = {}") == set()


def test_opaque_boundary_paths_are_policy_data() -> None:
    assert is_boundary_file("src/adapters/http.py", POLICY)
    assert not is_boundary_file("src/services/registry.py", POLICY)


def test_new_dataclasses_require_slots() -> None:
    assert findings(
        "from dataclasses import dataclass\n@dataclass\nclass Item:\n x: int"
    ) == {
        "unslotted_dataclasses",
    }
    assert (
        findings(
            "from dataclasses import dataclass as dc\n@dc(slots=True)\nclass Item:\n x: int"
        )
        == set()
    )


def test_pydantic_field_metadata_uses_annotated_and_separate_defaults() -> None:
    assert findings(
        "from pydantic import Field\n"
        "class Contract:\n"
        " value: str = Field(alias='value')\n"
        " optional: int | None = Field(default=None, alias='optional')"
    ) == {"legacy_pydantic_fields"}
    assert (
        findings(
            "from typing import Annotated\n"
            "from pydantic import Field\n"
            "class Contract:\n"
            " value: Annotated[str, Field(alias='value')]\n"
            " optional: Annotated[int | None, Field(alias='optional')] = None"
        )
        == set()
    )


def test_frozen_pydantic_models_prefer_read_only_collection_interfaces() -> None:
    assert findings(
        "from typing import Annotated\n"
        "from pydantic import BaseModel, ConfigDict, Field\n"
        "class Contract(BaseModel):\n"
        " model_config = ConfigDict(frozen=True)\n"
        " records: Annotated[list[str], Field()]\n"
        " lookup: Annotated[dict[str, int], Field()]"
    ) == {"pydantic_collection_contracts"}
    assert (
        findings(
            "from collections.abc import Mapping, Sequence\n"
            "from pydantic import BaseModel, ConfigDict\n"
            "class Contract(BaseModel):\n"
            " model_config = ConfigDict(frozen=True)\n"
            " records: Sequence[str]\n"
            " lookup: Mapping[str, int]"
        )
        == set()
    )
    assert (
        findings(
            "from pydantic import BaseModel\n"
            "class MutableContract(BaseModel):\n"
            " records: list[str]\n"
            " lookup: dict[str, int]"
        )
        == set()
    )
    assert findings(
        "from pydantic import BaseModel, ConfigDict\n"
        "class FrozenBase(BaseModel):\n"
        " model_config = ConfigDict(frozen=True)\n"
        "class ChildContract(FrozenBase):\n"
        " records: list[str]"
    ) == {"pydantic_collection_contracts"}


def test_mutable_pydantic_models_prefer_concrete_collections() -> None:
    assert findings(
        "from collections.abc import Mapping, Sequence\n"
        "from pydantic import BaseModel\n"
        "class MutableContract(BaseModel):\n"
        " records: Sequence[str]\n"
        " lookup: Mapping[str, int]"
    ) == {"pydantic_collection_contracts"}
    assert findings(
        "from collections.abc import Mapping as ReadOnlyMap\n"
        "from pydantic import BaseModel\n"
        "class MutableContract(BaseModel):\n"
        " records: list[str]\n"
        " lookup: ReadOnlyMap[str, int]"
    ) == {"pydantic_collection_contracts"}


def test_mutability_setting_can_be_overridden_on_a_frozen_model_subclass() -> None:
    assert findings(
        "from collections.abc import Sequence\n"
        "from pydantic import BaseModel, ConfigDict\n"
        "class FrozenBase(BaseModel):\n"
        " model_config = ConfigDict(frozen=True)\n"
        "class MutableChild(FrozenBase):\n"
        " model_config = ConfigDict(frozen=False)\n"
        " records: Sequence[str]"
    ) == {"pydantic_collection_contracts"}


def test_imported_concrete_list_and_dict_aliases_do_not_hide_input_contracts() -> None:
    assert findings(
        "from typing import List as L, Dict as D\n"
        "def f(x: L[str], y: D[str, int]): pass"
    ) == {"concrete_inputs"}


def test_literal_rule_ids_require_semantic_construction_when_selected() -> None:
    source = 'RULE = "alphus/python/none/style/line-too-long"'
    visitor = StyleVisitor(POLICY, semantic_rule_ids=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["literal_rule_ids"] == [1]

    visitor = StyleVisitor(POLICY)
    visitor.visit(ast.parse(source))
    assert visitor.findings["literal_rule_ids"] == []

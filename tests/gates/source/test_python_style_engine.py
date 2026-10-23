"""Protect the Python structure gate against false positives and bypasses."""

import ast
from pathlib import Path

from alphus.config import PythonStylePolicy
from alphus.gates.source.python_style import (
    StyleVisitor,
    findings_for,
    is_boundary_file,
)

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

    formatted = 'def report(issue): return f"alphus/python/none/style/{issue}"'
    visitor = StyleVisitor(POLICY, semantic_rule_ids=True)
    visitor.visit(ast.parse(formatted))
    assert visitor.findings["literal_rule_ids"] == [1]

    serialized = 'def report(finding): return f"{finding.rule_id}: {finding.message}"'
    visitor = StyleVisitor(POLICY, semantic_rule_ids=True)
    visitor.visit(ast.parse(serialized))
    assert visitor.findings["literal_rule_ids"] == []


def test_scoped_reporting_requires_logger_and_semantic_exit_codes() -> None:
    source = (
        "def run():\n    print('status')\n    exit_code = 127\n    return exit_code\n"
    )
    visitor = StyleVisitor(POLICY, structured_reporting=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["raw_reporting_prints"] == [2]
    assert visitor.findings["magic_exit_codes"] == [3]
    visitor = StyleVisitor(POLICY)
    visitor.visit(ast.parse(source))
    assert visitor.findings["raw_reporting_prints"] == []
    assert visitor.findings["magic_exit_codes"] == []


def test_scoped_repeated_literals_ignore_type_declarations() -> None:
    source = (
        "from typing import Literal\n"
        "Status = Literal['ready', 'ready', 'ready']\n"
        "A = 'repeated-value'\n"
        "B = 'repeated-value'\n"
        "C = 'repeated-value'\n"
    )
    visitor = StyleVisitor(POLICY, repeated_literals=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["repeated_literals"] == [3, 4, 5]


def test_literal_rule_dimensions_require_canonical_enums() -> None:
    raw = "rule_tag('python', 'none', 'style', 'line-too-long')"
    visitor = StyleVisitor(POLICY, semantic_rule_ids=True)
    visitor.visit(ast.parse(raw))
    assert visitor.findings["literal_rule_dimensions"] == [1]

    symbolic = "rule_tag(Scope.PYTHON, Framework.NONE, Category.STYLE, 'line-too-long')"
    visitor = StyleVisitor(POLICY, semantic_rule_ids=True)
    visitor.visit(ast.parse(symbolic))
    assert visitor.findings["literal_rule_dimensions"] == []


def test_scoped_semantic_results_require_named_heterogeneous_records() -> None:
    source = (
        "def load() -> tuple[dict[str, int], list[str]]: pass\n"
        "def count() -> tuple[int, int]: pass\n"
        "def many() -> tuple[str, ...]: pass\n"
    )
    visitor = StyleVisitor(POLICY, semantic_results=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["heterogeneous_tuple_returns"] == [1]


def test_scoped_pattern_declarations_name_globs_and_regexes() -> None:
    source = (
        "import re\n"
        "DEFAULT_INCLUDES = ('*.exe',)\n"
        "SECTION_RE = re.compile('x')\n"
        "DEFAULT_INCLUDE_GLOBS = ('*.dll',)\n"
        "SECTION_REGEX = re.compile('y')\n"
    )
    visitor = StyleVisitor(POLICY, pattern_kinds=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["undifferentiated_patterns"] == [2, 3]


def test_scoped_classmethod_factory_uses_self_return() -> None:
    source = (
        "class Report:\n"
        "    @classmethod\n"
        "    def create(cls) -> Report: return cls()\n"
        "    @staticmethod\n"
        "    def empty() -> Report: return Report()\n"
    )
    visitor = StyleVisitor(POLICY, self_returns=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["concrete_classmethod_returns"] == [3]


def test_scoped_semantic_results_check_nested_heterogeneous_tuples() -> None:
    visitor = StyleVisitor(POLICY, semantic_results=True)
    visitor.visit(ast.parse("def comments() -> list[tuple[int, str]]: return []"))
    assert visitor.findings["heterogeneous_tuple_returns"] == [1]


def test_scoped_semantic_results_preserve_named_and_wire_contracts() -> None:
    source = (
        "from typing import NamedTuple, TypedDict\n"
        "class Pair(NamedTuple):\n    count: int\n    name: str\n"
        "class WireRow(TypedDict):\n    count: int\n    name: str\n"
        "def pair() -> Pair: ...\n"
        "def wire() -> WireRow: ...\n"
        "def coordinates() -> tuple[int, int]: ...\n"
        "def tags() -> tuple[str, ...]: ...\n"
        "def json_row() -> dict[str, int | str]: ...\n"
    )
    visitor = StyleVisitor(POLICY, semantic_results=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["heterogeneous_tuple_returns"] == []
    assert visitor.findings["opaque_mappings"] == []


def test_semantic_result_paths_are_opt_in_and_respect_exclusions(
    tmp_path: Path,
) -> None:
    relative = Path("src/results.py")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(
        "def load() -> tuple[dict[str, int], list[str]]: return {}, []\n",
        encoding="utf-8",
    )

    disabled = findings_for(tmp_path, [relative], POLICY)
    assert (
        disabled.get(relative.as_posix(), {}).get("heterogeneous_tuple_returns") is None
    )

    enabled = POLICY.model_copy(update={"semantic_result_paths": ["src/**"]})
    selected = findings_for(tmp_path, [relative], enabled)
    assert selected[relative.as_posix()]["heterogeneous_tuple_returns"] == [1]

    excluded = enabled.model_copy(update={"exclude": ["src/**"]})
    assert findings_for(tmp_path, [relative], excluded) == {}


def test_scoped_text_reader_check_detects_direct_path_reads() -> None:
    visitor = StyleVisitor(POLICY, shared_text_readers=True)
    visitor.visit(ast.parse("content = path.read_text(encoding='utf-8')"))
    assert visitor.findings["direct_text_reads"] == [1]


def test_scoped_literal_alias_must_not_repeat_its_members() -> None:
    source = (
        "from typing import Literal, TypeAlias\n"
        "Status: TypeAlias = Literal['ready', 'failed', 'pending']\n"
        "if value in {'ready', 'failed', 'pending'}: pass\n"
    )
    visitor = StyleVisitor(POLICY, repeated_literals=True)
    visitor.visit(ast.parse(source))
    assert visitor.findings["duplicate_literal_catalogs"] == [3]


def test_scoped_public_constants_need_an_external_import() -> None:
    source = "EXPORTED = 1\nINTERNAL = 2\n_PRIVATE = 3\n"
    visitor = StyleVisitor(
        POLICY,
        public_constants=True,
        module_name="alphus.gates.cpp.sample",
        imported_symbols=frozenset({"alphus.gates.cpp.sample.EXPORTED"}),
    )
    visitor.visit(ast.parse(source))
    assert visitor.findings["unused_public_constants"] == [2]


def test_public_constant_import_index_only_flags_unconsumed_symbols(
    tmp_path: Path,
) -> None:
    source = Path("src/alphus/gates/cpp/sample.py")
    consumer = Path("src/alphus/gates/cpp/consumer.py")
    (tmp_path / source).parent.mkdir(parents=True)
    (tmp_path / source).write_text("EXPORTED = 1\nINTERNAL = 2\n", encoding="utf-8")
    (tmp_path / consumer).write_text(
        "from alphus.gates.cpp.sample import EXPORTED\n", encoding="utf-8"
    )
    policy = POLICY.model_copy(
        update={"public_constant_paths": ("src/alphus/gates/cpp/**",)}
    )
    result = findings_for(tmp_path, [source, consumer], policy)
    assert result[source.as_posix()]["unused_public_constants"] == [2]

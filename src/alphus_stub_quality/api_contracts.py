"""Reusable unittest gates for a configured source/stub API and its examples.

These are structural checks. They do not infer complete type or runtime semantics.
Consumers supply the expected surface and keep their behavioral runtime assertions.
"""

from __future__ import annotations

import ast
import unittest
from collections import Counter
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from importlib import metadata
from pathlib import Path
from types import ModuleType

from alphus_stub_quality.api_audit_support import (
    class_attributes as _class_attributes,
)
from alphus_stub_quality.api_audit_support import (
    class_bases as _class_bases,
)
from alphus_stub_quality.api_audit_support import (
    class_nodes as _class_nodes,
)
from alphus_stub_quality.api_audit_support import (
    decorator_kinds as _decorator_kinds,
)
from alphus_stub_quality.api_audit_support import (
    defined_names as _defined_names,
)
from alphus_stub_quality.api_audit_support import (
    enum_members as _enum_members,
)
from alphus_stub_quality.api_audit_support import (
    is_public as _is_public,
)
from alphus_stub_quality.api_audit_support import (
    method_nodes as _method_nodes,
)
from alphus_stub_quality.api_audit_support import (
    runtime_class_index,
    runtime_package_root,
)
from alphus_stub_quality.api_audit_support import (
    source_signature_shape as _signature_shape,
)
from alphus_stub_quality.api_audit_support import (
    stub_function_parameters as _stub_function_parameters,
)
from alphus_stub_quality.api_audit_support import (
    stub_import_bindings as _stub_import_bindings,
)
from alphus_stub_quality.api_audit_support import (
    uses_typing_any as _uses_typing_any,
)


class ApiCoverageTests(unittest.TestCase):
    """Inherit and supply the package contract; no package names are built in."""

    __test__ = False
    package_name: str
    required_version: str
    module_paths: Mapping[str, str]
    package_exports: Mapping[str, AbstractSet[str]]
    stub_imports: Mapping[str, Mapping[str, tuple[str, str]]]
    export_targets: Mapping[str, Mapping[str, tuple[str, str | None]]]
    stub_root: Path
    fixture_path: Path
    runtime_root: Path
    runtime_packages: Mapping[str, ModuleType]
    forbidden_hooks: AbstractSet[str] = frozenset(
        {"__getattr__", "__getattribute__", "__dir__"}
    )
    forbidden_calls: AbstractSet[str] = frozenset({"setattr", "exec", "eval"})

    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_root = runtime_package_root(cls.package_name)
        found = metadata.version(cls.package_name)
        if found != cls.required_version:
            raise AssertionError(
                f"API inventory is pinned to {cls.required_version}, found {found}"
            )

    def test_runtime_modules_have_one_to_one_stub_files(self) -> None:
        runtime_modules = {
            path.relative_to(self.runtime_root).with_suffix("").as_posix()
            for path in self.runtime_root.rglob("*.py")
        }
        stub_modules = {
            path.relative_to(self.stub_root).with_suffix("").as_posix()
            for path in self.stub_root.rglob("*.pyi")
        }
        self.assertEqual(runtime_modules, set(self.module_paths.values()))
        self.assertEqual(stub_modules, set(self.module_paths.values()))

    def test_public_definitions_and_class_shapes_match(self) -> None:
        for relative in sorted(self.module_paths.values()):
            runtime_path = self.runtime_root / f"{relative}.py"
            stub_path = self.stub_root / f"{relative}.pyi"
            runtime_tree = ast.parse(runtime_path.read_text(encoding="utf-8"))
            stub_tree = ast.parse(stub_path.read_text(encoding="utf-8"))
            self.assertEqual(
                _defined_names(runtime_tree), _defined_names(stub_tree), relative
            )
            runtime_classes = _class_nodes(runtime_tree)
            stub_classes = _class_nodes(stub_tree)
            self.assertEqual(runtime_classes.keys(), stub_classes.keys(), relative)
            for class_name, runtime_class in runtime_classes.items():
                stub_class = stub_classes[class_name]
                self.assertEqual(
                    _class_bases(runtime_class),
                    _class_bases(stub_class),
                    f"{relative}:{class_name} bases",
                )
                runtime_methods = _method_nodes(runtime_class)
                stub_methods = _method_nodes(stub_class)
                self.assertEqual(
                    runtime_methods.keys(),
                    stub_methods.keys(),
                    f"{relative}:{class_name} methods",
                )
                for method_name, runtime_method in runtime_methods.items():
                    stub_method = stub_methods[method_name]
                    self.assertEqual(
                        _signature_shape(runtime_method),
                        _signature_shape(stub_method),
                        f"{relative}:{class_name}.{method_name} parameters/defaults",
                    )
                    self.assertEqual(
                        _decorator_kinds(runtime_method),
                        _decorator_kinds(stub_method),
                        f"{relative}:{class_name}.{method_name} decorators",
                    )
                runtime_attributes = _class_attributes(runtime_class)
                stub_attributes = _class_attributes(stub_class)
                self.assertEqual(
                    runtime_attributes,
                    stub_attributes,
                    f"{relative}:{class_name} public attributes",
                )
                runtime_enum = _enum_members(runtime_class)
                stub_enum = _enum_members(stub_class)
                self.assertEqual(
                    runtime_enum, stub_enum, f"{relative}:{class_name} enum members"
                )

    def test_stub_public_callables_have_complete_annotations(self) -> None:
        for relative in sorted(self.module_paths.values()):
            stub_path = self.stub_root / f"{relative}.pyi"
            tree = ast.parse(stub_path.read_text(encoding="utf-8"))
            functions = [
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _is_public(node.name)
            ]
            for class_node in _class_nodes(tree).values():
                functions.extend(_method_nodes(class_node).values())
            for function in functions:
                for parameter in _stub_function_parameters(function):
                    self.assertIsNotNone(
                        parameter.annotation,
                        f"{relative}:{function.name}.{parameter.arg} needs an annotation",
                    )
                self.assertIsNotNone(
                    function.returns,
                    f"{relative}:{function.name} needs a return annotation",
                )

    def test_initializer_exports_match_runtime_aliases_and_typing_fixture(self) -> None:
        fixture_path = self.fixture_path
        fixture_tree = ast.parse(fixture_path.read_text(encoding="utf-8"))
        fixture_imports: dict[str, set[str]] = {
            name: set() for name in self.package_exports
        }
        for node in fixture_tree.body:
            if isinstance(node, ast.ImportFrom) and node.module in fixture_imports:
                fixture_imports[node.module].update(alias.name for alias in node.names)

        for package, expected_names in self.package_exports.items():
            runtime_package = self.runtime_packages[package]
            runtime_names = {
                name for name in vars(runtime_package) if not name.startswith("_")
            }
            self.assertEqual(
                runtime_names, expected_names, f"{package} runtime exports"
            )
            self.assertEqual(
                fixture_imports[package], expected_names, f"{package} fixture imports"
            )

            relative = package.removeprefix(self.package_name).lstrip(".")
            stub_init = (
                self.stub_root / relative / "__init__.pyi"
                if relative
                else self.stub_root / "__init__.pyi"
            )
            stub_tree = ast.parse(stub_init.read_text(encoding="utf-8"))
            stub_names = {
                alias.asname or alias.name
                for node in stub_tree.body
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            self.assertEqual(stub_names, expected_names, f"{package} stub exports")
            self.assertEqual(
                _stub_import_bindings(package, stub_tree),
                self.stub_imports[package],
                f"{package} stub import targets",
            )

            for export, (target_module, target_name) in self.export_targets[
                package
            ].items():
                target = self.runtime_packages[target_module]
                expected = (
                    target if target_name is None else getattr(target, target_name)
                )
                self.assertIs(
                    getattr(runtime_package, export),
                    expected,
                    f"{package}.{export} runtime alias",
                )

    def test_consumer_fixture_probes_every_public_callable(self) -> None:
        fixture_path = self.fixture_path
        fixture_tree = ast.parse(fixture_path.read_text(encoding="utf-8"))
        method_probes: Counter[str] = Counter(
            node.func.attr
            for node in ast.walk(fixture_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        )
        constructor_probes: set[str] = set()
        expected_methods: Counter[str] = Counter()
        expected_constructors: set[str] = set()
        expected_str_methods = 0
        for relative in self.module_paths.values():
            tree = ast.parse(
                (self.runtime_root / f"{relative}.py").read_text(encoding="utf-8")
            )
            for class_name, class_node in _class_nodes(tree).items():
                for method_name in _method_nodes(class_node):
                    if method_name == "__init__":
                        expected_constructors.add(class_name)
                    elif method_name == "__str__":
                        expected_str_methods += 1
                    else:
                        expected_methods[method_name] += 1

        imported_names: dict[str, str] = {}
        for node in fixture_tree.body:
            if isinstance(node, ast.ImportFrom):
                imported_names.update(
                    {alias.asname or alias.name: alias.name for alias in node.names}
                )
        constructor_probes = {
            imported_names.get(node.func.id, node.func.id)
            for node in ast.walk(fixture_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and imported_names.get(node.func.id, node.func.id) in expected_constructors
        }

        self.assertEqual(
            set(method_probes), set(expected_methods), "typed method call inventory"
        )
        for method_name, required_probes in expected_methods.items():
            self.assertGreaterEqual(
                method_probes[method_name],
                required_probes,
                f"typed method probe count for {method_name}",
            )
        self.assertEqual(
            constructor_probes, expected_constructors, "constructor call inventory"
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "str"
                for node in ast.walk(fixture_tree)
            ),
            expected_str_methods,
            "protocol __str__ call inventory",
        )

    def test_consumer_fixture_probes_public_methods_on_their_declaring_classes(
        self,
    ) -> None:
        fixture_path = self.fixture_path
        fixture_tree = ast.parse(fixture_path.read_text(encoding="utf-8"))
        runtime_classes = runtime_class_index(self.runtime_root, self.module_paths)
        class_aliases: dict[str, tuple[str, str]] = {}
        module_aliases: dict[str, str] = {}

        for node in fixture_tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            for imported in node.names:
                local_name = imported.asname or imported.name
                if (
                    node.module is not None
                    and node.module in self.export_targets
                    and imported.name in self.export_targets[node.module]
                ):
                    module, class_name = self.export_targets[node.module][imported.name]
                    if class_name is None:
                        module_aliases[local_name] = module
                    else:
                        class_aliases[local_name] = (module, class_name)
                elif (
                    node.module is not None
                    and node.module in runtime_classes
                    and imported.name in runtime_classes[node.module]
                ):
                    class_aliases[local_name] = (node.module, imported.name)

        def class_for_expression(expression: ast.expr) -> tuple[str, str] | None:
            if isinstance(expression, ast.Name):
                return class_aliases.get(expression.id)
            if isinstance(expression, ast.Attribute) and isinstance(
                expression.value, ast.Name
            ):
                module = module_aliases.get(expression.value.id)
                if module is not None and expression.attr in runtime_classes.get(
                    module, set()
                ):
                    return (module, expression.attr)
            if isinstance(expression, ast.Call):
                return class_for_expression(expression.func)
            return None

        instances: dict[str, tuple[str, str]] = {}
        for node in ast.walk(fixture_tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call):
                targets = [node.target]
            else:
                continue
            target_class = class_for_expression(node.value.func)
            if target_class is not None:
                for target in targets:
                    if isinstance(target, ast.Name):
                        instances[target.id] = target_class

        def receiver_class(expression: ast.expr) -> tuple[str, str] | None:
            if isinstance(expression, ast.Name) and expression.id in instances:
                return instances[expression.id]
            return class_for_expression(expression)

        expected: Counter[tuple[str, str, str]] = Counter()
        for relative in self.module_paths.values():
            module = (
                self.package_name
                if relative == "__init__"
                else self.package_name
                + "."
                + relative.replace("/", ".").removesuffix(".__init__")
            )
            tree = ast.parse(
                (self.runtime_root / f"{relative}.py").read_text(encoding="utf-8")
            )
            for class_name, class_node in _class_nodes(tree).items():
                for method_name in _method_nodes(class_node):
                    if method_name not in {"__init__", "__str__"}:
                        expected[(module, class_name, method_name)] += 1

        observed: Counter[tuple[str, str, str]] = Counter()
        for node in ast.walk(fixture_tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            owner = receiver_class(node.func.value)
            if owner is not None:
                observed[(*owner, node.func.attr)] += 1
        self.assertEqual(
            set(observed), set(expected), "typed method calls by declaring class"
        )
        for method, required_probes in expected.items():
            self.assertGreaterEqual(
                observed[method],
                required_probes,
                f"typed method probe count for {method}",
            )

        parents = {
            child: parent
            for parent in ast.walk(fixture_tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(fixture_tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            parent = parents.get(node)
            while parent is not None:
                if (
                    isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Name)
                    and parent.func.id == "assert_type"
                ):
                    break
                parent = parents.get(parent)
            self.assertIsNotNone(
                parent, f"{node.func.attr} call must assert its result type"
            )

    def test_runtime_has_no_unmodeled_dynamic_api_hooks_or_any_annotations(
        self,
    ) -> None:
        for root in (self.runtime_root, self.stub_root):
            for path in root.rglob("*.py" if root == self.runtime_root else "*.pyi"):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                self.assertFalse(
                    _uses_typing_any(tree), f"{path}: Any weakens this candidate"
                )
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.assertNotIn(
                            node.name,
                            self.forbidden_hooks,
                            f"{path}: dynamic API hook {node.name}",
                        )
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in self.forbidden_calls
                    ):
                        self.fail(f"{path}: dynamic API call {node.func.id}")

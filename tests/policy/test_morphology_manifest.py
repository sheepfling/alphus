"""Exercise deterministic, import-free morphology declaration discovery."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from scripts.generate_morphology_manifest import (
    _text_argument_lines,
    _tuple_lines,
    feature_registrations,
    main,
    render_builtin_registry_stub,
    render_feature_manifest,
    render_feature_policies,
    render_manifest,
    render_quality_rule_names,
)
from scripts.generate_runner_manifest import render_manifest as render_runner_manifest

_DECLARATION: tuple[tuple[str, object], ...] = (
    ("selector", "demo-check"),
    ("finding_tag_complaints", ("demo-check",)),
    ("concern", "demo-concern"),
    ("claim_kind", "condition"),
    ("claim", "A demo claim backed by a literal source finding."),
    ("mechanisms", ("exact-rule",)),
    ("inspected_scope", ("repository-files",)),
    ("languages_formats", ("repository",)),
    ("evidence_kinds", ("path-line",)),
    ("evaluation_maturity", "synthetic-only"),
)


def _feature_source(
    declaration: tuple[tuple[str, object], ...],
    *,
    feature_class: str = "BuiltinFeature",
) -> str:
    """Render synthetic feature input using typed semantic contracts."""
    feature_fields = {
        "policy_field",
        "policy_model",
        "output_shape",
        "summary",
        "applies_to",
        "domains",
        "requires_files",
        "policy_inputs",
        "display_name",
        "input_mode",
    }
    policy_model = dict(declaration).get("policy_model")
    if not isinstance(policy_model, str):
        raise TypeError("test feature declarations need a policy model path")
    policy_module, policy_class = policy_model.rsplit(".", 1)
    lines = ["ALPHUS_CHECK = FeatureDefinition(\n"]
    for key, value in declaration:
        if key == "selector" or key in feature_fields:
            rendered = policy_class if key == "policy_model" else repr(value)
            lines.append(f"    {key}={rendered},\n")
    lines.append(")\n")
    values = dict(declaration)
    complaints = values.get("finding_tag_complaints", ())
    morphology = [
        "ALPHUS_MORPHOLOGY = RuleMorphology(\n",
        f"    selector={values['selector']!r},\n",
        "    finding_ids=(\n",
    ]
    for complaint in complaints:
        morphology.extend(
            [
                "        RuleTag(Scope.REPOSITORY, Framework.NONE, ",
                f"Category.TESTING, {complaint!r}),\n",
            ]
        )
    morphology.extend(
        [
            "    ),\n",
            f"    concern={values['concern']!r},\n",
            "    claim_kind=ClaimKind.CONDITION,\n",
            f"    claim={values['claim']!r},\n",
            "    mechanisms=(DetectionMechanism.EXACT_RULE,),\n",
            f"    inspected_scope={values['inspected_scope']!r},\n",
            f"    languages_formats={values['languages_formats']!r},\n",
            f"    evidence_kinds={values['evidence_kinds']!r},\n",
            "    evaluation_maturity=EvaluationMaturity.SYNTHETIC_ONLY,\n",
            ")\n",
        ]
    )
    lines.extend(morphology)
    if feature_class == "BuiltinFeature":
        runner_parameters = "root, files, config"
        resolver_lines: list[str] = []
    elif feature_class == "CompositeFindingBuiltinFeature":
        runner_parameters = "root, files, config, policy"
        resolver_lines = [
            "def _resolve_demo_policy(config):\n",
            "    return None\n",
        ]
    else:
        runner_parameters = "root, files, policy"
        resolver_lines = [
            "def _resolve_demo_policy(config):\n",
            "    return None\n",
        ]
    lines.extend(
        [
            f"def _registered_demo_runner({runner_parameters}):\n",
            "    return []\n",
            *resolver_lines,
            f"ALPHUS_FEATURE = {feature_class}(\n",
            "    definition=ALPHUS_CHECK,\n",
            "    morphology=ALPHUS_MORPHOLOGY,\n",
            "    runner=_registered_demo_runner,\n",
        ]
    )
    if feature_class != "BuiltinFeature":
        lines.append("    policy_resolver=_resolve_demo_policy,\n")
    lines.append(")\n")
    return f"from {policy_module} import {policy_class}\n" + "".join(lines)


def test_static_discovery_rejects_typed_feature_output_mismatch(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    declaration = tuple(
        (key, "demo-check" if key == "selector" else value)
        for key, value in _DECLARATION
    ) + (
        ("finding_tag_complaints", ("demo-check",)),
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "messages"),
        ("summary", "Reports demo findings."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
    )
    (gates / "demo_check.py").write_text(
        _feature_source(declaration, feature_class="FindingBuiltinFeature"),
        encoding="utf-8",
    )
    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    pass\n", encoding="utf-8"
    )
    (policy / "sources.py").write_text(
        "class DemoPolicy:\n    pass\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="does not match output shape 'messages'"):
        feature_registrations(tmp_path)


def test_generated_text_arguments_wrap_without_changing_their_value() -> None:
    value = (
        "Checks configured repository paths, manifests, tracked files, and "
        "layout rules while preserving the current repository contract."
    )
    lines = _text_argument_lines("summary", value)

    assert len(lines) > 1
    assert all(len(line) <= 88 for line in lines)
    module = ast.parse("FeatureDefinition(\n" + "\n".join(lines) + "\n)")
    call = module.body[0].value
    assert isinstance(call, ast.Call)
    assert ast.literal_eval(call.keywords[0].value) == value


def test_generated_text_arguments_split_long_tokens_without_inserting_spaces() -> None:
    value = "x" * 90
    lines = _text_argument_lines("summary", value)

    assert len(lines) > 1
    assert all(len(line) <= 88 for line in lines)
    module = ast.parse("FeatureDefinition(\n" + "\n".join(lines) + "\n)")
    call = module.body[0].value
    assert isinstance(call, ast.Call)
    assert ast.literal_eval(call.keywords[0].value) == value


def test_generated_feature_definition_imports_are_sorted(
    pytestconfig: pytest.Config,
) -> None:
    imports = tuple(
        line
        for line in render_feature_manifest(Path(pytestconfig.rootpath)).splitlines()
        if line.startswith("from alphus.policy.")
    )

    assert imports == tuple(sorted(imports))


def test_generated_feature_tuples_wrap_without_changing_their_values() -> None:
    values = (
        "scientific-computing",
        "simulation",
        "earth-science",
        "trajectory-analysis",
        "physical-units",
    )
    lines = _tuple_lines("domains", values)

    assert len(lines) > 1
    assert all(len(line) <= 88 for line in lines)
    module = ast.parse("FeatureDefinition(\n" + "\n".join(lines) + "\n)")
    call = module.body[0].value
    assert isinstance(call, ast.Call)
    assert ast.literal_eval(call.keywords[0].value) == values


def _with_field(
    declaration: tuple[tuple[str, object], ...], key: str, value: object
) -> tuple[tuple[str, object], ...]:
    return tuple((name, value if name == key else item) for name, item in declaration)


def _with_contract(
    declaration: tuple[tuple[str, object], ...], selector: str, contract: str
) -> tuple[tuple[str, object], ...]:
    result: list[tuple[str, object]] = []
    for name, item in declaration:
        if name == "selector":
            result.append((name, selector))
        elif name == "finding_tag_complaints":
            result.append(("finding_contracts", (contract,)))
        else:
            result.append((name, item))
    return tuple(result)


def _with_contracts(
    declaration: tuple[tuple[str, object], ...],
    selector: str,
    contracts: tuple[str, ...],
) -> tuple[tuple[str, object], ...]:
    result: list[tuple[str, object]] = []
    for name, item in declaration:
        if name == "selector":
            result.append((name, selector))
        elif name == "finding_tag_complaints":
            result.append(("finding_contracts", contracts))
        else:
            result.append((name, item))
    return tuple(result)


def _write_overlapping_contract_fixture(root: Path) -> None:
    gates = root / "src/alphus/gates"
    gates.mkdir(parents=True, exist_ok=True)
    (gates / "shared_catalog.py").write_text(
        "ALPHUS_COMPLAINT_CONTRACTS: Final = (\n"
        "    ComplaintContract(\n"
        "        name='first-only',\n"
        "        emitters=('demo-one',),\n"
        "        entries=(\n"
        "            ComplaintEntry(emitter='demo-one', tag=rule_tag("
        "Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'first-only')),\n"
        "        ),\n"
        "    ),\n"
        "    ComplaintContract(\n"
        "        name='shared-demo',\n"
        "        emitters=('demo-one', 'demo-two'),\n"
        "        entries=(\n"
        "            ComplaintEntry(emitter='demo-one', tag=rule_tag("
        "Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'shared-demo')),\n"
        "            ComplaintEntry(emitter='demo-two', tag=rule_tag("
        "Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'shared-demo')),\n"
        "        ),\n"
        "    ),\n"
        ")\n",
        encoding="utf-8",
    )
    contracts = root / "src/alphus/contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "rule_tags.py").write_text(
        "class Scope:\n    REPOSITORY = 'repository'\n"
        "class Framework:\n    NONE = 'none'\n"
        "class Category:\n    TESTING = 'testing'\n",
        encoding="utf-8",
    )
    first = _with_contracts(_DECLARATION, "demo-one", ("first-only", "shared-demo"))
    second = _with_contracts(_DECLARATION, "demo-two", ("shared-demo",))
    for filename, declaration in (("first", first), ("second", second)):
        (gates / f"{filename}.py").write_text(
            f"ALPHUS_MORPHOLOGY = {declaration!r}\n", encoding="utf-8"
        )


def _write_contract_fixture(root: Path, *, shared_rule_id: str) -> None:
    scope, framework, category, complaint = shared_rule_id.split("/")[1:]
    rule_tag_call = (
        f"rule_tag(Scope.{scope.upper()}, Framework.{framework.upper()}, "
        f"Category.{category.upper()}, {complaint!r})"
    )
    gates = root / "src/alphus/gates"
    gates.mkdir(parents=True, exist_ok=True)
    (gates / "shared_catalog.py").write_text(
        "ALPHUS_COMPLAINT_CONTRACTS: Final = (\n"
        "    ComplaintContract(\n"
        "        name='shared-demo',\n"
        "        emitters=('demo-one', 'demo-two'),\n"
        "        entries=(\n"
        f"            ComplaintEntry(emitter='demo-one', tag={rule_tag_call}),\n"
        f"            ComplaintEntry(emitter='demo-two', tag={rule_tag_call}),\n"
        "        ),\n"
        "    ),\n"
        ")\n",
        encoding="utf-8",
    )
    contracts = root / "src/alphus/contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "rule_tags.py").write_text(
        "class Scope:\n    REPOSITORY = 'repository'\n"
        "class Framework:\n    NONE = 'none'\n"
        "class Category:\n    TESTING = 'testing'\n    STYLE = 'style'\n",
        encoding="utf-8",
    )
    for filename, selector in (("first", "demo-one"), ("second", "demo-two")):
        declaration = _with_contract(_DECLARATION, selector, "shared-demo")
        (gates / f"{filename}.py").write_text(
            f"ALPHUS_MORPHOLOGY = {declaration!r}\n", encoding="utf-8"
        )


def _module(
    root: Path, name: str, *, declaration: tuple[tuple[str, object], ...] | None = None
) -> None:
    path = root / f"src/alphus/gates/{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = declaration or _DECLARATION
    path.write_text(
        "raise RuntimeError('feature code must not be imported')\n"
        f"ALPHUS_MORPHOLOGY = {value!r}\n"
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )


def test_feature_owned_discovery_accepts_selector_without_central_registry(
    tmp_path: Path,
) -> None:
    _module(tmp_path, "demo")

    manifest = render_manifest(tmp_path)

    assert '"demo-check": RuleMorphology(' in manifest
    assert "DetectionMechanism.EXACT_RULE" in manifest
    assert "ClaimKind.CONDITION" in manifest
    assert "RuleTag(" in manifest
    assert "Scope.REPOSITORY" in manifest
    assert "Framework.NONE" in manifest
    assert "Category.TESTING" in manifest


def test_explicit_complaint_contract_shares_one_tag_across_emitters(
    tmp_path: Path,
) -> None:
    _write_contract_fixture(
        tmp_path, shared_rule_id="alphus/repository/none/testing/shared-demo"
    )

    manifest = render_manifest(tmp_path)

    assert '"demo-one": RuleMorphology(' in manifest
    assert '"demo-two": RuleMorphology(' in manifest
    assert manifest.count('"shared-demo"') == 4
    assert manifest.count('finding_contracts=("shared-demo",)') == 2


def test_feature_can_compose_contracts_with_shared_secondary_owner(
    tmp_path: Path,
) -> None:
    _write_overlapping_contract_fixture(tmp_path)

    manifest = render_manifest(tmp_path)

    assert manifest.count('"first-only"') >= 2
    assert manifest.count('"shared-demo"') >= 4
    assert 'finding_contracts=("first-only", "shared-demo")' in manifest
    assert 'finding_contracts=("shared-demo",)' in manifest


def test_feature_rejects_duplicate_contract_references(tmp_path: Path) -> None:
    _write_contract_fixture(
        tmp_path, shared_rule_id="alphus/repository/none/testing/shared-demo"
    )
    declaration = _with_contracts(
        _DECLARATION, "demo-one", ("shared-demo", "shared-demo")
    )
    (tmp_path / "src/alphus/gates/first.py").write_text(
        f"ALPHUS_MORPHOLOGY = {declaration!r}\n", encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="finding_contracts must not contain duplicates"
    ):
        render_manifest(tmp_path)


def test_complaint_contract_rejects_undeclared_emitter(tmp_path: Path) -> None:
    _write_contract_fixture(
        tmp_path, shared_rule_id="alphus/repository/none/testing/shared-demo"
    )
    declaration = _with_contract(_DECLARATION, "demo-three", "shared-demo")
    gates = tmp_path / "src/alphus/gates"
    (gates / "third.py").write_text(
        f"ALPHUS_MORPHOLOGY = {declaration!r}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="not a permitted emitter"):
        render_manifest(tmp_path)


def test_complaint_contract_rejects_ambiguous_runtime_tag_lookup(
    tmp_path: Path,
) -> None:
    _write_contract_fixture(
        tmp_path, shared_rule_id="alphus/repository/none/testing/shared-demo"
    )
    (tmp_path / "src/alphus/gates/shared_catalog.py").write_text(
        "ALPHUS_COMPLAINT_CONTRACTS = (\n"
        "    ComplaintContract(\n"
        "        name='shared-demo',\n"
        "        emitters=('demo-one',),\n"
        "        entries=(\n"
        "            ComplaintEntry(emitter='demo-one', tag=rule_tag("
        "Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'shared-demo')),\n"
        "            ComplaintEntry(emitter='demo-one', tag=rule_tag("
        "Scope.REPOSITORY, Framework.NONE, Category.STYLE, 'shared-demo')),\n"
        "        ),\n"
        "    ),\n"
        ")\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ambiguous runtime tag lookup"):
        render_manifest(tmp_path)


def test_uncontracted_cross_selector_finding_id_remains_an_error(
    tmp_path: Path,
) -> None:
    for filename, selector in (("first", "demo-one"), ("second", "demo-two")):
        declaration = _with_field(_DECLARATION, "selector", selector)
        declaration = _with_field(
            declaration, "finding_tag_complaints", ("shared-demo",)
        )
        _module(tmp_path, filename, declaration=declaration)
        path = tmp_path / f"src/alphus/gates/{filename}.py"
        path.write_text(
            f"ALPHUS_MORPHOLOGY = {declaration!r}\n"
            "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, "
            "'shared-demo')\n",
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="declared by multiple owners"):
        render_manifest(tmp_path)


def test_complaint_contract_rejects_unknown_rule_tag_enum(tmp_path: Path) -> None:
    _write_contract_fixture(
        tmp_path, shared_rule_id="alphus/repository/none/tooling/shared-demo"
    )

    with pytest.raises(ValueError, match="invalid complaint contract rule ID"):
        render_manifest(tmp_path)


def test_feature_definition_generates_catalog_and_lazy_runner_views(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    feature_declaration = _DECLARATION + (
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "findings"),
        ("summary", "Reports a demo condition."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
        ("display_name", "Demo check"),
        ("input_mode", "configured-source-scan"),
    )
    (gates / "demo_check.py").write_text(
        _feature_source(feature_declaration)
        + "def check_demo(root, files, config):\n    return []\n"
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )
    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    pass\n", encoding="utf-8"
    )
    (policy / "sources.py").write_text(
        "class DemoPolicy:\n    pass\n", encoding="utf-8"
    )
    group = gates / "demo_group"
    group.mkdir()
    (group / "runners.py").write_text(
        "from types import MappingProxyType\n"
        "DEMO_GROUP_RULE_RUNNERS: object = MappingProxyType({})\n",
        encoding="utf-8",
    )

    registration = feature_registrations(tmp_path)
    definitions = render_feature_manifest(tmp_path)
    policies = render_feature_policies(tmp_path)
    quality_rules = render_quality_rule_names(tmp_path)
    runner_manifest = render_runner_manifest(tmp_path)

    assert [item.selector for item in registration] == ["demo-check"]
    assert '"demo-check": FeatureDefinition(' in definitions
    assert "policy_model=DemoPolicy" in definitions
    assert 'display_name="Demo check"' in definitions
    assert 'input_mode="configured-source-scan"' in definitions
    assert "class GeneratedFeaturePolicies(StrictModel):" in policies
    assert "demo_policy: _demo_policy_policy | None = None" in policies
    assert '"demo-check",' in quality_rules
    assert "def _run_feature_demo_check(" not in runner_manifest
    assert 'import_module("alphus.gates.demo_check")' not in runner_manifest
    assert '"demo-check": _run_feature_demo_check' not in runner_manifest
    assert "**DEMO_GROUP_RULE_RUNNERS," in runner_manifest


def test_composite_feature_can_reference_another_feature_policy_field(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    for selector, policy_field, policy_inputs in (
        ("base-check", "base_policy", ("base_policy",)),
        (
            "composite-check",
            "composite_policy",
            ("composite_policy", "base_policy"),
        ),
    ):
        declaration = tuple(
            (key, selector if key == "selector" else value)
            for key, value in _DECLARATION
        ) + (
            ("finding_tag_complaints", (selector,)),
            ("policy_field", policy_field),
            ("policy_model", "alphus.policy.sources.DemoPolicy"),
            ("output_shape", "findings"),
            ("summary", f"Reports {selector} findings."),
            ("applies_to", ("python",)),
            ("domains", ()),
            ("requires_files", True),
            ("policy_inputs", policy_inputs),
        )
        (gates / f"{selector.replace('-', '_')}.py").write_text(
            _feature_source(declaration)
            + "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, "
            + f"{selector!r})\n",
            encoding="utf-8",
        )

    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    pass\n", encoding="utf-8"
    )
    (policy / "sources.py").write_text(
        "class DemoPolicy:\n    pass\n", encoding="utf-8"
    )

    features = {item.selector: item for item in feature_registrations(tmp_path)}
    generated_policies = render_feature_policies(tmp_path)

    assert features["composite-check"].policy_inputs == (
        "composite_policy",
        "base_policy",
    )
    assert "base_policy: _base_policy_policy | None = None" in generated_policies
    assert (
        "composite_policy: _composite_policy_policy | None = None" in generated_policies
    )


def test_message_feature_uses_one_typed_morphology_id_for_result_adaptation(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    declaration = _DECLARATION + (
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "messages"),
        ("summary", "Reports a demo message."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
    )
    (gates / "demo_messages.py").write_text(
        _feature_source(declaration), encoding="utf-8"
    )
    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    pass\n", encoding="utf-8"
    )
    (policy / "sources.py").write_text(
        "class DemoPolicy:\n    pass\n", encoding="utf-8"
    )
    group = gates / "demo_group"
    group.mkdir()
    (group / "runners.py").write_text(
        "from types import MappingProxyType\n"
        "DEMO_GROUP_RULE_RUNNERS: object = MappingProxyType({})\n",
        encoding="utf-8",
    )

    registration = feature_registrations(tmp_path)
    manifest = render_manifest(tmp_path)

    assert [item.selector for item in registration] == ["demo-check"]
    assert '"demo-check": RuleMorphology(' in manifest
    assert "RuleTag(" in manifest
    assert '"demo-check"' in manifest


def test_message_feature_rejects_ambiguous_morphology_ids(tmp_path: Path) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    declaration = _DECLARATION + (
        ("finding_tag_complaints", ("demo-check", "second-message")),
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "messages"),
        ("summary", "Reports demo messages."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
    )
    source = _feature_source(declaration)
    (gates / "demo_messages.py").write_text(source, encoding="utf-8")

    with pytest.raises(
        ValueError, match="message features need exactly one typed finding ID"
    ):
        render_manifest(tmp_path)


def test_feature_definition_supports_qualified_constructor_and_selector_constant(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    source = _feature_source(
        _DECLARATION
        + (
            ("policy_field", "demo_policy"),
            ("policy_model", "alphus.policy.sources.DemoPolicy"),
            ("output_shape", "findings"),
            ("summary", "Reports a demo condition."),
            ("applies_to", ("python",)),
            ("domains", ()),
            ("requires_files", True),
        )
    )
    source = source.replace(
        "ALPHUS_CHECK = FeatureDefinition(",
        "SELECTOR = 'demo-check'\nALPHUS_CHECK = metadata.FeatureDefinition(",
        1,
    ).replace("selector='demo-check',", "selector=SELECTOR,", 1)
    source = source.replace(
        ")\nALPHUS_MORPHOLOGY = RuleMorphology(",
        ")\nSELECTOR = 'reassigned-after-check'\nALPHUS_MORPHOLOGY = RuleMorphology(",
        1,
    )
    source = source.replace(
        "from alphus.policy.sources import DemoPolicy\n",
        "import alphus.policy.sources\n",
    ).replace(
        "policy_model=DemoPolicy,", "policy_model=alphus.policy.sources.DemoPolicy,"
    )
    (gates / "demo_check.py").write_text(
        "import metadata\n"
        + source
        + "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )
    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    pass\n", encoding="utf-8"
    )
    (policy / "sources.py").write_text(
        "class DemoPolicy:\n    pass\n", encoding="utf-8"
    )
    group = gates / "demo_group"
    group.mkdir()
    (group / "runners.py").write_text(
        "from types import MappingProxyType\n"
        "DEMO_GROUP_RULE_RUNNERS: object = MappingProxyType({})\n",
        encoding="utf-8",
    )

    registration = feature_registrations(tmp_path)

    assert [item.selector for item in registration] == ["demo-check"]
    assert registration[0].selector == "demo-check"


def test_feature_definition_rejects_reassigned_transitive_alias(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    source = _feature_source(
        _DECLARATION
        + (
            ("policy_field", "demo_policy"),
            ("policy_model", "alphus.policy.sources.DemoPolicy"),
            ("output_shape", "findings"),
            ("summary", "Original summary."),
            ("applies_to", ("python",)),
            ("domains", ()),
            ("requires_files", True),
        )
    ).replace("summary='Original summary.'", "summary=SUMMARY_ALIAS", 1)
    source = source.replace(
        "ALPHUS_CHECK = FeatureDefinition(",
        "A = 'original'\nB = A\nA = 'later'\nSUMMARY_ALIAS = B\n"
        "ALPHUS_CHECK = FeatureDefinition(",
        1,
    )
    (gates / "demo_check.py").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="depends on reassigned constant 'A'"):
        feature_registrations(tmp_path)


def test_feature_registration_without_export_fails_during_static_discovery(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    policy = tmp_path / "src/alphus/policy"
    gates.mkdir(parents=True)
    policy.mkdir(parents=True)
    feature_declaration = _DECLARATION + (
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "findings"),
        ("summary", "Reports a demo condition."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
    )
    source = _feature_source(feature_declaration).split(
        "def _registered_demo_runner", 1
    )[0]
    source += (
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n"
    )
    (gates / "demo.py").write_text(source, encoding="utf-8")
    (policy / "orchestration.py").write_text("class CheckPolicies: pass\n")
    (policy / "sources.py").write_text("class DemoPolicy: pass\n")

    with pytest.raises(ValueError, match="must define exactly one ALPHUS_FEATURE"):
        feature_registrations(tmp_path)


def test_feature_policy_imports_wrap_deterministically(tmp_path: Path) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    policy = tmp_path / "src/alphus/policy"
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text(
        "class CheckPolicies:\n    pass\n", encoding="utf-8"
    )
    (policy / "sources.py").write_text(
        "class DemoPolicyWithALongerThanUsualModelNameOne:\n    pass\n"
        "class DemoPolicyWithALongerThanUsualModelNameTwo:\n    pass\n",
        encoding="utf-8",
    )
    names = (
        "DemoPolicyWithALongerThanUsualModelNameOne",
        "DemoPolicyWithALongerThanUsualModelNameTwo",
    )
    for index, class_name in enumerate(names, start=1):
        selector = f"demo-{index}"
        complaint = f"demo-check-{index}"
        declaration = _with_field(_DECLARATION, "selector", selector)
        declaration = _with_field(declaration, "finding_tag_complaints", (complaint,))
        feature_declaration = declaration + (
            ("policy_field", f"demo_policy_{index}"),
            ("policy_model", f"alphus.policy.sources.{class_name}"),
            ("output_shape", "findings"),
            ("summary", "Reports a demo condition."),
            ("applies_to", ("python",)),
            ("domains", ()),
            ("requires_files", True),
        )
        (gates / f"demo_{index}.py").write_text(
            _feature_source(feature_declaration)
            + "def check_demo(root, files, config):\n    return []\n"
            "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, "
            f"'{complaint}')\n",
            encoding="utf-8",
        )

    generated = render_feature_policies(tmp_path)

    assert "from alphus.policy.sources import (" in generated
    assert f"    {names[0]} as _demo_policy_1_policy," in generated
    assert f"    {names[1]} as _demo_policy_2_policy," in generated
    assert generated.index("_demo_policy_1_policy") < generated.index(
        "_demo_policy_2_policy"
    )


def test_feature_policy_generation_shares_identical_policy_models(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    policy = tmp_path / "src/alphus/policy"
    gates.mkdir(parents=True)
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text("class CheckPolicies: pass\n")
    (policy / "sources.py").write_text("class DemoPolicy: pass\n")

    for name, selector in (("first", "first-check"), ("second", "second-check")):
        feature = _with_field(_DECLARATION, "selector", selector)
        feature = _with_field(feature, "finding_tag_complaints", (selector,))
        feature_declaration = feature + (
            ("policy_field", "shared_policy"),
            ("policy_model", "alphus.policy.sources.DemoPolicy"),
            ("output_shape", "findings"),
            ("summary", "Reports a demo condition."),
            ("applies_to", ("python",)),
            ("domains", ()),
            ("requires_files", True),
        )
        (gates / f"{name}.py").write_text(
            _feature_source(feature_declaration)
            + f"def check_{name}(root, files, config):\n    return []\n"
            "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, "
            f"'{selector}')\n",
            encoding="utf-8",
        )

    generated = render_feature_policies(tmp_path)

    assert generated.count("shared_policy: _shared_policy_policy | None = None") == 1


def test_feature_policy_generation_rejects_conflicting_shared_models(
    tmp_path: Path,
) -> None:
    gates = tmp_path / "src/alphus/gates"
    policy = tmp_path / "src/alphus/policy"
    gates.mkdir(parents=True)
    policy.mkdir(parents=True)
    (policy / "orchestration.py").write_text("class CheckPolicies: pass\n")
    (policy / "sources.py").write_text(
        "class DemoPolicy:\n    pass\nclass OtherPolicy:\n    pass\n"
    )

    for name, selector, policy_model in (
        ("first", "first-check", "DemoPolicy"),
        ("second", "second-check", "OtherPolicy"),
    ):
        feature = _with_field(_DECLARATION, "selector", selector)
        feature = _with_field(feature, "finding_tag_complaints", (selector,))
        feature_declaration = feature + (
            ("policy_field", "shared_policy"),
            ("policy_model", f"alphus.policy.sources.{policy_model}"),
            ("output_shape", "findings"),
            ("summary", "Reports a demo condition."),
            ("applies_to", ("python",)),
            ("domains", ()),
            ("requires_files", True),
        )
        (gates / f"{name}.py").write_text(
            _feature_source(feature_declaration)
            + f"def check_{name}(root, files, config):\n    return []\n"
            "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, "
            f"'{selector}')\n",
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="conflicting policy models"):
        render_feature_policies(tmp_path)


def test_selector_generation_falls_back_to_legacy_literal(tmp_path: Path) -> None:
    policy = tmp_path / "src/alphus/policy"
    (tmp_path / "src/alphus/gates").mkdir(parents=True)
    policy.mkdir(parents=True)
    (policy / "catalog.py").write_text(
        "from types import MappingProxyType\nRULE_SPECS = MappingProxyType({})\n",
        encoding="utf-8",
    )
    (policy / "base.py").write_text(
        "from typing import Literal, TypeAlias\n"
        'QualityRuleName: TypeAlias = Literal["legacy-alpha", "legacy-beta"]\n',
        encoding="utf-8",
    )

    result = render_quality_rule_names(tmp_path)

    assert '    "legacy-alpha",' in result
    assert '    "legacy-beta",' in result


def test_feature_policy_root_symlink_is_rejected(tmp_path: Path) -> None:
    gates = tmp_path / "src/alphus/gates"
    gates.mkdir(parents=True)
    outside = tmp_path.with_name(f"{tmp_path.name}-outside-policy")
    outside.mkdir()
    (outside / "orchestration.py").write_text("class CheckPolicies: pass\n")
    (outside / "sources.py").write_text("class DemoPolicy: pass\n")
    policy_parent = tmp_path / "src/alphus"
    policy = policy_parent / "policy"
    policy.symlink_to(outside, target_is_directory=True)
    feature_declaration = _DECLARATION + (
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "findings"),
        ("summary", "Reports a demo condition."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
    )
    (gates / "demo.py").write_text(
        _feature_source(feature_declaration)
        + "def check_demo(root, files, config):\n    return []\n"
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )

    try:
        with pytest.raises(ValueError, match="built-in policy root escapes"):
            feature_registrations(tmp_path)
    finally:
        shutil.rmtree(outside)


def test_feature_policy_orchestration_symlink_is_rejected(tmp_path: Path) -> None:
    gates = tmp_path / "src/alphus/gates"
    policy = tmp_path / "src/alphus/policy"
    gates.mkdir(parents=True)
    policy.mkdir(parents=True)
    outside = tmp_path.with_name(f"{tmp_path.name}-outside-orchestration")
    outside.write_text("class CheckPolicies: pass\n", encoding="utf-8")
    (policy / "sources.py").write_text("class DemoPolicy: pass\n", encoding="utf-8")
    (policy / "orchestration.py").symlink_to(outside)
    feature_declaration = _DECLARATION + (
        ("policy_field", "demo_policy"),
        ("policy_model", "alphus.policy.sources.DemoPolicy"),
        ("output_shape", "findings"),
        ("summary", "Reports a demo condition."),
        ("applies_to", ("python",)),
        ("domains", ()),
        ("requires_files", True),
    )
    (gates / "demo.py").write_text(
        _feature_source(feature_declaration)
        + "def check_demo(root, files, config):\n    return []\n"
        "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')\n",
        encoding="utf-8",
    )

    try:
        with pytest.raises(ValueError, match="strict policy declaration escapes"):
            feature_registrations(tmp_path)
    finally:
        outside.unlink()


def test_discovery_rejects_orphan_finding_complaint(tmp_path: Path) -> None:
    source = _DECLARATION
    _module(
        tmp_path,
        "demo",
        declaration=_with_field(source, "finding_tag_complaints", ("orphan",)),
    )

    with pytest.raises(ValueError, match="finding complaint 'orphan' is not declared"):
        render_manifest(tmp_path)


def test_discovery_ignores_rule_tags_with_dynamic_components(tmp_path: Path) -> None:
    _module(tmp_path, "demo")
    path = tmp_path / "src/alphus/gates/demo.py"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "rule_tag(Scope.REPOSITORY, Framework.NONE, Category.TESTING, 'demo-check')",
            "rule_tag(scope, Framework.NONE, Category.TESTING, 'demo-check')",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="finding complaint 'demo-check' is not declared"
    ):
        render_manifest(tmp_path)


def test_discovery_rejects_orphan_before_duplicate_complaint_matches(
    tmp_path: Path,
) -> None:
    declaration = _with_field(
        _DECLARATION, "finding_tag_complaints", ("orphan", "shared")
    )
    _module(tmp_path, "demo", declaration=declaration)
    path = tmp_path / "src/alphus/gates/demo.py"
    with path.open("a", encoding="utf-8") as source:
        source.write(
            "rule_tag(Scope.PYTHON, Framework.NONE, Category.TESTING, 'shared')\n"
            "rule_tag(Scope.MARKDOWN, Framework.NONE, Category.TESTING, 'shared')\n"
        )

    with pytest.raises(ValueError, match="finding complaint 'orphan' is not declared"):
        render_manifest(tmp_path)


def test_discovery_rejects_ambiguous_complaint_matches(tmp_path: Path) -> None:
    declaration = _with_field(_DECLARATION, "finding_tag_complaints", ("shared",))
    _module(tmp_path, "demo", declaration=declaration)
    path = tmp_path / "src/alphus/gates/demo.py"
    with path.open("a", encoding="utf-8") as source:
        source.write(
            "rule_tag(Scope.PYTHON, Framework.NONE, Category.TESTING, 'shared')\n"
            "rule_tag(Scope.MARKDOWN, Framework.NONE, Category.TESTING, 'shared')\n"
        )

    with pytest.raises(
        ValueError, match="finding complaint 'shared' resolves to multiple rule tags"
    ):
        render_manifest(tmp_path)


def test_discovery_preserves_declared_complaint_order(tmp_path: Path) -> None:
    declaration = _with_field(
        _DECLARATION, "finding_tag_complaints", ("second", "demo-check")
    )
    _module(tmp_path, "demo", declaration=declaration)
    path = tmp_path / "src/alphus/gates/demo.py"
    with path.open("a", encoding="utf-8") as source:
        source.write(
            "rule_tag(Scope.PYTHON, Framework.NONE, Category.TESTING, 'second')\n"
        )

    manifest = render_manifest(tmp_path)
    finding_ids = manifest.split("finding_ids=(", maxsplit=1)[1]

    assert finding_ids.index('"second"') < finding_ids.index('"demo-check"')


def test_discovery_rejects_oversized_source_before_parsing(tmp_path: Path) -> None:
    _module(tmp_path, "demo")
    oversized = tmp_path / "src/alphus/gates/oversized.py"
    oversized.write_bytes(b"#" * (1_048_576 + 1))

    with pytest.raises(ValueError, match="byte scan limit"):
        render_manifest(tmp_path)


def test_discovery_rejects_duplicate_selectors(tmp_path: Path) -> None:
    _module(tmp_path, "alpha")
    _module(tmp_path, "beta")

    with pytest.raises(ValueError, match="duplicate morphology selector"):
        render_manifest(tmp_path)


def test_discovery_rejects_duplicate_finding_ids_across_selectors(
    tmp_path: Path,
) -> None:
    _module(tmp_path, "alpha")
    declaration = _with_field(_DECLARATION, "selector", "other-check")
    _module(tmp_path, "beta", declaration=declaration)

    with pytest.raises(ValueError, match="finding ID .* declared by multiple owners"):
        render_manifest(tmp_path)


def test_discovery_rejects_non_slug_morphology_values(tmp_path: Path) -> None:
    declaration = _with_field(_DECLARATION, "languages_formats", ("Python",))
    _module(tmp_path, "bad_slug", declaration=declaration)

    with pytest.raises(
        ValueError, match="languages_formats must contain lowercase slugs"
    ):
        render_manifest(tmp_path)


def test_discovery_rejects_symlinked_python_modules(tmp_path: Path) -> None:
    _module(tmp_path, "local")
    outside = tmp_path / "outside.py"
    outside.write_text("ALPHUS_MORPHOLOGY = {}\n", encoding="utf-8")
    (tmp_path / "src/alphus/gates/external.py").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes the built-in gates root"):
        render_manifest(tmp_path)


def test_discovery_rejects_symlinked_gates_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "demo.py").write_text("ALPHUS_MORPHOLOGY = ()\n", encoding="utf-8")
    gates = repository / "src/alphus/gates"
    gates.parent.mkdir(parents=True)
    gates.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="built-in gates root escapes the repository"):
        render_manifest(repository)


def test_discovery_rejects_unknown_mechanisms(tmp_path: Path) -> None:
    declaration = _with_field(_DECLARATION, "mechanisms", ("mystery",))
    _module(tmp_path, "demo", declaration=declaration)

    with pytest.raises(ValueError, match="unsupported morphology mechanism"):
        render_manifest(tmp_path)


def test_checked_in_manifest_matches_feature_declarations(
    pytestconfig: pytest.Config,
) -> None:
    assert main(["--root", str(pytestconfig.rootpath), "--check"]) == 0


def test_registry_stub_narrows_literals_from_feature_owned_forms(
    pytestconfig: pytest.Config,
) -> None:
    stub = render_builtin_registry_stub(Path(pytestconfig.rootpath))

    assert 'selector: Literal["file-size"]' in stub
    assert ") -> FindingBuiltinFeature[FileSizePolicy]: ..." in stub
    assert 'selector: Literal["cli"]' in stub
    assert ") -> MessageBuiltinFeature[CliPolicy]: ..." in stub
    assert 'selector: Literal["cyclomatic-complexity"]' in stub
    assert ") -> CyclomaticBuiltinFeature[CyclomaticComplexityPolicy]: ..." in stub
    assert "selector: str, /" in stub
    assert ") -> BuiltinFeatureRegistration: ..." in stub


def test_check_detects_stale_generated_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _module(tmp_path, "demo")
    catalog = tmp_path / "src/alphus/policy/catalog.py"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        "from types import MappingProxyType\n"
        '_LEGACY_RULE_SPECS = MappingProxyType({"demo-check": None})\n',
        encoding="utf-8",
    )
    target = tmp_path / "src/alphus/policy/_generated_morphology.py"
    feature_target = tmp_path / "src/alphus/policy/_generated_feature_definitions.py"
    feature_policies_target = (
        tmp_path / "src/alphus/policy/_generated_feature_policies.py"
    )
    quality_rules_target = (
        tmp_path / "src/alphus/policy/_generated_quality_rule_names.py"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_manifest(tmp_path), encoding="utf-8")
    feature_target.write_text(render_feature_manifest(tmp_path), encoding="utf-8")
    feature_policies_target.write_text(
        render_feature_policies(tmp_path), encoding="utf-8"
    )
    quality_rules_target.write_text(
        render_quality_rule_names(tmp_path), encoding="utf-8"
    )
    registry_stub_target = tmp_path / "src/alphus/plugins/builtin_registry.pyi"
    registry_stub_target.parent.mkdir(parents=True, exist_ok=True)
    registry_stub_target.write_text(
        render_builtin_registry_stub(tmp_path), encoding="utf-8"
    )

    assert main(["--root", str(tmp_path), "--check"]) == 0
    target.write_text(
        target.read_text(encoding="utf-8") + "# stale\n", encoding="utf-8"
    )
    assert main(["--root", str(tmp_path), "--check"]) == 1
    assert "is stale" in capsys.readouterr().err

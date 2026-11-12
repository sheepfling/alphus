from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import HeuristicTotalConsumptionPolicy, QualityGateConfig
from alphus.execution.dispatch import run_builtin_rule
from alphus.gates.review.heuristic_total_consumption import (
    ALPHUS_FEATURE,
    check_heuristic_total_consumption,
    heuristic_total_consumption_sites,
    resolve_heuristic_total_consumption_policy,
    run_heuristic_total_consumption_feature,
)
from alphus.plugins.builtin import FindingBuiltinFeature

_DIRECT = """\
import re

def preserve_text(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", text)
"""

_CAPTURED = """\
import re

def preserve_text(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z]+", text)
    return tokens
"""


def _policy(**updates: object) -> HeuristicTotalConsumptionPolicy:
    return HeuristicTotalConsumptionPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/text/*.py",),
            "function_names": ("preserve_text",),
            "input_names": ("text",),
            "token_match_helpers": ("re.findall",),
            "output_contract": "preserve-unmatched-spans",
            **updates,
        }
    )


@pytest.mark.parametrize("source", [_DIRECT, _CAPTURED])
def test_reports_only_configured_token_match_results(source: str) -> None:
    sites = heuristic_total_consumption_sites(source, _policy())
    assert [(site.function, site.input_name, site.helper) for site in sites] == [
        ("preserve_text", "text", "re.findall")
    ]


def test_annotation_only_name_preserves_selected_function_evidence() -> None:
    source = _DIRECT + "\npreserve_text: object\n"
    assert len(heuristic_total_consumption_sites(source, _policy())) == 1


@pytest.mark.parametrize(
    "signature",
    [
        "def preserve_text(text: str, re: object) -> list[str]:",
        "def preserve_text(text: str, *re: object) -> list[str]:",
        "def preserve_text(text: str, **re: object) -> list[str]:",
    ],
)
def test_parameter_shadowing_configured_helper_root_abstains(
    signature: str,
) -> None:
    source = _DIRECT.replace("def preserve_text(text: str) -> list[str]:", signature)
    assert heuristic_total_consumption_sites(source, _policy()) == []


@pytest.mark.parametrize(
    "source",
    [
        _DIRECT.replace("re.findall", "re.finditer"),
        _DIRECT.replace("text)", "other_text)"),
        _DIRECT.replace('return re.findall(r"[A-Za-z]+", text)', "return text"),
        _DIRECT.replace("preserve_text", "extract_tokens"),
        _CAPTURED.replace("return tokens", "return tokens + [text]"),
        _DIRECT + "\npreserve_text = lambda text: text\n",
        _DIRECT + "\nfrom other_module import preserve_text\n",
        _DIRECT + "\nclass preserve_text: pass\n",
        _DIRECT + "\ndef wrapper(default=(preserve_text := replacement)): pass\n",
    ],
)
def test_other_helpers_preserving_shapes_and_rebindings_abstain(source: str) -> None:
    assert heuristic_total_consumption_sites(source, _policy()) == []


def test_unconfigured_function_scope_does_not_report_token_extractor() -> None:
    source = _DIRECT.replace("preserve_text", "extract_tokens")
    assert heuristic_total_consumption_sites(source, _policy()) == []


def test_rebinding_one_selected_function_does_not_suppress_other_functions() -> None:
    source = (
        _DIRECT.replace("preserve_text", "preserve_a")
        + "\n"
        + _DIRECT.replace("preserve_text", "preserve_b")
        + "\npreserve_b = replacement\n"
    )
    sites = heuristic_total_consumption_sites(
        source, _policy(function_names=("preserve_a", "preserve_b"))
    )
    assert [site.function for site in sites] == ["preserve_a"]


def test_module_comprehension_target_does_not_shadow_selected_function() -> None:
    source = _DIRECT + "\npreviews = [preserve_text for preserve_text in callbacks]\n"

    assert len(heuristic_total_consumption_sites(source, _policy())) == 1


def test_module_comprehension_walrus_still_counts_as_rebinding() -> None:
    source = _DIRECT + "\npreviews = [(preserve_text := item) for item in callbacks]\n"

    assert heuristic_total_consumption_sites(source, _policy()) == []


def test_module_match_capture_rebinding_abstains() -> None:
    source = (
        _DIRECT
        + "\nmatch replacement:\n"
        + "    case {'callback': preserve_text}: pass\n"
    )

    assert heuristic_total_consumption_sites(source, _policy()) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("output_contract", "lossy-extractor"),
        ("token_match_helpers", ()),
        ("function_names", ()),
    ],
)
def test_policy_requires_explicit_content_preservation_contract(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        _policy(**{field: value})


def test_check_honors_path_scope_and_exclusion(tmp_path: Path) -> None:
    selected = tmp_path / "src/text/normalizer.py"
    selected.parent.mkdir(parents=True)
    selected.write_text(_DIRECT, encoding="utf-8")
    path = Path("src/text/normalizer.py")
    assert len(check_heuristic_total_consumption(tmp_path, (path,), _policy())) == 1
    assert not check_heuristic_total_consumption(
        tmp_path, (path,), _policy(exclude=("src/text/normalizer.py",))
    )


def test_registration_binds_typed_heuristic_policy_and_finding_runner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "src/text/parser.py"
    path.parent.mkdir(parents=True)
    path.write_text(_DIRECT, encoding="utf-8")
    relative = path.relative_to(tmp_path)
    policy = _policy()
    config = QualityGateConfig.model_validate(
        {"schema_version": 1, "checks": {"heuristic_total_consumption": policy}},
        strict=True,
    )

    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.definition.policy_model is HeuristicTotalConsumptionPolicy
    assert type(resolve_heuristic_total_consumption_policy(config)) is (
        HeuristicTotalConsumptionPolicy
    )
    expected = run_heuristic_total_consumption_feature(
        tmp_path, [relative], resolve_heuristic_total_consumption_policy(config)
    )
    assert check_heuristic_total_consumption(tmp_path, [relative], policy) == expected
    assert (
        run_builtin_rule("heuristic-total-consumption", tmp_path, [relative], config)
        == expected
    )

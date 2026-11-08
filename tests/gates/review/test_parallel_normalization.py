from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import ParallelNormalizationPolicy, QualityGateConfig
from alphus.gates.review.parallel_normalization import (
    ALPHUS_FEATURE,
    check_parallel_normalization,
    parallel_normalization_sites,
    resolve_parallel_normalization_policy,
)
from alphus.plugins.builtin import FindingBuiltinFeature

_DRIFT = """\
def normalize_for_display(text: str) -> str:
    return " ".join(text.split())

def normalize_for_key(text: str) -> str:
    return "-".join(text.split())
"""


def test_registration_binds_finding_runner_to_normalization_policy() -> None:
    assert isinstance(ALPHUS_FEATURE, FindingBuiltinFeature)
    assert ALPHUS_FEATURE.policy_resolver is resolve_parallel_normalization_policy
    assert ALPHUS_FEATURE.definition.policy_model is ParallelNormalizationPolicy


def test_resolver_returns_the_strict_declared_normalization_policy() -> None:
    config = QualityGateConfig.model_validate(
        {
            "schema_version": 1,
            "checks": {"parallel_normalization": _policy()},
        },
        strict=True,
    )
    policy = resolve_parallel_normalization_policy(config)

    assert type(policy) is ParallelNormalizationPolicy
    assert policy == _policy()


def _policy(**updates: object) -> ParallelNormalizationPolicy:
    return ParallelNormalizationPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/text/*.py",),
            "pairs": (
                {
                    "concept": "canonical display text",
                    "first_function": "normalize_for_display",
                    "second_function": "normalize_for_key",
                    "output_contract": "same-output-for-same-input",
                },
            ),
            **updates,
        }
    )


def test_reports_separator_drift_under_explicit_same_output_contract() -> None:
    sites = parallel_normalization_sites(_DRIFT, _policy())
    assert len(sites) == 1
    assert sites[0].concept == "canonical display text"
    assert sites[0].first_signature.join_separator == " "
    assert sites[0].second_signature.join_separator == "-"


@pytest.mark.parametrize(
    "source",
    [
        _DRIFT.replace('"-".join', '" ".join'),
        _DRIFT.replace("text: str", "text: object"),
        _DRIFT.replace(
            'return "-".join(text.split())',
            'parts = text.split()\n    return "-".join(parts)',
        ),
        _DRIFT.replace("normalize_for_key", "different_function"),
        _DRIFT + "\nnormalize_for_key = lambda text: text\n",
        _DRIFT + "\nclass normalize_for_key:\n    pass\n",
        _DRIFT + "\nfrom other_module import *\n",
        _DRIFT + "\ndel normalize_for_key\n",
        _DRIFT
        + "\ntry:\n    pass\nexcept ValueError as normalize_for_key:\n    pass\n",
        _DRIFT
        + "\nmatch replacement:\n    case {'callback': normalize_for_key}: pass\n",
        _DRIFT + "\nif enabled:\n    def normalize_for_key(text: str) -> str:\n"
        "        return text\n",
    ],
)
def test_equal_otherwise_unconfigured_or_rebound_forms_abstain(source: str) -> None:
    assert parallel_normalization_sites(source, _policy()) == []


def test_split_separator_drift_is_reported() -> None:
    source = _DRIFT.replace('"-".join(text.split())', '"-".join(text.split(";"))')
    sites = parallel_normalization_sites(source, _policy())
    assert len(sites) == 1
    assert sites[0].first_signature.split_separator is None
    assert sites[0].second_signature.split_separator == ";"


def test_pair_split_across_selected_files_is_explicitly_not_evaluated(
    tmp_path: Path,
) -> None:
    first = tmp_path / "src/text/first.py"
    second = tmp_path / "src/text/second.py"
    first.parent.mkdir(parents=True)
    first.write_text(
        _DRIFT.split("\ndef normalize_for_key", maxsplit=1)[0], encoding="utf-8"
    )
    second.write_text(
        "def normalize_for_key(text: str) -> str:\n    return '-'.join(text.split())\n",
        encoding="utf-8",
    )
    findings = check_parallel_normalization(
        tmp_path, (Path("src/text/first.py"), Path("src/text/second.py")), _policy()
    )
    assert len(findings) == 1
    assert "NOT EVALUATED" in findings[0].message
    assert "not evaluated" in findings[0].message


def test_equal_pair_in_one_file_is_evaluated_without_diagnostic(tmp_path: Path) -> None:
    selected = tmp_path / "src/text/normalizers.py"
    selected.parent.mkdir(parents=True)
    selected.write_text(_DRIFT.replace('"-".join', '" ".join'), encoding="utf-8")
    assert not check_parallel_normalization(
        tmp_path, (Path("src/text/normalizers.py"),), _policy()
    )


@pytest.mark.parametrize(
    "first_source,second_source",
    [
        (
            "def normalize_for_display(text: str) -> str:\n    return text\n",
            "",
        ),
        (
            (
                "def normalize_for_display(text: str) -> str:\n    return text\n"
                "def normalize_for_display(text: str) -> str:\n    return text\n"
            ),
            "def normalize_for_key(text: str) -> str:\n    return text\n",
        ),
    ],
)
def test_absent_or_ambiguous_helpers_do_not_claim_cross_file_coverage(
    tmp_path: Path, first_source: str, second_source: str
) -> None:
    first = tmp_path / "src/text/first.py"
    second = tmp_path / "src/text/second.py"
    first.parent.mkdir(parents=True)
    first.write_text(first_source, encoding="utf-8")
    second.write_text(second_source, encoding="utf-8")
    assert not check_parallel_normalization(
        tmp_path, (Path("src/text/first.py"), Path("src/text/second.py")), _policy()
    )


@pytest.mark.parametrize(
    "pair",
    [
        {
            "concept": "same",
            "first_function": "normalize_for_display",
            "second_function": "normalize_for_display",
            "output_contract": "same-output-for-same-input",
        },
        {
            "concept": "same",
            "first_function": "normalize_for_display",
            "second_function": "normalize_for_key",
            "output_contract": "unknown-contract",
        },
    ],
)
def test_policy_requires_two_distinct_functions_and_declared_contract(
    pair: Mapping[str, str],
) -> None:
    with pytest.raises(ValidationError):
        _policy(pairs=(pair,))


def test_check_honors_path_scope_and_exclusions(tmp_path: Path) -> None:
    selected = tmp_path / "src/text/normalizers.py"
    selected.parent.mkdir(parents=True)
    selected.write_text(_DRIFT, encoding="utf-8")
    path = Path("src/text/normalizers.py")
    assert len(check_parallel_normalization(tmp_path, (path,), _policy())) == 1
    assert not check_parallel_normalization(
        tmp_path, (path,), _policy(exclude=("src/text/normalizers.py",))
    )
    assert not check_parallel_normalization(
        tmp_path, (Path("src/render/normalizers.py"),), _policy()
    )

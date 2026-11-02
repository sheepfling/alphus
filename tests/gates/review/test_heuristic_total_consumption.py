from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import HeuristicTotalConsumptionPolicy
from alphus.gates.review.heuristic_total_consumption import (
    check_heuristic_total_consumption,
    heuristic_total_consumption_sites,
)

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


@pytest.mark.parametrize(
    "source",
    [
        _DIRECT.replace("re.findall", "re.finditer"),
        _DIRECT.replace("text)", "other_text)"),
        _DIRECT.replace('return re.findall(r"[A-Za-z]+", text)', "return text"),
        _DIRECT.replace("preserve_text", "extract_tokens"),
        _CAPTURED.replace("return tokens", "return tokens + [text]"),
        _DIRECT + "\npreserve_text = lambda text: text\n",
    ],
)
def test_other_helpers_preserving_shapes_and_rebindings_abstain(source: str) -> None:
    assert heuristic_total_consumption_sites(source, _policy()) == []


def test_unconfigured_function_scope_does_not_report_token_extractor() -> None:
    source = _DIRECT.replace("preserve_text", "extract_tokens")
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

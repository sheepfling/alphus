"""Boundary tests for declared source-specific repair clusters."""

from pathlib import Path

import pytest

from alphus.config import PatchCascadePolicy
from alphus.gates.review.patch_cascade import check_patch_cascade, patch_cascade_sites


def _policy() -> PatchCascadePolicy:
    return PatchCascadePolicy.model_validate(
        {
            "extensions": [".py"],
            "exclude": [],
            "source_paths": ["src/*.py"],
            "functions": [
                {
                    "function_name": "parse_document",
                    "selector_names": ["repair_id"],
                    "repair_ids": ["vendor-a", "vendor-b"],
                    "normalization_helpers": ["normalize_text"],
                    "function_contract": "general-parser",
                }
            ],
        }
    )


def test_two_declared_repair_ids_with_normalization_are_review_candidates() -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
"""
    sites = patch_cascade_sites(source, _policy())
    assert len(sites) == 1
    assert sites[0].repair_ids == ("vendor-a", "vendor-b")
    assert sites[0].helpers == ("normalize_text",)


def test_single_repair_branch_is_below_cluster_threshold() -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    return text
"""
    assert patch_cascade_sites(source, _policy()) == []


def test_unconfigured_id_and_nested_function_do_not_count() -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-c":
        text = normalize_text(text, "-")
    def nested():
        if repair_id == "vendor-b":
            normalize_text(text, "-")
    return text
"""
    assert patch_cascade_sites(source, _policy()) == []


def test_local_helper_rebinding_makes_identity_unknown() -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    normalize_text = identity
    return text
"""
    assert patch_cascade_sites(source, _policy()) == []


def test_parameter_shadowing_of_helper_makes_identity_unknown() -> None:
    source = """\
def parse_document(repair_id, text, normalize_text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
"""
    assert patch_cascade_sites(source, _policy()) == []


def test_redefinition_of_selected_parser_is_ambiguous() -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
parse_document = replacement
"""
    assert patch_cascade_sites(source, _policy()) == []


@pytest.mark.parametrize(
    "rebind",
    [
        "from other_module import parse_document",
        "import other_module as parse_document",
        "class parse_document:\n    pass",
        "del parse_document",
    ],
)
def test_import_class_and_delete_rebindings_make_parser_unknown(rebind: str) -> None:
    source = (
        """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
"""
        + rebind
        + "\n"
    )
    assert patch_cascade_sites(source, _policy()) == []


def test_rule_respects_configured_path_scope_and_exclusions(tmp_path: Path) -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
"""
    selected = tmp_path / "src/parser.py"
    selected.parent.mkdir()
    selected.write_text(source, encoding="utf-8")
    path = selected.relative_to(tmp_path)
    assert len(check_patch_cascade(tmp_path, (path,), _policy())) == 1
    assert not check_patch_cascade(
        tmp_path,
        (path,),
        _policy().model_copy(update={"exclude": ("src/parser.py",)}),
    )
    assert not check_patch_cascade(tmp_path, (Path("other/parser.py"),), _policy())

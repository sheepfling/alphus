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


def test_comprehension_local_target_does_not_shadow_normalization_helper() -> None:
    source = """\
def parse_document(repair_id, text, callbacks):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    previews = [normalize_text for normalize_text in callbacks]
    return text
"""
    assert len(patch_cascade_sites(source, _policy())) == 1


def test_comprehension_local_callback_is_not_configured_helper_evidence() -> None:
    source = """\
def parse_document(repair_id, text, callbacks):
    if repair_id == "vendor-a":
        previews = [normalize_text(text) for normalize_text in callbacks]
    if repair_id == "vendor-b":
        previews = [normalize_text(text) for normalize_text in callbacks]
    return text
"""
    assert patch_cascade_sites(source, _policy()) == []


def test_unrelated_comprehension_target_preserves_helper_call_evidence() -> None:
    source = """\
def parse_document(repair_id, text, callbacks):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
        previews = [normalize_text(item, " ") for item in callbacks]
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
"""
    assert len(patch_cascade_sites(source, _policy())) == 1


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


def test_pattern_capture_shadowing_normalization_helper_makes_identity_unknown() -> (
    None
):
    source = """\
def parse_document(repair_id, text, options):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    match options:
        case {"normalize": normalize_text}:
            pass
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


@pytest.mark.parametrize(
    "shadowing",
    [
        "from unrelated import identity as normalize_text",
        "def normalize_text(text, separator):\n        return text",
    ],
)
def test_import_and_function_helper_shadowing_make_identity_unknown(
    shadowing: str,
) -> None:
    source = f"""\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    {shadowing}
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


def test_definition_time_walrus_rebinding_makes_parser_ambiguous() -> None:
    source = """\
def parse_document(repair_id, text):
    if repair_id == "vendor-a":
        text = normalize_text(text, " ")
    if repair_id == "vendor-b":
        text = normalize_text(text, "-")
    return text
def wrapper(default=(parse_document := replacement)):
    pass
"""
    assert patch_cascade_sites(source, _policy()) == []


@pytest.mark.parametrize(
    "rebind",
    [
        "from other_module import parse_document",
        "from other_module import *",
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

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import SemanticWorkPresentationPolicy
from alphus.gates.review.semantic_work_presentation import (
    check_semantic_work_presentation,
    semantic_work_presentation_sites,
)

_COMPOSITE = """\
def render_document(source):
    layout = reconstruct_layout(source)
    corrected = apply_content_correction(layout)
    owned = decide_semantic_ownership(corrected)
    return serialize_output(owned)
"""


def _policy(**updates: object) -> SemanticWorkPresentationPolicy:
    return SemanticWorkPresentationPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/presentation/*.py",),
            "function_names": ("render_document",),
            "source_layout_helpers": ("reconstruct_layout",),
            "content_correction_helpers": ("apply_content_correction",),
            "semantic_ownership_helpers": ("decide_semantic_ownership",),
            "serialization_helpers": ("serialize_output",),
            "module_role": "presentation",
            **updates,
        }
    )


def test_reports_all_consumer_declared_roles_in_selected_function() -> None:
    sites = semantic_work_presentation_sites(_COMPOSITE, _policy())
    assert [(site.function, site.line) for site in sites] == [("render_document", 1)]


@pytest.mark.parametrize(
    "source",
    [
        _COMPOSITE.replace("decide_semantic_ownership(corrected)", "corrected"),
        _COMPOSITE.replace("    owned = decide_semantic_ownership(corrected)\n", ""),
        _COMPOSITE.replace("serialize_output", "format_output"),
        _COMPOSITE.replace("reconstruct_layout", "layout_source"),
        _COMPOSITE.replace(
            "    return serialize_output(owned)",
            "    def nested():\n        return serialize_output(owned)\n"
            "    return owned",
        ),
        (
            "def render_document("
            "source=reconstruct_layout(None), "
            "corrected=apply_content_correction(None), "
            "owned=decide_semantic_ownership(None)):\n"
            "    return serialize_output(source)\n"
        ),
        _COMPOSITE + "\nrender_document = lambda source: source\n",
        _COMPOSITE
        + "\nif condition:\n    def render_document(source):\n        return source\n",
    ],
)
def test_partial_unconfigured_nested_or_rebound_work_abstains(source: str) -> None:
    assert semantic_work_presentation_sites(source, _policy()) == []


def test_operations_split_across_functions_do_not_form_composite() -> None:
    source = """\
def render_document(source):
    return serialize_output(source)

def prepare_document(source):
    layout = reconstruct_layout(source)
    corrected = apply_content_correction(layout)
    return decide_semantic_ownership(corrected)
"""
    assert semantic_work_presentation_sites(source, _policy()) == []


def test_non_presentation_module_contract_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _policy(module_role="service")


def test_one_helper_cannot_claim_multiple_roles() -> None:
    with pytest.raises(ValidationError):
        _policy(content_correction_helpers=("reconstruct_layout",))


def test_check_honors_declared_module_path_and_exclusions(tmp_path: Path) -> None:
    selected = tmp_path / "src/presentation/render.py"
    selected.parent.mkdir(parents=True)
    selected.write_text(_COMPOSITE, encoding="utf-8")
    path = Path("src/presentation/render.py")
    assert len(check_semantic_work_presentation(tmp_path, (path,), _policy())) == 1
    assert not check_semantic_work_presentation(
        tmp_path, (path,), _policy(exclude=("src/presentation/render.py",))
    )
    assert not check_semantic_work_presentation(
        tmp_path, (Path("src/service/render.py"),), _policy()
    )

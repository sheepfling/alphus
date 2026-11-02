from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import ProvenanceOwnershipPolicy
from alphus.gates.review.provenance_ownership import (
    check_provenance_ownership,
    provenance_ownership_sites,
)

_PATH_ONLY = """\
def remaining_paragraphs(tables, paragraphs):
    table_paths = {table.source.path for table in tables}
    return [p for p in paragraphs if p.source.path not in table_paths]
"""


def _policy(**updates: object) -> ProvenanceOwnershipPolicy:
    return ProvenanceOwnershipPolicy.model_validate(
        {
            "extensions": (".py",),
            "exclude": (),
            "source_paths": ("src/render/*.py",),
            "function_names": ("remaining_paragraphs",),
            "owner_collection_names": ("tables",),
            "candidate_collection_names": ("paragraphs",),
            "ownership_basis": "exact-source-span",
            **updates,
        }
    )


def test_reports_configured_path_only_exclusion_under_span_contract() -> None:
    sites = provenance_ownership_sites(_PATH_ONLY, _policy())
    assert [
        (site.function, site.owner_collection, site.candidate_collection)
        for site in sites
    ] == [("remaining_paragraphs", "tables", "paragraphs")]


@pytest.mark.parametrize(
    "source",
    [
        _PATH_ONLY.replace("not in table_paths", "in table_paths"),
        _PATH_ONLY.replace("p.source.path", "p.source.span"),
        _PATH_ONLY.replace("paragraphs", "notes"),
        _PATH_ONLY.replace("remaining_paragraphs", "other_function"),
        _PATH_ONLY.replace("return [", "table_paths.clear()\n    return ["),
        _PATH_ONLY.replace("return [", "table_paths = set()\n    return ["),
        _PATH_ONLY.replace(
            "{table.source.path for table in tables}",
            "{(table.source.path, table.source.start, table.source.end) for table in tables}",
        ),
    ],
)
def test_different_relation_collection_or_scope_abstains(source: str) -> None:
    assert provenance_ownership_sites(source, _policy()) == []


def test_file_scope_policy_is_an_explicit_exemption() -> None:
    assert (
        provenance_ownership_sites(_PATH_ONLY, _policy(ownership_basis="file-scope"))
        == []
    )


def test_nested_and_unconfigured_functions_do_not_supply_evidence() -> None:
    unrelated = """\
def unrelated(tables, paragraphs):
    table_paths = {table.source.path for table in tables}
    return [p for p in paragraphs if p.source.path not in table_paths]
"""
    nested = """\
def outer(tables, paragraphs):
    def remaining_paragraphs():
        table_paths = {table.source.path for table in tables}
        return [p for p in paragraphs if p.source.path not in table_paths]
    return []
"""
    assert provenance_ownership_sites(unrelated, _policy()) == []
    assert provenance_ownership_sites(nested, _policy()) == []


def test_policy_requires_explicit_basis_and_scoped_names() -> None:
    with pytest.raises(ValidationError):
        _policy(ownership_basis="unknown")
    with pytest.raises(ValidationError):
        _policy(function_names=())


def test_check_honors_source_paths_and_exclusions(tmp_path: Path) -> None:
    selected = tmp_path / "src/render/filter.py"
    selected.parent.mkdir(parents=True)
    selected.write_text(_PATH_ONLY, encoding="utf-8")
    path = Path("src/render/filter.py")
    assert len(check_provenance_ownership(tmp_path, (path,), _policy())) == 1
    assert not check_provenance_ownership(
        tmp_path, (path,), _policy(exclude=("src/render/filter.py",))
    )

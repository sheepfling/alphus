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


def test_reports_filter_capture_returned_immediately() -> None:
    source = _PATH_ONLY.replace(
        "return [p for p in paragraphs if p.source.path not in table_paths]",
        "remaining = [p for p in paragraphs if p.source.path not in table_paths]\n"
        "    return remaining",
    )
    assert len(provenance_ownership_sites(source, _policy())) == 1


@pytest.mark.parametrize(
    "source",
    [
        _PATH_ONLY.replace("not in table_paths", "in table_paths"),
        _PATH_ONLY.replace("p.source.path", "p.source.span"),
        _PATH_ONLY.replace("paragraphs", "notes"),
        _PATH_ONLY.replace("remaining_paragraphs", "other_function"),
        _PATH_ONLY.replace("return [", "table_paths.clear()\n    return ["),
        _PATH_ONLY.replace("return [", "table_paths = set()\n    return ["),
        _PATH_ONLY + "\nremaining_paragraphs = lambda tables, paragraphs: paragraphs\n",
        _PATH_ONLY + "\nclass remaining_paragraphs:\n    pass\n",
        _PATH_ONLY + "\ndel remaining_paragraphs\n",
        _PATH_ONLY + "\nfrom other_module import remaining_paragraphs\n",
        _PATH_ONLY + "\nfrom other_module import *\n",
        _PATH_ONLY.replace(
            "return [",
            "alias = table_paths\n    alias.clear()\n    return [",
        ),
        _PATH_ONLY.replace(
            "return [",
            "def clear_paths():\n        table_paths.clear()\n    clear_paths()\n    return [",
        ),
        _PATH_ONLY.replace(
            "return [",
            "clear_paths = lambda: table_paths.clear()\n    clear_paths()\n    return [",
        ),
        _PATH_ONLY.replace(
            "return [p for p in paragraphs if p.source.path not in table_paths]",
            "discarded = [p for p in paragraphs if p.source.path not in table_paths]\n"
            "    return paragraphs",
        ),
        _PATH_ONLY.replace(
            "{table.source.path for table in tables}",
            "{(table.source.path, table.source.start, table.source.end) for table in tables}",
        ),
        _PATH_ONLY.replace(
            "{table.source.path for table in tables}",
            "{excluded.source.path for table in tables}",
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


def test_configured_functions_are_selected_independently_per_file(
    tmp_path: Path,
) -> None:
    policy = _policy(function_names=("remaining_paragraphs", "remaining_tables"))
    remaining_tables = _PATH_ONLY.replace("remaining_paragraphs", "remaining_tables")
    first = tmp_path / "src/render/paragraphs.py"
    second = tmp_path / "src/render/tables.py"
    first.parent.mkdir(parents=True)
    first.write_text(_PATH_ONLY, encoding="utf-8")
    second.write_text(remaining_tables, encoding="utf-8")

    findings = check_provenance_ownership(
        tmp_path,
        (Path("src/render/paragraphs.py"), Path("src/render/tables.py")),
        policy,
    )

    assert [finding.path for finding in findings] == [
        "src/render/paragraphs.py",
        "src/render/tables.py",
    ]


def test_ambiguous_function_suppresses_only_its_own_candidate() -> None:
    policy = _policy(function_names=("remaining_paragraphs", "remaining_tables"))
    source = (
        _PATH_ONLY
        + "\ndef remaining_paragraphs(tables, paragraphs):\n    return paragraphs\n"
        + _PATH_ONLY.replace("remaining_paragraphs", "remaining_tables")
    )

    assert [site.function for site in provenance_ownership_sites(source, policy)] == [
        "remaining_tables"
    ]


def test_module_match_capture_rebinding_abstains() -> None:
    source = (
        _PATH_ONLY
        + "\nmatch replacement:\n"
        + "    case {'callback': remaining_paragraphs}: pass\n"
    )

    assert provenance_ownership_sites(source, _policy()) == []


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

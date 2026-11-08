"""Typed result shape for the built-in Python style analyzer."""

from typing import TypedDict


class StyleFindings(TypedDict):
    """Named Python-style finding categories with their source line numbers."""

    bare_containers: list[int]
    bare_tuples: list[int]
    concrete_inputs: list[int]
    local_imports: list[int]
    opaque_mappings: list[int]
    unslotted_dataclasses: list[int]
    quoted_types: list[int]
    type_checking_imports: list[int]
    os_path: list[int]
    main_module_imports: list[int]
    legacy_pydantic_fields: list[int]
    pydantic_collection_contracts: list[int]
    mutable_module_constants: list[int]
    literal_rule_ids: list[int]
    literal_rule_dimensions: list[int]
    raw_reporting_prints: list[int]
    magic_exit_codes: list[int]
    repeated_literals: list[int]
    unnamed_tuple_returns: list[int]
    undifferentiated_patterns: list[int]
    concrete_classmethod_returns: list[int]
    concrete_model_validator_returns: list[int]
    concrete_self_returns: list[int]
    direct_text_reads: list[int]
    duplicate_literal_catalogs: list[int]
    unused_public_constants: list[int]

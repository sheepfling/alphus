"""Compatibility imports for shared Python AST analysis utilities."""

from alphus.support.source_scanning import (
    ImportAliases,
    canonical_expression_name,
    import_aliases,
    qualified_call_lines,
    qualified_reference_lines,
    registry_decorated_function_lines,
)

__all__ = [
    "ImportAliases",
    "canonical_expression_name",
    "import_aliases",
    "qualified_call_lines",
    "qualified_reference_lines",
    "registry_decorated_function_lines",
]

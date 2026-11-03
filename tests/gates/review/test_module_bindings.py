import ast

from alphus.gates.review._module_bindings import module_binding_counts


def test_comprehension_iteration_target_is_not_a_module_binding() -> None:
    tree = ast.parse(
        "def preserve(text): return find_tokens(text)\n"
        "previews = [preserve for preserve in callbacks]\n"
    )

    assert module_binding_counts(tree, ("preserve",)) == {"preserve": 1}


def test_comprehension_assignment_expression_is_a_module_binding() -> None:
    tree = ast.parse(
        "def preserve(text): return find_tokens(text)\n"
        "previews = [(preserve := item) for item in callbacks]\n"
    )

    assert module_binding_counts(tree, ("preserve",)) == {"preserve": 2}


def test_module_pattern_capture_is_a_module_binding() -> None:
    tree = ast.parse(
        "def preserve(text): return find_tokens(text)\n"
        "match replacement:\n"
        "    case {'callback': preserve}: pass\n"
    )

    assert module_binding_counts(tree, ("preserve",)) == {"preserve": 2}


def test_module_star_and_mapping_rest_captures_are_module_bindings() -> None:
    tree = ast.parse(
        "def preserve(text): return find_tokens(text)\n"
        "match replacement:\n"
        "    case [*preserve]: pass\n"
        "match replacement:\n"
        "    case {'callback': callback, **preserve}: pass\n"
    )

    assert module_binding_counts(tree, ("preserve",)) == {"preserve": 3}


def test_exception_handler_alias_is_a_module_binding() -> None:
    tree = ast.parse(
        "def preserve(text): return find_tokens(text)\n"
        "try:\n"
        "    consume()\n"
        "except ValueError as preserve:\n"
        "    consume(preserve)\n"
    )

    assert module_binding_counts(tree, ("preserve",)) == {"preserve": 2}

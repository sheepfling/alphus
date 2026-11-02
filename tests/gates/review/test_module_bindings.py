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

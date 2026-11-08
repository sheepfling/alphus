def check_guards(node_count: int, ast_nodes: list[object]) -> None:
    if node_count > 512:
        return
    if len(ast_nodes) > 512:
        return

from collections.abc import Sequence


def matrix_product(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    rows: int,
    columns: int,
    inner: int,
) -> list[list[float]]:
    return [
        [sum(left[i][k] * right[k][j] for k in range(inner)) for j in range(columns)]
        for i in range(rows)
    ]

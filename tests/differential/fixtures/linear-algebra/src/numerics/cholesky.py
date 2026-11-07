import math
from collections.abc import Sequence


def factorize(matrix: Sequence[Sequence[float]], n: int) -> list[list[float]]:
    lower = [[0.0 for _ in range(n)] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            partial = sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                lower[i][j] = math.sqrt(matrix[i][i] - partial)
            else:
                lower[i][j] = (matrix[i][j] - partial) / lower[j][j]
    return lower

def invert_matrix(matrix: list[list[float]], size: int) -> None:
    for column in range(size):
        pivot_row = max(
            range(column, size),
            key=lambda candidate: abs(matrix[candidate][column]),
        )
        matrix[column], matrix[pivot_row] = matrix[pivot_row], matrix[column]
        diagonal = matrix[column][column]
        matrix[column] = [value / diagonal for value in matrix[column]]
        for row in range(size):
            if row != column:
                factor = matrix[row][column]
                matrix[row] = [
                    current - factor * pivot_value
                    for current, pivot_value in zip(matrix[row], matrix[column])
                ]

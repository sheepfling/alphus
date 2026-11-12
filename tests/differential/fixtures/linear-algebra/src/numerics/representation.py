from collections.abc import Sequence
from typing import Protocol


class Values(Protocol):
    def tolist(self) -> Sequence[float]: ...


class NumpyLike:
    def asarray(self, values: Sequence[float]) -> object:
        return values


np = NumpyLike()


def convert(values: Values) -> object:
    return np.asarray(values.tolist())

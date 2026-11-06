from typing import Protocol

from actions import start


class Action(Protocol):
    def __call__(self, params: object) -> object: ...


REGISTRY: dict[str, Action] = {"start": start}

from typing import Protocol


class Model(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, object]: ...

    def model_validate(self, value: object) -> object: ...


def render(model: Model) -> object:
    payload = model.model_dump(mode="json")
    alias = payload
    return model.model_validate(alias)

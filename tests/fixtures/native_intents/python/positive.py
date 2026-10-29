from collections.abc import Callable

from package.api import PublicWidget as PublicWidget

__all__ = ("PublicWidget",)


class HTTPWidget:
    def register(self, callback: Callable[[], None], _context: object) -> None:
        callback()


class legacy_name:
    """Consumer-specific naming exception."""


def use_shadow(value: int) -> int:
    print(value)
    value = value + 1
    return value


def use_inner_shadow(value: int) -> int:
    def inner(value: int) -> int:
        return value + 1

    return inner(value)

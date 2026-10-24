from package.api import PublicWidget as PublicWidget

__all__ = ("PublicWidget",)


class HTTPWidget:
    def register(self, callback, _context):
        callback()


class legacy_name:
    """Consumer-specific naming exception."""


def use_shadow(value):
    print(value)
    value = value + 1
    return value


def use_inner_shadow(value):
    def inner(value):
        return value + 1

    return inner(value)

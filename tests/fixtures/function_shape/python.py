"""Python native-rule fixtures; each boundary is exercised independently."""

# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN206, F841


def parameters_at_limit(first, second, *, keyword=3):
    return first, second, keyword


def parameters_over_limit(first, second, third, fourth):
    return first, second, third, fourth


class ReceiverShapes:
    def method_at_limit(self, first, second, *, keyword):
        return first, second, keyword

    @classmethod
    def classmethod_at_limit(cls, first, second):
        return cls, first, second

    def positional_only(self, first, /, second=2):
        return first, second

    def keyword_only(self, first, *, second, third=3):
        return first, second, third

    def variadic(self, first, *args, **kwargs):
        return first, args, kwargs


def statements_at_limit():
    first = 1
    second = 2


def statements_over_limit():
    first = 1
    second = 2
    third = 3


def nesting_at_limit():
    if True:
        pass


def nesting_over_limit():
    if True:
        if True:
            pass

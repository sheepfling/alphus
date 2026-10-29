import json  # noqa: F401


class bad_name:  # noqa: N801
    pass


def BadFunction(unused_callback_parameter: object) -> None:  # noqa: N802, ARG001
    never_used = 1  # noqa: F841
    return None
    print("genuinely unreachable")

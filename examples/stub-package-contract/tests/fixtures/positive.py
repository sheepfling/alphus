from typing_extensions import assert_type

from sample_contract import NameNode, flatten_names, format_value

flat_names: list[str] = ["alpha", "beta"]
recursive_names: list[NameNode] = ["alpha", ["beta", ["gamma"]]]

assert_type(flatten_names(flat_names), list[str])
assert_type(flatten_names(recursive_names), list[str])
assert_type(flatten_names(["alpha", ["beta"]]), list[str])
assert_type(format_value(7), str)
assert_type(format_value("seven"), int)


def _uncalled_static_probe() -> None:
    """Checker input only: the verifier never imports or runs this fixture."""
    assert_type(flatten_names(["static-only"]), list[str])

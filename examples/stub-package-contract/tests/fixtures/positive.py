from typing import assert_type

from sample_contract import NameNode, flatten_names

flat_names: list[str] = ["alpha", "beta"]
recursive_names: list[NameNode] = ["alpha", ["beta", ["gamma"]]]

assert_type(flatten_names(flat_names), list[str])
assert_type(flatten_names(recursive_names), list[str])
assert_type(flatten_names(["alpha", ["beta"]]), list[str])

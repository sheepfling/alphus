"""Behavior assertions run against the installed wheel in the target venv."""

import sys
from pathlib import Path

import sample_contract
from sample_contract import flatten_names, format_value

assert (
    Path(sample_contract.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
)

assert flatten_names(["alpha", ["beta", ["gamma"]]]) == ["alpha", "beta", "gamma"]
assert type(format_value(7)) is str
assert format_value(7) == "7"
assert type(format_value("seven")) is int
assert format_value("seven") == 5

for invalid in [[("nested tuple",)], [7]]:
    try:
        flatten_names(invalid)  # type: ignore[arg-type]
    except TypeError:
        continue
    raise AssertionError(f"runtime accepted an unsupported input: {invalid!r}")

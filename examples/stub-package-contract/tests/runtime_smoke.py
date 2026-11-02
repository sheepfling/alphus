"""Behavior assertions run against the installed wheel in the target venv."""

from sample_contract import flatten_names

assert flatten_names(["alpha", ["beta", ["gamma"]]]) == ["alpha", "beta", "gamma"]

for invalid in [[("nested tuple",)], [7]]:
    try:
        flatten_names(invalid)  # type: ignore[arg-type]
    except TypeError:
        continue
    raise AssertionError(f"runtime accepted an unsupported input: {invalid!r}")

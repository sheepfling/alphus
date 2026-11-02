from sample_contract import NameNode, flatten_names, format_value

nested_tuples: list[tuple[str, ...]] = [("alpha",)]
invalid_values: list[object] = ["alpha", 7]

flatten_names(nested_tuples)  # expect-error
flatten_names([("alpha",)])  # expect-error
flatten_names([7])  # expect-error
format_value(object())  # expect-error

# Pydantic practices consumer example

This small consumer enables the five Pydantic v2 checks and the optional
external-schema documentation recommendation. The model deliberately contains
review findings so you can see the profile report them without importing or
executing the model module.

Copy this directory into a Git checkout that uses Alphus, install Alphus with
its Python tools, then run from the copied directory:

```sh
python -m pip install 'alphus[python]'
alphus --root . --config quality-gates.toml --plan --profile pydantic
alphus --root . --config quality-gates.toml --run --profile pydantic --json
```

`PublicRequest` is named as an external model so the metadata rule also checks
its generated JSON Schema descriptions. A class docstring supplies the model
description; `Field(description=...)` supplies a field description. The
`quantity` field intentionally omits that description in this demonstration.
Remove the example violations or disable individual rule flags when adapting
the configuration to a real consumer.

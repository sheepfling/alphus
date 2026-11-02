# Installed three-checker stub example

This small, deliberately artificial package exercises the shared verifier
against a built and installed wheel. It is a development/CI example; it does
not add Alphus to an end user's runtime dependencies.

The checker contract includes an annotated `list[str]` variable and a recursive
list variable as positive inputs. Marked negative lines cover a tuple variable,
a nested tuple literal, and a non-string value. The target runtime smoke checks
accepted nested lists and rejects the same unsupported nested tuple and scalar
shapes, and asserts that its package import comes from the target interpreter
prefix. Native `mypy.stubtest` separately checks the installed module's
runtime/stub member and callable shape. Static fixtures and runtime assertions
are separate evidence lanes.

Provision separate checker and target environments from this directory:

```shell
repo=/path/to/alphus
work="$(mktemp -d)"
python3.11 -m venv "$work/checker"
python3.11 -m venv "$work/target"
"$work/checker/bin/python" -m pip install "$repo[python,mypy,ty]"
"$work/target/bin/python" -m pip install 'build>=1' 'setuptools>=68' wheel 'mypy>=2.3,<3'
"$work/checker/bin/python" -m alphus.gates.stubs.verify \
  --root "$PWD" \
  --config stub-quality.json \
  --target-python "$work/target/bin/python" \
  --report "$work/verification-report.json"
```

The verifier builds the wheel from a temporary source copy, installs that wheel
in the target environment, then runs the selected MyPy, Pyright, and Ty fixture
contract from a separate checker environment. It runs `stubtest` and the
behavior smoke in the target environment. The report records actual checker and
target interpreter identities, installed tool versions, per-stage command and
result, a built-wheel digest and identity, and whether optional lanes were
omitted or not run after an earlier failure.

This fixture runs on the interpreter versions you provision. It is not evidence
that all declared Python/checker/runtime compatibility combinations passed, nor
that a separate runtime distribution and stub-only distribution interoperate.
Consumers must add their own installed runtime and stub package constraints,
public API inventory, allowlist, and actual platform matrix.

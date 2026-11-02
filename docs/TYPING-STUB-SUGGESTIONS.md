# Third-party typing stub suggestions

`typing-stub-suggestions` is an opt-in informational review rule. It suggests
known stub dependencies for imports in selected Python files. It never installs
a package or edits a manifest. The default optional dependency group is
`dev`; set `typing_groups` to other PEP 621 groups when needed.

The built-in catalog currently maps `yaml` → `PyYAML` → `types-PyYAML` for
PyYAML 6.0 on Python 3.10+, `scipy` → `scipy` → `scipy-stubs==1.18.1.*`
for SciPy 1.18.1 on Python 3.12+, `dateutil` → `python-dateutil` →
`types-python-dateutil==2.9.0.*` for python-dateutil 2.9 on Python 3.10+, and
`toml` → `toml` → `types-toml==0.10.8.*` for toml 0.10 on Python 3.10+.
Requests 2.33 maps to `types-requests==2.33.0.*` on Python 3.10+; Requests
2.34+ ships inline typing, so an installed typed runtime is skipped.
The PyYAML mapping records its tested stub checker set (`mypy`, `pyright`, and
`ty`) and compatible stub-version range; the SciPy mapping is scoped to the
same three checkers. The dateutil mapping is scoped to those three checkers,
and the toml mapping to `mypy` and `pyright`; the requests mapping is scoped to
the rule's supported `mypy`, `pyright`, and `ty` options. Findings point to the
importing source line and include the selected checker scope. When a candidate
is suggested, the rule also reports checker distribution versions visible in
the selected interpreter, or that a selected checker is not installed. This is
environment evidence only: the rule does not run the checker or infer checker
behavior from its version. These bounds were checked against
[typeshed's PyYAML metadata](https://github.com/python/typeshed/blob/main/stubs/PyYAML/METADATA.toml),
[types-PyYAML on PyPI](https://pypi.org/project/types-PyYAML/), and the
[official scipy-stubs project metadata](https://github.com/scipy/scipy-stubs/blob/master/pyproject.toml)
[types-python-dateutil on PyPI](https://pypi.org/project/types-python-dateutil/),
and [types-toml on PyPI](https://pypi.org/project/types-toml/), plus
[typeshed's Requests metadata](https://github.com/python/typeshed/blob/main/stubs/requests/METADATA.toml)
and [types-requests on PyPI](https://pypi.org/project/types-requests/) on
2026-11-02. Typeshed currently targets Requests `~=2.33.0` and marks that stub
obsolete at runtime version 2.34.0; the PyPI description confirms Requests
2.34.0+ includes type annotations.
Pyright 1.1.414 was also run against installed PyYAML, SciPy, dateutil, and toml
runtime/stub packages; deliberate incompatible assignments were rejected and
valid return types were inferred. The catalog's dateutil and toml checker
scopes follow their published checker metadata, while this local compatibility
probe used Pyright only. This small catalog is a maintained snapshot, not a live lookup.
When a known import is outside its verified runtime or Python range, the rule
reports that it made no recommendation. Add candidates to override mappings,
or set `builtin_catalog = false` to disable the catalog. `disabled_imports`
disables individual built-ins.

For custom mappings, configure an explicit import name, runtime and stub
distribution, runtime and Python version ranges, checker scope, and compatible
stub-version range. The rule checks that the runtime distribution is declared in PEP 621
`project.dependencies`, its installed version is inside the configured ranges,
the selected PEP 621 optional typing groups exist, and the stub distribution is
not already in those groups. It reads selected-interpreter metadata for both
runtime and stub distributions. A declared stub missing from that interpreter,
an installed but undeclared stub, and a version mismatch are reported as
separate states. It reads installed runtime files to recognize `py.typed` and
bundled `.pyi` files, and skips packages that provide either.
Unavailable runtime metadata is reported as not evaluated; it is not treated as
proof that stubs are missing.

Import names do not reliably identify distribution names. Mypy can suggest
`types-PyYAML` for an untyped `yaml` import, but this rule does not require or
run a checker diagnostic. Stub packages have their own compatibility ranges;
SciPy's stubs use a version line matching the compatible SciPy release. Keep
the catalog current with upstream metadata and your project's supported
dependency versions.

Example configuration using the built-in mappings:

```toml
[checks.typing_stub_suggestions]
extensions = [".py"]
exclude = []
dependency_file = "pyproject.toml"
typing_groups = ["dev"]
checkers = ["mypy", "pyright"]

[[checks.typing_stub_suggestions.candidates]]
import_name = "yaml"
runtime_distribution = "PyYAML"
stub_distribution = "types-PyYAML"
supported_runtime_versions = "==6.0.*"
supported_python_versions = ">=3.10,<4"
checkers = ["mypy", "pyright"]
stub_version_specifier = ">=6.0.12,<7"
```

The dependency manifest should declare PyYAML under `[project].dependencies`
and provide the selected optional group, for example
`[project.optional-dependencies].dev`. Stubs declared in other groups are
not considered by this rule; add every relevant group to `typing_groups`.

To opt out of one built-in, set `disabled_imports = ["yaml"]`; to turn off all
built-ins, set `builtin_catalog = false`. A custom candidate with the same
`import_name` replaces its built-in mapping.

The rule is deliberately conservative. It analyzes syntactic imports in the
selected files, not dynamic imports or checker resolution. It does not run a
checker to validate the candidate stub. It does not query
package indexes at runtime, infer names, or automatically install dependencies.

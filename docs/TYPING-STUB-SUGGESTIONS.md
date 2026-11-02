# Third-party typing stub suggestions

`typing-stub-suggestions` is an opt-in informational review rule. It suggests
known stub dependencies for imports in selected Python files. It never installs
a package or edits a manifest. The default optional dependency group is
`dev`; set `typing_groups` to other PEP 621 groups when needed.

The built-in catalog currently maps `yaml` → `PyYAML` → `types-PyYAML` for
PyYAML 6.0 on Python 3.10+, and `scipy` → `scipy` → `scipy-stubs==1.18.1.*`
for SciPy 1.18.1 on Python 3.12+. These bounds were checked against
[typeshed's PyYAML metadata](https://github.com/python/typeshed/blob/main/stubs/PyYAML/METADATA.toml),
[types-PyYAML on PyPI](https://pypi.org/project/types-PyYAML/), and the
[official scipy-stubs project metadata](https://github.com/scipy/scipy-stubs/blob/master/pyproject.toml)
on 2026-11-02. This small catalog is a maintained snapshot, not a live lookup.
When a known import is outside its verified runtime or Python range, the rule
reports that it made no recommendation. Add candidates to override mappings,
or set `builtin_catalog = false` to disable the catalog. `disabled_imports`
disables individual built-ins.

For custom mappings, configure an explicit import name, runtime and stub
distribution, and runtime and Python version ranges. The rule checks that the runtime distribution is declared in PEP 621
`project.dependencies`, its installed version is inside the configured ranges,
the selected PEP 621 optional typing groups exist, and the stub distribution is
not already in those groups. It reads installed distribution files to recognize
`py.typed` and bundled `.pyi` files, and skips packages that provide either.
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
```

The dependency manifest should declare PyYAML under `[project].dependencies`
and provide the selected optional group, for example
`[project.optional-dependencies].dev`. Stubs declared in other groups are
not considered by this rule; add every relevant group to `typing_groups`.

To opt out of one built-in, set `disabled_imports = ["yaml"]`; to turn off all
built-ins, set `builtin_catalog = false`. A custom candidate with the same
`import_name` replaces its built-in mapping.

The rule is deliberately conservative. It analyzes syntactic imports in the
selected files, not dynamic imports or checker resolution. It does not query
package indexes at runtime, infer names, or automatically install dependencies.

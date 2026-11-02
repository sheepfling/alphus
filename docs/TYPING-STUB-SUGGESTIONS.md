# Third-party typing stub suggestions

`typing-stub-suggestions` is an opt-in informational review rule. It can point
out a configured stub dependency for an import that appears in the selected
Python files. It never installs a package or edits a manifest.

The rule uses an explicit mapping from import name to runtime and stub
distribution, with runtime and Python version ranges supplied by the repository
owner. It checks that the runtime distribution is declared in PEP 621
`project.dependencies`, its installed version is inside the configured ranges,
the selected PEP 621 optional typing groups exist, and the stub distribution is
not already in those groups. It reads installed distribution files to recognize
`py.typed` and bundled `.pyi` files, and skips packages that provide either.
Unavailable runtime metadata is reported as not evaluated; it is not treated as
proof that stubs are missing.

Import names do not reliably identify distribution names. For example, the
known mapping `yaml` → `PyYAML` → `types-PyYAML` must be configured explicitly.
Mypy can suggest `types-PyYAML` for an untyped `yaml` import, but this rule
doesn't run a checker or infer the need from that diagnostic. Stub packages can
also have their own compatibility ranges. Keep mappings and version bounds
current with the project's chosen checker and supported dependency versions.

Example configuration (the values are illustrative and must be verified for
the consumer's dependency set):

```toml
[checks.typing_stub_suggestions]
extensions = [".py"]
exclude = []
dependency_file = "pyproject.toml"
typing_groups = ["dev"]
checkers = ["mypy"]

[[checks.typing_stub_suggestions.candidates]]
import_name = "yaml"
runtime_distribution = "PyYAML"
stub_distribution = "types-PyYAML"
supported_runtime_versions = ">=6,<7"
supported_python_versions = ">=3.11,<4"
package_path = "yaml"
```

The dependency manifest should declare PyYAML under `[project].dependencies`
and provide the selected optional group, for example
`[project.optional-dependencies].dev`. Stubs declared in other groups are
not considered by this rule; add every relevant group to `typing_groups`.

The rule is deliberately conservative. It analyzes syntactic imports in the
selected files, not dynamic imports or checker resolution. It does not query
package indexes, assume typeshed coverage, or synthesize distribution names.

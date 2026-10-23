# Python compatibility imports

A forwarding module keeps an old import path alive while its implementation
moves elsewhere. It is easy to leave one behind after the migration ends.
Alphus's `Python compatibility imports` workflow gate scans Python files under
a source root and fails for forwarding modules without a removal plan.

Run it directly:

```sh
python -m alphus.gates.python.compatibility --source-root src
```

The scanner recognizes import-only modules with optional `__all__` and a
delegating main guard, wildcard imports outside package initializers, and
modules whose docstring begins with an explicit compatibility-import heading
or whose comments explicitly mark a compatibility import. Ordinary package `__init__.py`
exports and command `__main__.py` entry points are not treated as forwarders
unless explicitly marked or using a wildcard import. This is a focused AST
check for common shims, not a proof that every import alias is temporary.

## Temporary removal plan

When a consumer needs a transition window, put a plan in its repository and
pass it to the gate:

```sh
python -m alphus.gates.python.compatibility --source-root src --plan compatibility-imports.toml
```

```toml
schema_version = 1

[[forwarders]]
module = "sample.old_api"
replacement = "sample.new_api:Thing"
owner = "package maintainers"
remove_by = 2027-01-01
```

Every field is required. `module` names the old import path; `replacement`
names the module or object callers should use. `owner` identifies who will
remove it. `remove_by` is a TOML date: on that day, measured in UTC, the gate
fails until the forwarder is removed. A plan entry also fails if its old module
no longer exists, so the plan itself cannot become another abandoned shim.
Duplicate or malformed entries fail. Active plans appear in the gate output.

Without `--plan`, any detected forwarder fails. Alphus's own self-profile uses
that strict mode because its source tree has no approved compatibility imports.

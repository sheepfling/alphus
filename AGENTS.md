# Agent setup

For Python work in this repository, create a virtual environment in the repository and install Alphus in editable mode with its Python development tools:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[python]"
```

Use `.venv/bin/python` and the tools installed in `.venv/bin` for development and validation. `.venv/` is ignored by Git.

## Choosing checks for a project area

- When a user names a domain or workload, inspect `alphus --catalog --json` and the selected repository's configured profiles (`alphus --plan --json`). Use `docs/REVIEW-CHECKS.md` for detailed behavior and limits; use `docs/CONSUMER-PROFILES.md` and examples for native tools and profile composition.
- Treat `domains` in the catalog as advisory relevance tags. Check `applies_to`, the target repository's languages and dependencies, policy requirements, and the check's documented limits before recommending it.
- Normalize broad or multilingual wording to a catalog tag only when repository evidence supports the mapping (for example, `earth` to `earth-science` or `trajectoires` to `trajectory-analysis`); state uncertain mappings.
- Suggest a consumer-owned profile or TOML change with a short rationale. Do not silently enable a check or change a default profile. Distinguish available checks from missing domain-specific coverage instead of implying that a nearby generic rule validates domain semantics.
- When adding a built-in rule, give its `RuleSpec` a precise summary, supported applicability labels, and only justified domain tags. Keep the catalog completeness check passing and update the rule's detailed documentation and an example policy.

# YAML consumer profile

Select the YAML bundle with `languages = ["yaml"]` or run
`alphus --init-config yaml`. It adds one read-only `yamllint -- {files}` command
for Git-tracked and non-ignored untracked `.yaml` and `.yml` files. Install and
pin `yamllint` in the consumer's development or CI dependencies; Alphus does
not install it or fetch packages when checks run.

yamllint parses syntax and token streams; it does not construct YAML objects,
invoke tag constructors, or execute document content. The bundle has no
auto-fixer.

The adjacent `.yamllint` is a consumer-owned example. It treats syntax and
duplicate keys as errors, reports legacy truthy spellings and leading-zero
octal-looking numbers as warnings, and leaves style rules disabled. It accepts
`True` and `TRUE` as boolean spellings. Tune `allowed-values` and rule levels
to the parser and compatibility requirements of the consuming application.
The example's `ignore` entries skip `generated/` and `vendor/`; Alphus itself
still uses its normal Git-aware inventory. To filter paths before invocation,
replace the shortcut with an explicit command step and its regular file
inventory:

```toml
schema_version = 1

[[orchestration.steps]]
kind = "command"
name = "YAML lint"
argv = ["yamllint", "--", "{files}"]
files.include = ["**/*.yaml", "**/*.yml"]
files.exclude = ["**/generated/**", "**/vendor/**"]

[[orchestration.profiles]]
name = "yaml"
steps = ["YAML lint"]

[[orchestration.profiles]]
name = "check"
steps = ["YAML lint"]
```

The recipe keeps yamllint's raw diagnostics, rule IDs, locations, and per-step
exit code in the standard Alphus profile report. The overall status follows
Alphus's normal aggregation. A missing executable is a command launch failure;
if no YAML files match, Alphus reports `not_applicable`. The recipe does not
auto-fix files.

This bundle checks YAML syntax and configured lint rules, not Kubernetes,
Ansible, or another application's schema and runtime behavior. Kubernetes
Services without selectors can be valid when manually paired with
EndpointSlices, so a generic YAML rule must not reject them. A future
Kubernetes schema integration (such as kubeconform) and a future Ansible
integration (such as ansible-lint) are separate slices.

YAML dialect and consumer parser matter. Under YAML 1.2's core schema,
`true`, `True`, and `TRUE` are boolean spellings, and an untagged integer such
as `010` is decimal. In yamllint 1.38.0, `truthy` honors a `%YAML 1.2`
directive, while `octal-values` checks the plain scalar's token spelling and
warns on `010` even under that directive. That warning is configurable; it
does not mean `010` is octal under YAML 1.2. Disable or adjust the rule if this
warning is unsuitable for the consumer's YAML dialect. Quoting the value
avoids the token-pattern warning. Neither rule proves how every consumer
parser resolves values. YAML 1.1 truthy words such as `yes` and `on` have
different semantics. See the [YAML 1.2.2 core schema](https://yaml.org/spec/1.2.2/#1032-tag-resolution),
[yamllint rule documentation](https://yamllint.readthedocs.io/en/v1.38.0/rules.html#truthy),
and [yamllint 1.38.0's octal rule implementation](https://github.com/adrienverge/yamllint/blob/v1.38.0/yamllint/rules/octal_values.py).

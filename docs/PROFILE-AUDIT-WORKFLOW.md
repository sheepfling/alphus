# Review a requested profile audit

Use this workflow when an agent or reviewer is asked to inspect a defined set
of checks. A successful default profile only says that its configured steps
completed under their policies; it does not establish that optional checks
requested by the audit were selected.

## Declare the request before running

Create a temporary policy copy (for example, `.quality-audit.toml`) and keep
the checked-in policy unchanged. In the temporary policy, compose or add a
named profile that selects every requested check. Record the requested
selectors and subfeatures in the review notes, including checks that require a
specific native rule, script inventory, or `Alphus` rule path. Do not enable
every optional rule by default: a threshold, tool, or domain choice without an
existing documented default needs an explicit decision from the policy owner.

## Inspect scope, then execute

Save the resolved plan before running tools:

```sh
alphus --root . --config .quality-audit.toml --profile audit --plan --json > audit-plan.json
```

Review the plan against the declared request. Confirm each requested check is
selected, inspect native rule selection and effective configuration, and verify
the included and excluded files for each scoped step. Add scripts explicitly
when they belong to the request. A selected aggregate rule does not prove that
an optional subfeature ran; inspect its per-intent binding or native rule
selection.

Write a caller-owned JSON manifest declaring the required steps and their
exact expected inventory. Use `null` only for an intentionally unscoped step;
use an empty list when an empty selected inventory is the expectation. When a
semantic intent is explicitly configured, include all three selector fields
so Alphus can check that exact binding. For a native command selector, use
`required_argv` to require exact tokens in the resolved command line:

```json
{
  "format": "alphus.audit-manifest",
  "schema_version": 1,
  "profile": "audit",
  "checks": [
    {
      "check_id": "python-source-review",
      "step": "Python source review",
      "expected_files": ["src/example.py"],
      "required_argv": ["--select=ANN"]
    }
  ]
}
```

Execute the same profile with the manifest and retain the structured result:

```sh
alphus --root . --config .quality-audit.toml --profile audit --json \
  --audit-manifest audit-manifest.json > audit-result.json
```

Keep the process exit status, configuration identity, source revision, plan,
manifest, result, and any available native-tool output together. The result's
`audit_completion` assesses each declared step, exact selected file list, and
optional semantic intent against the resolved plan and execution report. A
requested item absent from the plan is `not_selected`; a different inventory
is `scope_mismatch`; disabled, unsupported, empty-inventory, unexecuted, and
execution-failure outcomes remain incomplete. An incomplete assessment returns
operational exit code 2 while preserving the profile's own `exit_code` field.

## Assess coverage separately from findings and exit policy

For executed built-in rules, the assessment distinguishes `executed_zero` from
`executed_with_findings`. For opaque native command steps, a successful process
without structured finding evidence is `executed` with `findings_state` set to
`unknown`; a `passed` intent is not treated as proof of zero findings. A
completed audit can still report findings and retain the normal profile
severity/provisional exit behavior. The audit assessment is a separate field.
Missing policy and other preflight failures attach an incomplete assessment to
the versioned execution-failure envelope rather than representing clean
coverage.

The manifest verifies only the declarations it contains. Reviewers must still
ensure it fully represents the request, including native rule selection,
scripts, and relevant subfeatures. Do not describe a successful profile or
aggregate exit code as comprehensive coverage when the manifest itself is
incomplete.

## Assess findings against the project

Coverage and findings answer different questions. For every emitted finding,
read the diagnostic's concise message and any rule guidance linked by the
catalog. If no link is available, inspect the owning check's documentation and
the relevant project context, such as its `AGENTS.md`, design decisions,
supported-runtime policy, or build constraints. Do not treat the finding as an
instruction to change code without that review.

Recommend a correction when the check's evidence and project constraints
support it. When the current code is intentional, record the concrete reason
and the evidence for an exception. When the rule misreads the project or its
limits, capture that as a rule gap with a reproduction and the missing context.
Do not chase a zero-finding report as a goal, and do not write or inject a
project `AGENTS.md`; project instructions remain user-owned.

The 0.0.3 registry does not yet expose a rule-guidance link for every finding.
Until that field is implemented, reviewers can use the selector inventory to
locate its owning feature documentation. The workflow above is review guidance;
it does not automatically edit project instructions or alter check selection.

When blocked by missing policy, unavailable tools, or unresolved scope, name
the exact requirement and work completed. Do not silently add tools, persist
the temporary policy, change consumer CI, or invent severity thresholds.

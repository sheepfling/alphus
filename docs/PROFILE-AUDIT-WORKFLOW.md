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

Execute the same profile and retain its structured result:

```sh
alphus --root . --config .quality-audit.toml --profile audit --json > audit-result.json
```

Keep the process exit status, configuration identity, source revision, plan,
result, and any available native-tool output together. A nonzero exit can
still produce a useful partial report; preserve it and report the failure
rather than treating it as a completed audit.

## Assess coverage separately from findings and exit policy

Compare every declared request item with the plan and result. Report each as
selected and executed, intentionally omitted, unselected, disabled, unsupported,
not applicable because its inventory was empty, or failed before completion.
For an executed check, inspect its finding payload and counts to distinguish
findings from executed zero. A `passed` intent means its configured failure
policy passed; it does not by itself mean there were no findings. A missing
policy is a configuration failure and cannot be reported as zero findings.

The result records configured step and intent outcomes, but Alphus does not
currently accept an external audit manifest or compute a completion judgment
against one. The reviewer must keep the requested-check list with the saved
plan/result and explicitly identify any mismatch. Do not describe a successful
profile or aggregate exit code as comprehensive coverage when that comparison
has not been made.

When blocked by missing policy, unavailable tools, or unresolved scope, name
the exact requirement and work completed. Do not silently add tools, persist
the temporary policy, change consumer CI, or invent severity thresholds.

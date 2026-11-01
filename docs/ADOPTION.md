# Adopting and operating Alphus

Use this guide to add Alphus to a repository that already has tools, scripts,
and CI. Alphus coordinates selected checks; it does not discover every check a
repository ought to run. Keep the existing workflow as the starting point and
make the selected policy explicit.

## Bootstrap from the workflow you have

1. Inventory the repository's languages, package manifests, native tool
   configuration, existing check commands, and CI jobs. Keep checks that
   already work; avoid adding a second owner for the same kind of finding.
2. Choose the closest [consumer profile example](CONSUMER-PROFILES.md#profiles-by-consumer-type).
   A Python project can start with
   [`examples/python/quality-gates.toml`](../examples/python/quality-gates.toml);
   a mixed-language project can start with
   [`examples/polyglot/quality-gates.toml`](../examples/polyglot/quality-gates.toml).
3. Copy or adapt the policy as `quality-gates.toml` at the repository root.
   Select only languages and tools the repository uses. Install and pin those
   tools in its development and CI dependency setup.
4. Preview the selected default profile, then run it:

   ```sh
   alphus --plan --profile check --json
   alphus --profile check
   ```

   `--plan` validates the policy and shows the resolved profile without running
   checks. It does not install or verify native tools, and a valid plan does not
   prove that the repository selected every useful check.
5. Connect the same named profile to CI. Start with the existing
   [quality action](../ci/quality/action.yml) for GitHub Actions, or invoke
   `alphus --root "$PWD" --config quality-gates.toml --profile check` from the
   repository's existing CI job.

For a local source checkout, the Python bundle can be installed with
`python -m pip install -e "/path/to/alphus[python]"`. For shared CI, pin the
Alphus action or Git dependency to a reviewed commit. Keep consumer tool
versions in the repository's existing lockfile or verification requirements.

## Know what each setting controls

There are three distinct configuration owners:

- **Alphus selection and orchestration** live in `quality-gates.toml`:
  selected tools and built-in rules, profile membership, file scope, execution
  order, rollout, severity, and failure threshold.
- **Alphus built-in rule settings** live in `[checks.<rule>]` sections in that
  TOML file. A selected built-in rule needs its policy section and, where
  required, a top-level `[files]` inventory. The optional
  [review sniffers](REVIEW-CHECKS.md) are not activated just because the
  repository contains Python files; select their steps in a profile.
- **Native tool behavior** belongs in the tool's own config and dependency
  setup. For example, Ruff rules stay in Ruff configuration, and Markdown
  policy stays with rumdl or mdrepo. Alphus invokes those tools and combines
  their results. See [subtool ownership](SUBTOOLS.md).

For common languages, `languages = [...]` selects standard bundles. Use
`tools = [...]` for a smaller selection or a specific opt-in tool. The bundle
list and its current contents are in the
[consumer profile guide](CONSUMER-PROFILES.md#start-with-one-file). Do not
select every available bundle by default: inspect the manifests and current
CI first, then add the checks that match the repository.

For an Alphus sniffer, follow its selector-specific section in
[Review checks](REVIEW-CHECKS.md). Add the corresponding `[checks.<rule>]`
settings and a `kind = "rule"` step to a profile. Add that step to `check` when
it should run on the main acceptance path. A separate `review` profile is
useful while evaluating advisory rules.

## Tune failure levels and rollout

Alphus has two independent controls. **Severity** classifies an individual
Alphus finding as `error`, `warning`, or `info`; the profile's
`failure_threshold` decides which severities fail the profile. **Rollout**
decides whether a step's failure blocks the profile at all.

| Setting | Effect |
| --- | --- |
| `failure_threshold = "error"` | Errors fail; warnings and info are reported. This is the default. |
| `failure_threshold = "warning"` | Errors and warnings fail. |
| `failure_threshold = "info"` | Every finding fails. |
| `severity = "warning"` on a rule step | Classifies all findings from that Alphus rule as warnings. |
| `rollout = "provisional"` on a step | Runs and reports the step, but its failure does not fail the aggregate profile. |
| `rollout = "mainline"` | The step participates in the aggregate result. This is the default. |

In a complete policy with the sniffer settings and a profile that selects this
step, the rollout portion can look like this:

```toml
[orchestration]
failure_threshold = "error"

[[orchestration.steps]]
kind = "rule"
name = "Pydantic review"
rule = "pydantic-practices"
severity = "warning"
rollout = "provisional"
```

Provisional steps still run and their findings or command failures remain in
the report. Promote a step to `mainline` after reviewing its scope and output.
Changing severity does not make a provisional step blocking, and changing the
threshold does not promote one. For a mainline native command, a nonzero tool
exit still fails the profile regardless of finding severity. These settings
change how results affect the profile; they do not change what a rule detects.
Use that rule's own options or the native tool's configuration to adjust
detection and file scope. Alphus does not infer finding severity from arbitrary
native-tool output.

## Audit the effective policy

Use the plan as an execution audit, then compare it with repository intent:

```sh
alphus --plan --profile check --json
git diff -- quality-gates.toml
```

In the plan, inspect the selected profile and included profiles, the failure
threshold, every step's `kind`, `rule` or command, `rollout`, and any rule
`severity`. For file-scoped commands, inspect `selected_files` and
`applicable`; an empty scope is not a passing check. Inspect command arguments
as well as names, because a step can keep its name while its executable,
arguments, or file selection changes.

Then compare the plan with the repository's package manifests, native configs,
scripts, and CI jobs. Confirm that expected existing checks still appear, that
newly relevant languages and test commands are covered, and that excludes are
narrow. `--plan` shows what the policy enables; it cannot identify an omitted
tool or detect that a broad exclusion conflicts with your intent. Alphus does
not currently have a universal policy-completeness audit or a protected list of
required checks. Keep the expected `check` profile in version control and have
policy changes reviewed with the same care as CI workflow changes. If the
repository uses branch protections or CODEOWNERS, require maintainer review for
changes to the Alphus policy and quality workflows.

When reviewing an agent's changes, pay particular attention to changes that
remove steps or profiles, add or widen exclusions, reduce file scopes, change
`mainline` to `provisional`, lower a rule's severity, relax the failure
threshold (for example, from `warning` to `error`), alter native tool
configuration, or remove a dependency. Require a concrete reason for each such
change. A green run after one of those changes does not by itself show that the
original gate still ran.

## Handle false positives

First check whether the finding is outside the rule's documented scope or is a
real issue with an acceptable fix. If the rule is wrong for a broader class of
valid code, report a small reproducer and correct the rule so the fix benefits
other consumers. If the code is a legitimate repository-specific exception,
prefer a narrow rule-level `exclude` or the native tool's own documented
suppression. Put the reason beside the exception in the checked-in config and
keep unrelated files covered.

Avoid disabling the whole rule, suppressing a whole directory, or lowering the
profile threshold to clear one finding. Those changes hide unrelated findings.
If a new check is too noisy to block while its behavior is evaluated, keep it
`provisional` and review the reports before promotion. Alphus has no single
cross-tool inline suppression or universal finding-baseline format; use the
mechanism owned by the rule or native tool. The
[sniffer guide](REVIEW-CHECKS.md) documents their known limits and selectors.

## Give coding agents a policy contract

Add a short project-specific instruction to the repository's `AGENTS.md` (or
equivalent) and make the expected acceptance profile explicit. For example:

> Before changing quality policy, inspect package manifests, existing native
> configuration, CI commands, and `alphus --plan --profile check --json`.
> Preserve relevant checks already used by the repository. Do not weaken a
> check to make a code change pass: do not remove steps, widen exclusions,
> shrink file scopes, change mainline steps to provisional, lower a rule's
> severity, relax the failure threshold, or alter native tool rules without an
> explicit, reviewed reason.
> For a suspected false positive, provide the rule ID, file and line, the
> relevant rule documentation, and a reproducer. Propose the narrowest rule
> fix or exception, and report the effective plan and profile result.

This makes the agent compare a proposed policy with the existing workflow
instead of guessing from source extensions. It is a review instruction, not a
technical lock: CI branch protections and human review remain the enforcement
boundary for policy changes.

## Run in CI

For GitHub Actions, the reusable action installs the pinned Alphus revision
and the consumer's verification requirements, then runs one explicit profile:

```yaml
- uses: sheepfling/alphus/ci/quality@<REVIEWED_ALPHUS_SHA>
  with:
    requirements-file: requirements-quality.txt
    config-file: quality-gates.toml
    profile: check
```

Pin the action to an immutable reviewed commit and keep the selected native
tools in `requirements-quality.txt` or the repository's established tool
installation path. The same command can run locally and in other CI systems:

```sh
alphus --root "$PWD" --config quality-gates.toml --profile check
```

Use the same configuration and profile locally and in CI so the command is
reproducible. Add a separate `--plan --json` step when you want its resolved
selection and file scopes as reviewable CI output; the plan does not replace
the profile run. The
[quality action](../ci/quality/action.yml) documents its install inputs, and
[consumer profiles](CONSUMER-PROFILES.md#one-pinned-local-and-hosted-entrypoint)
cover profile composition and other CI arrangements.

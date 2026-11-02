# Profile reports and adoption exports

Use `--json` to send a profile result to stdout. A completed result separates
execution status and exit codes from findings, severity counts, the profile's
`failure_threshold`, and each step's `rollout`. A step keeps the raw child exit
in `exit_code`, even when its provisional rollout leaves the aggregate exit
code at 0. Provisional C++ advisory reports likewise keep their `mode`,
`blocking`, and findings separate. These fields describe rollout confidence;
Alphus does not calculate a numeric confidence score.

`--history-dir` archives completed profile results with elapsed, step, and work
unit timings, the source revision, a configuration digest, and the complete
result. It does not record native tool versions or a complete selected and
excluded file inventory. Use `--plan --json` to inspect resolved profile steps
and file selections before running. Archive the effective policy and any
referenced fragments alongside that plan; their include and exclude patterns
explain configured scope. Some repository-wide commands do not report a
resolved file list.

## Export recipe

This example stores the plan, profile result, history, source identity, and
interpreter version as separate CI artifacts. Add one version command for
every selected native tool using that tool's supported version option. The
three sample native commands assume the profile selects the standard Python
bundle; remove or add commands to match `plan.json`.

```sh
set -eu
: "${ALPHUS_ARTIFACT_DIR:?set the CI artifact directory outside the checkout}"
artifacts="$ALPHUS_ARTIFACT_DIR"
mkdir -p "$artifacts"

git rev-parse HEAD > "$artifacts/source-revision.txt"
git status --porcelain > "$artifacts/worktree-status.txt"
cp quality-gates.toml "$artifacts/quality-gates.toml"
python --version > "$artifacts/python-version.txt" 2>&1
python -m pip show alphus > "$artifacts/alphus-package.txt"
set +e
alphus --root . --config quality-gates.toml --profile check --plan --json \
  > "$artifacts/plan.json" 2> "$artifacts/plan-stderr.txt"
plan_exit=$?
set -e
printf '%s\n' "$plan_exit" > "$artifacts/plan-exit-code.txt"
# For each selected tool, capture its supported version command as well.
ruff --version > "$artifacts/ruff-version.txt" 2>&1
pyright --version > "$artifacts/pyright-version.txt" 2>&1
pytest --version > "$artifacts/pytest-version.txt" 2>&1

set +e
alphus --root . --config quality-gates.toml --profile check --json \
  --history-dir "$artifacts/history" --consumer-id team/repository \
  > "$artifacts/profile.json" 2> "$artifacts/stderr.txt"
profile_exit=$?
set -e
printf '%s\n' "$profile_exit" > "$artifacts/process-exit-code.txt"
```

Keep every policy fragment referenced by `orchestration_files` with the
artifact. Record versions for the native commands selected by the plan, plus
the Alphus installation or pinned source revision. A small consumer-side JSON
manifest can point to those files:

```json
{
  "source_revision": "source-revision.txt",
  "worktree_status": "worktree-status.txt",
  "effective_configuration": ["quality-gates.toml"],
  "selected_and_excluded_scope": "plan.json and the archived policy files",
  "interpreter_version": "python-version.txt",
  "alphus_installation": "alphus-package.txt",
  "native_tool_versions": {
    "ruff": "ruff-version.txt",
    "pyright": "pyright-version.txt",
    "pytest": "pytest-version.txt"
  },
  "timings": "history/*.json when a completed history record exists",
  "artifact_paths": [
    "plan.json",
    "plan-stderr.txt",
    "profile.json",
    "stderr.txt",
    "history/"
  ],
  "unavailable": []
}
```

Populate `native_tool_versions` for the tools in the selected profile. Put
missing values in `unavailable` instead of inferring them. A run that fails
before orchestration has no history timings; its JSON output says the evidence
is incomplete. If plan generation fails, `plan.json` may be empty; retain its
stderr and mark selected scope unavailable. The `process-exit-code.txt` records
the command's actual exit status independently of its JSON payload.

## Early failures

With `--json`, profile configuration and profile-resolution errors that occur
before orchestration emit a versioned `alphus.execution-failure` object. It
contains `execution_failure`, an empty `findings` array, explicit `null`
confidence and enforcement values, `raw_child_exit: null`, and
`evidence_complete: false`. This is not a completed clean profile result.
Completed profile JSON and profile-history schemas are unchanged. The versioned
failure object is also written to the requested `--output` path when the C++
advisory command fails before producing its report. C++ argument-parser usage
errors retain argparse's standard usage output. A C++ advisory failure writes
JSON to redirected stdout or to `--output`; on an interactive terminal without
`--output`, it keeps the error concise on stderr.

Capture stdout directly when an early failure must be retained, as in the
recipe above. C++ advisory commands also write early failure envelopes to their
`--output` artifact path. Their normal advisory report schema and provisional
exit behavior remain unchanged.

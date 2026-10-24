# Parallel quality execution

Alphus sends every profile step through one measured work-unit runner. Profiles
run serially unless a consumer opts into process concurrency. The profile
retains its declared step order for reporting and exit status. A bounded
scheduler starts independent work and buffers each result until it is reported
in profile order. Direct built-in rule checks use the same runner with one
work unit; backend-aware rules can expand into several units when enabled.

## Configure a worker budget

Add a worker budget to the root policy and mark reviewed check steps as safe to
overlap:

```toml
[orchestration.execution]
max_jobs = 4

[[orchestration.steps]]
kind = "command"
name = "Python lint"
argv = ["{python}", "-m", "ruff", "check", "."]
parallel = true
slots = 1
locks = ["ruff-cache"]
dispatch_priority = 20
```

`max_jobs` defaults to `1` and accepts values from 1 through 64. `--jobs N`
overrides it for one run or plan; `--jobs 1` gives the serial baseline. A step
defaults to `parallel = false`. Such a step waits for all previous work and
finishes before later work starts. Consecutive `parallel = true` steps form a
block that shares one budget. Native command steps remain project-owned, and
fix commands always run in their configured order. Serial built-in rules use
the in-process rule callback through the runner; opted-in rules use isolated
Python workers.

Each work unit uses one slot by default. `slots` lets a consumer reserve more
of the budget for a native tool that starts its own workers. `locks` are
exclusive resource names; units sharing a lock cannot overlap. Use them for
shared caches, generated files, and report destinations. Alphus does not infer
whether an arbitrary command reads or writes those resources. Explicitly
classify commands before enabling concurrency.

Set `dispatch_priority` from -100 through 100 to start more urgent eligible
units first. A larger number starts sooner; ties retain the declared step
order. Priority never bypasses `after`, locks, or the worker budget. It only
changes dispatch order inside a parallel block, not the order of results.
`priority` on a rule step remains the separate finding-remediation field.

`after = ["Other step"]` delays a step until the named step completes. The
dependency must be selected earlier in every profile that contains the step.
It is an ordering dependency: a failed predecessor does not suppress later
checks. An optional `timeout_seconds` applies to each launched work unit.

Run `alphus --plan --jobs 4` to inspect the effective budget and each step's
mode, slots, locks, and ordering dependencies. Existing serial profile JSON
keeps its result shape; concurrent runs still emit steps and captured output in
profile order.

## Built-in rules and metric backends

An opted-in built-in rule runs in an isolated Python process using the same
rule evaluation as a serial profile. `cyclomatic-complexity` expands into one
unit per configured Ruff, ESLint, or Lizard backend. Those units share the
profile's worker budget with neighboring parallel steps. A direct
`--rule cyclomatic-complexity --jobs N` invocation uses that same scheduler.
Other built-in rules remain one unit each; Alphus does not divide a rule's file
inventory without a rule-specific merge and coverage contract.

Missing tools, malformed worker responses, timeouts, and backend coverage
failures remain operational failures. The scheduler continues independent work
and reduces findings in the same order as a serial run. The installed Alphus
package supplies the Python worker; consumers still install the native tools
selected by their policy.

## Record results and prioritize earlier failures

Alphus already includes total counts, per-step status, findings, and captured
output in `--json` profile results. To keep those results across runs, pass
`--history-dir PATH` or set `ALPHUS_PROFILE_HISTORY_DIR`. Each completed run
then appends one immutable JSON record under `PATH/profiles/YYYY/MM/` and prints
its path to stderr. The archive includes the complete profile result, a digest,
the source checkout, policy fingerprint, timestamps, wall time for each step,
and execution time for each work unit. It also records the VCS kind, branch or
path, and revision when available.
Set `--consumer-id ID` (or `ALPHUS_CONSUMER_ID`) when saving runs from CI or
multiple worktrees. Use a stable, user-chosen identity such as
`sheepfling/alphus`; the absolute checkout path is still recorded for
provenance. New records use schema version 3 with a digest covering the timing
and provenance envelope as well as the embedded result. Existing version 1
and 2 records remain readable and group by their recorded checkout path when
they have no consumer identity. Version 2 records carry a consumer identity
but do not identify which VCS supplied their Git-oriented branch and revision.
Profile history probes Git and then local Subversion metadata. A missing VCS
or unavailable command leaves those provenance fields null; it does not stop
the run or prevent the archive from being written. Python consumers can pass
a `VersionControlProvider` to `run_orchestration` for another system. VCS
specific gates still require their own backend when selected.
For a rule split across native backends, its step wall time covers the first
backend start through the last backend finish; individual unit times may
overlap. Ordinary runs remain read-only unless history is enabled.

```sh
alphus --profile check --jobs 4 --history-dir /path/to/alphus-history --consumer-id sheepfling/alphus
alphus --profile check --show-history --history-dir /path/to/alphus-history
alphus --profile check --show-history --history-dir /path/to/alphus-history --json
alphus --history-report runs --history-dir /path/to/alphus-history --json
alphus --history-report rollup --history-dir /path/to/alphus-history --json
```

`--show-history` prints the latest total and outcome counts plus failed step
names without rerunning gates. Add `--json` to read the complete saved record.
`--history-report runs` returns compact, newest-first rows with paths to the
complete records. `--history-report rollup` returns run failure counts and
timing statistics for runs, steps, and work units. Both reports accept
`--profile NAME` and `--consumer-id ID` filters, and emit a single JSON value
with `--json`. Rollups keep different consumer identities, profiles, and
policy fingerprints separate. They include sample counts because steps and
work units may change between runs. The p95 is the nearest-rank sample;
individual unit durations can overlap and must not be summed as wall time.

Python consumers can call `read_profile_record(path)` to validate one record,
`iter_profile_records(history_dir, ...)` to stream the archive, and
`rollup_profile_history(entries)` to calculate the same report. The reader
rejects unknown schema versions, malformed records, and result digest
mismatches rather than silently dropping them. These reports cover profile
archives; standalone C++ report history uses its own archive and trend API.
To analyze records produced by separate CI jobs or consumers, collect their
`profiles/YYYY/MM/*.json` files under one history directory before running
the CLI report. Python callers can also combine iterators from separate
archives and pass them to `rollup_profile_history`.

To start steps that failed in the previous comparable run first, configure:

```toml
[orchestration.execution]
max_jobs = 4
prioritize_previous_failures = true
```

That setting requires a history directory. A prior result is comparable when
the resolved checkout, consumer identity, profile, and validated policy
fingerprint match. Previously failed steps rank ahead of other eligible
steps; configured `dispatch_priority` then breaks ties. Reporting remains in
profile order.

The worker protocol and saved records use versioned JSON. JSON matches the
existing profile output and the repository's C++ report archives, and each
archive is written atomically by the coordinator. No database is needed for
one writer per profile run. CI must retain the directory as an artifact if
later jobs should use its history or analyze runs over time.

# Parallel quality execution

Alphus runs profiles serially unless a consumer opts into process concurrency.
The profile retains its declared step order for reporting and exit status. A
bounded scheduler starts independent work in child processes and buffers each
result until it is reported in profile order.

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
```

`max_jobs` defaults to `1` and accepts values from 1 through 64. `--jobs N`
overrides it for one run or plan; `--jobs 1` gives the serial baseline. A step
defaults to `parallel = false`. Such a step waits for all previous work and
finishes before later work starts. Consecutive `parallel = true` steps form a
block that shares one budget. Native command steps remain project-owned, and
fix commands always run in their configured order.

Each work unit uses one slot by default. `slots` lets a consumer reserve more
of the budget for a native tool that starts its own workers. `locks` are
exclusive resource names; units sharing a lock cannot overlap. Use them for
shared caches, generated files, and report destinations. Alphus does not infer
whether an arbitrary command reads or writes those resources. Explicitly
classify commands before enabling concurrency.

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

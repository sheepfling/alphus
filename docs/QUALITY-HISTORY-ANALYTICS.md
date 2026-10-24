# Analyze quality gates across repositories

Keep each consumer's `--history-dir` as the durable record of its runs. A
completed profile appends one immutable JSON document with its complete
result, timings, provenance, and integrity digests. Retain those archives as
CI artifacts or in an archival store; a local SQL database is a rebuildable
index, not the authoritative copy.
The self-check matrix uploads each Python version's archive as a separate
GitHub Actions artifact for 90 days. Copy records to longer-lived storage if
the analysis horizon extends beyond artifact retention.

New profile records use schema version 4. Their gate manifest assigns built-in
rules an `alphus/rule/<rule>` identity independent of the display step name.
Commands need an explicit `gate_id` to be comparable across repositories:

```toml
[[orchestration.steps]]
kind = "command"
name = "Python lint"
gate_id = "team/python-lint"
argv = ["{python}", "-m", "ruff", "check", "."]
```

Pick an ID only when the commands have the same purpose. The index also stores
a digest of each gate's relevant rule policy or command definition. A policy
change makes a separate rollup cohort even if the gate ID stays the same.
The digest cannot establish that separate consumers installed the same native
tool version; record and filter those versions in the consumer's own evidence
when that distinction matters.
Unidentified commands and older version 1–3 records remain readable but are
counted as unmapped gate observations. An importer will not guess that two
steps with the same display name are the same gate.

## Build and query the index

Install Alphus normally, then supply any number of independent archives:

```sh
alphus-history ingest --database /path/to/quality.sqlite \
  --archive /ci/history/repo-a --archive /ci/history/repo-b
alphus-history rollup --database /path/to/quality.sqlite
alphus-history rollup --database /path/to/quality.sqlite \
  --profile check --gate-id alphus/rule/line-length
alphus-history runs --database /path/to/quality.sqlite --limit 100
alphus-history gates --database /path/to/quality.sqlite --status failed
```

Both commands print versioned JSON. Repeating `ingest` is safe: record IDs and
canonical record digests detect duplicates and conflicting evidence. Each
record and its normalized gate, finding, and work-unit rows are inserted in
one transaction. Malformed records fail the import and can be repaired in the
source archive before retrying. To rebuild from scratch, remove the derived
database and ingest the retained archives again. Index schema changes require
a rebuild. Python integrations can call `open_index`, `ingest_archives`, and
`portfolio_rollup`, `list_index_runs`, and `list_gate_observations` from
`alphus.execution.history_index`. The `runs` and `gates` commands support
`--offset` and `--limit` for paged triage; gate rows include a path to the
complete archive record.

The portfolio report counts all selected runs in the requested consumer and
profile scope, then groups mapped gates by `(gate_id, gate_policy_sha256)`.
Each gate group reports selected runs, runs where that gate ID was absent,
and runs with that ID under another policy. It also reports every status,
attempted executions, attempted failure rate, and timing sample count. Timing
statistics use only attempted gates with an actual duration, so skipped gates
do not appear as zero-second checks. The p95 is the nearest-rank sample. A
gate can appear more than once in a run, so `observations` and status counts
may exceed `selected_runs`. Findings are summarized by rule ID and severity;
the complete finding and native report remain in the JSON archive.

The SQL tables are also queryable directly with SQLAlchemy or SQLite when a
team needs per-run triage. `runs.archive_path` points back to the verified
record; `gates`, `findings`, and `work_units` hold common fields. A work unit's
duration can overlap another unit's duration and must not be added to compute
wall time. `work_units.step_name` is populated for version 4 records.

The portfolio query does not infer equivalence between different profiles or
different gate policies. Filter to the cohort relevant to a decision, and use
the full archive when native gate reports need further normalization. Git,
Subversion, and caller-supplied VCS identities remain provenance only; they
are not needed to index a run.

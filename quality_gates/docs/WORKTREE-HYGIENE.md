# Worktree hygiene

Worktrees are useful for parallel changes, but each checkout can accumulate
ignored build products. A clean `git status` only describes tracked and
untracked, nonignored files. It does not prove that the checkout is small or
that its detached commit is already preserved on the primary branch.

## Inventory and budget

Run the read-only inventory from the primary checkout:

```shell
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)
python -m alphus.gates.vcs.worktree_hygiene --repo . --base-ref HEAD --max-worktrees 16 --max-logical-gib 100 --run-id $RUN_ID --output out/build-metrics/worktree-hygiene.json
```

Add every dedicated worktree storage root to include folders no longer
registered with Git. For example, use `--scan-root "agent=$agentWorktreeRoot"`
and set `--max-unregistered 0` when all unexplained folders need review. A
configured scan root that does not exist is an error, so a mistyped location
cannot silently pass. Without scan roots, the report covers registered
worktrees only.

The tool reports registered secondary worktrees, clean or dirty Git status,
whether each HEAD is an ancestor of the chosen base, logical file bytes and
largest top-level directories (including ignored outputs), unreadable
checkouts, and directories under any supplied scan roots that are not registered
to the inspected repository. Such a folder may belong to another repository;
check ownership before acting. All folders outside known checkout paths under
dedicated scan roots count toward the
worktree count, and their contents count toward the logical byte total. Labels
and locations are consumer configuration; the checker has no built-in agent or
project paths. It exits with failure when a budget is exceeded or inspection
is incomplete. Use `--skip-size` for a fast count audit; a byte budget requires
size measurement. Set a workstation-specific
count and size budget, then run this audit at the end of a work stream and
periodically on the development machine. This is a local workspace gate, not a
CI runner gate.

Logical bytes are file lengths, not allocated disk blocks. Compression,
hard links, and other sharing can make actual disk use different. The base-ref
check is also only a signal: an unreachable commit may be valuable, while a
reachable commit does not account for ignored outputs or an app session that
still owns the worktree. Never remove a checkout from this report alone.

## Closeout by owner

1. Identify the task or session that owns the worktree. Check its Git status,
   untracked files, ignored build products, branch or detached HEAD, and any
   commits absent from the primary branch. Preserve needed source and ignored
   artifacts before cleanup.
2. For an app-managed worktree, use the owning app's archive action. Preserve
   needed ignored files separately, because they may be excluded from the
   app's snapshot. Do not remove the checkout through a second tool while its
   owner still tracks it.
3. For a manually created worktree, preserve unique commits and artifacts,
   confirm no active task uses it, then use `git worktree remove <path>` from
   the primary repository. `git worktree prune` removes stale Git registration
   records after the filesystem state is resolved; it is not a substitute for
   reviewing a checkout. Never delete a registered worktree directory directly.

New work streams should reuse the current checkout unless isolation is needed.
Record the owner and intended closeout when a new worktree is created. If the
worktree must remain at handoff, record its path and the reason instead of
leaving an unexplained directory.

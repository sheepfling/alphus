# Git repository quality gates

Alphus keeps Git-specific gates in `alphus.gates.vcs`. Portable repository
layout, package, and metadata gates stay in `alphus.gates.repository`. This
boundary gives another version-control system its own adapter and rule mapping
without changing the portable rules or the normalized finding contract.
`alphus.support.inventory.FileInventoryBackend` is the file-discovery seam:
its `files(root)` and `tracked(root)` methods return safe repository-relative
paths. Git is the default backend. A future SVN or other adapter can be passed
to `candidate_files(..., backend=...)` and `tracked_files(..., backend=...)`;
its VCS-specific checks belong in `alphus.gates.vcs` rather than in portable
repository rules. The CLI currently selects the Git backend.

| Rule | Reads | Cadence |
| --- | --- | --- |
| `git-ignores` | Effective ignore rules and tracked generated paths | Every change |
| `git-attributes` | Tracked root `.gitattributes` and effective attributes | Every change |
| `git-history` | Reachable refs, blob sizes, and committed names | Monthly or manual |

A consumer can start with one policy and invoke a rule directly:

```toml
schema_version = 1
[checks.git]
attributes = [
  { path = "src/example.py", attribute = "eol", value = "lf" },
]
```

```shell
alphus --rule git-ignores
alphus --rule git-attributes
alphus --rule git-history
```

The fast `git` profile runs ignores and attributes. The separate
`repository-history` profile runs the slower history audit. None of these
rules requires a `[files]` inventory.

The ignore rule detects Python, JavaScript/TypeScript, and C/C++ from tracked
source. To check a language before its source is committed, list it under
`[checks.git]`:

```toml
languages = ["python", "javascript", "cpp"]
```

Common ignore rules cover `.env` and `.pypirc`. Language rules cover Python
virtual environments and caches, JavaScript dependencies and build state, and
C/C++ build outputs. The gate also reports generated paths already tracked;
adding `.gitignore` does not untrack them. A local global ignore can satisfy
the rule, while clean CI confirms repository coverage.

The attributes rule requires the root `.gitattributes` to be tracked. Each
configured row checks the *effective* value for its representative path using
`git check-attr`, including nested attributes. `value = "set"` checks a boolean
attribute such as `text`; `value = "lf"` checks `eol=lf`. Paths can be
representative names that do not exist yet. This keeps the policy small while
checking Git's interpretation rather than reimplementing its pattern grammar.

The history gate defaults to a 5 MiB blob threshold. Set `max_blob_mib` under
`[checks.git]` to change it. It inspects object sizes and generated path names,
not secret contents. A deletion commit does not erase reachable history;
review findings before rewriting shared history.

`.github/workflows/repository-hygiene.yml` runs the fast profile on pull
requests and pushes, and schedules the history profile monthly. Cadence lives
in CI or a scheduler, not in individual rule settings. A local history audit
covers only refs available in that checkout.

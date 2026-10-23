# Git-backed repository quality gates

Git is another Alphus finding source. The repository gate package owns two built-in rules, and they return the same structured findings as source rules:

| Rule | What it reads | Normal cadence |
| --- | --- | --- |
| git-ignores | Effective Git ignore rules and the tracked-file index | Every change |
| git-history | All locally reachable refs, blob sizes, and committed path names | Monthly or manual |

A consumer only needs this policy to run either rule directly:

    schema_version = 1
    [checks.git]

Then run alphus --rule git-ignores or alphus --rule git-history. No [files] inventory or extra console command is required. The self-profile in quality-gates.toml shows optional git and repository-history profiles. Its default check profile includes the fast git profile; the history profile remains separate.

The ignore rule detects Python, JavaScript/TypeScript, and C/C++ from tracked source. To check a language before its source is committed, list it under [checks.git]:

    languages = ["python", "javascript", "cpp"]

Common rules cover .env and .pypirc. Python rules cover virtual environments, caches, distribution output, and Streamlit secrets. JavaScript rules cover node_modules, TypeScript build state, and ESLint cache. C/C++ rules cover CMake and compiler outputs. JSON, TOML, and Markdown have no universal generated artifacts to require; add rules for tool-specific caches only when a tool is introduced.

The ignore gate asks Git whether representative generated paths are effectively ignored. It also reports generated paths already tracked, because adding .gitignore does not untrack them. A local global ignore can satisfy this rule, while clean CI confirms repository coverage. Review a tracked finding before removing it from the index; a deliberately committed fixture may need a narrower rule.

The history gate defaults to a 5 MiB blob threshold. Configure max_blob_mib in [checks.git] when needed. It measures Git objects without reading file content and reports paths matching generated-file patterns, including .env. This is a filename and size audit, not secret-content scanning. Historical findings need human review: a new deletion commit does not erase old objects, and rewriting shared history affects collaborators.

The workflow in .github/workflows/repository-hygiene.yml runs alphus --profile git on pull requests and pushes to main. It runs alphus --profile repository-history on the first day of each month at 04:23 UTC and by manual dispatch, using a full checkout. The scheduled job becomes active after the workflow reaches the default branch. Local history audits include only refs available in that checkout; fetch the refs you intend to inspect first.

Cadence belongs to CI or a scheduler, not individual rule configuration. Keep quick deterministic gates in the ordinary profile. Put more expensive checks in separate nightly, weekly, or monthly profiles as their cost warrants. This avoids adding scheduling fields to quality-gates.toml.

To add another language, add representative generated paths and tracked-file patterns to RULES and extend language detection in src/alphus/gates/repository/git_hygiene.py. Keep rules specific to generated output; source files and lockfiles should remain trackable.

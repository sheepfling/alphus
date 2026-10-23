# Repository hygiene and check cadence

Alphus has two Git hygiene commands. They use no quality-gates.toml settings:

| Command | Scope | When to run |
| --- | --- | --- |
| alphus-git-hygiene ignore | Effective ignore rules and files already tracked in the index | Every pull request and push to main |
| alphus-git-hygiene history | All reachable refs: large blobs and generated-file paths ever committed | Monthly and on demand |

The cadence belongs to CI or a scheduler, not to each rule's configuration. A small, deterministic check should run for each change; slower checks can run nightly or weekly when they become too expensive for pull requests. Checks that traverse all Git history belong on a monthly or manual cadence. This keeps the ordinary Alphus profile fast and avoids adding scheduling fields to quality-gates.toml.

The ignore command detects Python, JavaScript/TypeScript, and C/C++ from tracked source. Select a policy explicitly when preparing a new language area:

    alphus-git-hygiene ignore --languages python javascript cpp

Common rules cover .env. Python rules cover virtual environments, caches, and distribution output. JavaScript rules cover node_modules, TypeScript build state, and ESLint cache. C/C++ rules cover CMake and compiler outputs. JSON, TOML, and Markdown have no generic generated artifacts to require; their tool-specific caches should be added only when a tool is introduced.

The ignore command asks Git whether representative paths are *effectively* ignored. It also checks the index because adding .gitignore does not remove files already tracked. If a generated file is tracked, remove it from the index deliberately after checking whether it is a source fixture. A global ignore may satisfy the local command; CI runs from a clean checkout and checks the repository policy.

The history command uses the default 5 MiB blob threshold:

    alphus-git-hygiene history --max-blob-mib 5

It inspects Git object sizes without reading file content. It reports historical paths matching the same generated-file patterns, including .env. It is a filename and size audit, not secret-content scanning. A history finding needs human review: deleting a file in a new commit does not erase it from history, and rewriting shared history affects collaborators.

The workflow in .github/workflows/repository-hygiene.yml runs the fast command on pull requests and pushes to main. It runs the full-history command on the first day of each month at 04:23 UTC and by manual dispatch. The scheduled job becomes active when that workflow reaches the default branch. It uses a full Git checkout so all branch and tag history is available. For a local audit, fetch the refs you want to include before running history.

To add another language's ignore policy, add representative generated paths and matching tracked-file patterns to RULES in src/alphus/gates/repository/git_hygiene.py, then add language detection and a CLI choice. Keep rules specific to generated output; source files and lockfiles should remain trackable.

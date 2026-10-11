# Alphus architecture

Alphus is a Python package for running policy-driven quality checks
against Git repositories. Each consumer owns its TOML policy. The package
contains reusable policy models, file inventory, checkers, typed findings,
renderers, and command orchestration; it does not define a project's paths,
package graph, thresholds, or default check set.

## Execution model

The caller supplies the repository root and policy path. The Python CLI
validates the policy, selects the requested rule or ordered profile, gathers
the configured file inventory, and combines results into one exit status.
Native language tools retain their own checks and run as configured argument
vectors. Python owns ordering and aggregation without importing compiler,
Java, or Node ecosystems.

Node and npm are optional. A repository that configures no Node-based command
does not need `package.json`, Node.js, or npm. Consumers may keep established
commands in another launcher, such as `npm run check`, while delegating the
actual profile to `alphus`.

## Policy and checker boundaries

Use TOML for consumer-owned file patterns, exclusions, limits, package edges,
and command steps. Validate it into named models before execution. Keep
language semantics in versioned checker code rather than executable snippets
in policy. A command may declare a file inventory and use `{files}` as one
complete argv item; the runner expands that item into separate
repository-relative arguments. Empty scopes pass without starting the command.

Each checker receives an explicit root, validated rule policy, and selected
files. It returns typed findings or a typed report; it does not print, start
processes, or discover a checkout from the current directory or module path.
Module-role policies can name forbidden module-level assignments separately
from functions and classes. The assignment scanner follows module-level
control-flow branches and stops at function, class, and lambda scopes, so a
provider alias cannot hide in a conditional or be confused with a local name.
The CLI owns rendering, subprocess calls, report-only behavior, and exit
status. Use argument arrays for native tools, and keep their working
directories within the configured repository root. Consumers can configure
Markdown link and formatting tools as ordinary command steps without adding
repository-specific code to the package.

For a coordinated consumer example that assigns Markdown graph checks to
mdrepo, Markdown formatting to rumdl, and Python lint, typing, and tests to
their native tools, see [consumer quality profiles](CONSUMER-PROFILES.md).
This keeps upstream rule ownership intact while Alphus aggregates profile
status.

Profiles execute only when explicitly selected with `--run`. Review command
steps before running a policy from a repository that is not trusted, because
those steps execute the configured programs.

## Migration and verification

Migrate one checker at a time. Keep the consumer's command name as an adapter
until the old and new implementations return the same normalized findings for
the same repository snapshot. Do not add baselines or path suppressions just
to hide existing findings.

Keep two verification layers:

- Generic package tests use small temporary Git repositories with no
  consumer-specific names, paths, or package layout. Cover accepted and
  rejected inputs, invalid policy, and stable finding locations.
- Consumer tests verify that its policy selects the intended files and rules,
  its wrappers retain their public commands and output modes, and its
  normalized findings match the previous gate sequence.

Build and install the wheel outside the source checkout, then run it against a
generic fixture. A Python-only profile must work without Node or npm. Native
tool dependencies belong to the consumer's development setup, not to the
`alphus` runtime dependencies.

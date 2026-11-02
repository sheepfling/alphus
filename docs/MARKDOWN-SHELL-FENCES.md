# Markdown shell fence review

`markdown-shell-fences` is an opt-in informational check for shell commands in
Markdown code fences. It reports likely conflicts between a fence label and
strong syntax evidence. It does not run commands, change labels, or join the
default profile. Existing Markdown tools remain responsible for formatting and
repository-link checks; for example, markdownlint's MD040 rule requires a
language label but does not compare the label with the fenced content
([MD040 documentation](https://github.com/DavidAnson/markdownlint/blob/main/doc/md040.md)).

```toml
[checks.markdown_shell_fences]
include = ["docs/**/*.md"]
exclude = ["docs/archive/**"]

[[checks.markdown_shell_fences.suppressions]]
path = "docs/windows.md"
line = 18 # Opening fence line
reason = "This section intentionally contrasts Bash and Windows command forms."

[orchestration]
default_profile = "docs-review"

[[orchestration.steps]]
kind = "rule"
name = "Markdown shell review"
rule = "markdown-shell-fences"
rollout = "provisional"

[[orchestration.profiles]]
name = "docs-review"
steps = ["Markdown shell review"]
```

The default file selection is `**/*.md`; set `include` and `exclude` to match a
repository's documentation layout. A suppression identifies one opening fence
line and requires a reason. Findings point to the evidence line and include the
fence label, evidence, and a request to verify the intended shell. They use
`info` severity, so the default `error` failure threshold keeps this check
advisory. Consumers can set their own rollout and failure threshold.

## Evidence and limits

The checker recognizes Bash-family labels `bash`, `sh`, `zsh`, `dash`, and
`ash`; PowerShell labels `powershell`, `pwsh`, `ps`, and `ps1`; and command
prompt labels `cmd`, `cmd.exe`, `bat`, and `batch`. It reports PowerShell
environment assignments and selected PowerShell commands in Bash fences,
Windows command prompt environment and batch syntax in Bash fences, and clear
Bash `for`/`select`/`while` loop syntax in PowerShell fences. A small set of
unquoted Windows drive paths and `.venv\Scripts\python` executables in Bash
fences are review candidates rather than proof of a shell mismatch.

Fence parsing handles backtick and tilde fences, longer closing markers,
blockquotes, list indentation, and nested Markdown examples. The shell scan
ignores Markdown HTML comments, shell comments, Bash here-documents, quoted
string data, and fences whose first command line looks like an interactive
prompt. Unknown or missing labels are left to Markdown style tools.

This is a syntax-evidence review, not a shell parser. Git Bash, MSYS, and WSL
can accept some Windows-looking paths; project-specific aliases and embedded
shells can also make a mismatch intentional. Conversely, unrecognized syntax
may not be reported. Review each finding with the example's surrounding prose,
then adjust the label only after confirming which shell the author intends.

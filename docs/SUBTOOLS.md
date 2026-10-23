# Composing native quality tools

Alphus owns *which* checks run, their order, file selection, rollout status,
and aggregate result. The native tool owns *what* a finding means and how to
fix it. Start with one `quality-gates.toml`; split language steps into
`languages/*.toml` only when the policy becomes hard to read.

## One place for each setting

- `quality-gates.toml` selects steps, profiles, rollout, file scope, and fixers.
  The [starter](../examples/starter/quality-gates.toml) needs only this file.
- rumdl owns Markdown style and ordinary local links (`MD057`, `MD051`). Add
  `[tool.rumdl]` in `pyproject.toml` only when changing its defaults.
- mdrepo owns portable repository links and the document graph. Add
  `[tool.mdrepo]` in `pyproject.toml` or `mdrepo.toml` for nondefault policy,
  such as orphan roots.
- Taplo owns TOML formatting. Add its config only when changing defaults;
  keep it in the repository or pass `--config`.
- Prettier owns JSON formatting. Add the repository's Prettier config only
  when changing defaults.

Install and pin the tools named by the selected profile through the consumer's
normal development or CI dependency setup. Alphus does not install native
tools as runtime dependencies. Use `{python} -m <tool>` for a Python tool that
must run in Alphus's interpreter, and a project-pinned executable for tools
that are not Python packages. A missing executable fails its step visibly.

The command runner starts in the repository root by default. A step may set
`working_directory` to a path inside that root; configuration discovery by
Taplo and other tools can depend on that directory. `{root}` is the absolute
checkout path, `{config}` is the Alphus policy path, and `{python}` is the
running interpreter. `{files}` expands to separate relative path arguments.
It requires a `files = { include = [...] }` inventory on that command step.
Alphus selects Git tracked and non-ignored untracked files for this inventory.
An empty selection skips the command. An unscoped command runs once even when
there are no matching files. The global `[files]` section is needed only for
Alphus-owned `kind = "rule"` steps.

## Keep Markdown checks distinct

When both tools run, rumdl owns ordinary missing local targets (`MD057`) and
heading fragments (`MD051`). Leave mdrepo's
`links.check-missing-targets` disabled, its default, so it does not repeat those
findings as `MDR004`. Mdrepo owns portable repository link rules, path case,
durable targets, and rooted Markdown graph orphans. Enable orphan checks only
after choosing graph roots, such as:

```toml
[orphans]
enabled = true
roots = ["README.md"]
```

That snippet belongs in `mdrepo.toml` or the equivalent `[tool.mdrepo.orphans]`
table in `pyproject.toml`. The
[consumer Markdown steps](../examples/consumer/languages/markdown.toml) pass an
explicit `--config` for the example file. The smaller
[Markdown policy](../examples/markdown/quality-gates.toml) lets mdrepo discover
its config. Keep the policy explicit when working-directory choices might
change discovery. Mdrepo builds its document graph from the repository even
when Alphus passes selected Markdown paths for findings and fixes.

The two steps are ordered rumdl, then mdrepo. For the paired edit loop, apply
rumdl fixes first, then mdrepo safe fixes, inspect the diff, and rerun the
read-only profile. Mdrepo's `fix` handles only supported safe link rewrites;
remaining findings need review. Rumdl `fmt` can also leave findings that its
formatter cannot resolve. See mdrepo's
[responsibility boundary](https://github.com/sheepfling/mdrepo/blob/main/docs/responsibility-boundary.md)
and [fix documentation](https://github.com/sheepfling/mdrepo/blob/main/README.md).

## Pair checks with explicit fixers

A normal `alphus` run invokes read-only commands. For a file-scoped formatter,
declare its write command in `fix_argv` on the same step:

```toml
[[orchestration.steps]]
kind = "command"
name = "TOML format"
argv = ["taplo", "fmt", "--check", "{files}"]
fix_argv = ["taplo", "fmt", "{files}"]
files = { include = ["*.toml", "**/*.toml"] }
```

Taplo's [`fmt --check`](https://taplo.tamasfe.dev/cli/usage/formatting.html)
checks without writing; `fmt` formats. Taplo discovers config from its working
directory unless explicitly given `--config`. Prettier similarly pairs
[`--check` with `--write`](https://prettier.io/docs/cli/) and resolves
[configuration](https://prettier.io/docs/configuration) from each input file.
The [consumer TOML](../examples/consumer/languages/toml.toml) and
[JSON](../examples/consumer/languages/json.toml) profiles put syntax parsing
before formatting; syntax failures have no automatic fixer. Native formatters
own only their selected language and scope.

Review the fix plan and apply named steps deliberately:

```sh
alphus --fix-plan
alphus --apply-fixes --fix-step "Markdown style"
alphus --apply-fixes --fix-step "Markdown links and graph"
alphus
```

`--apply-fixes` runs only selected fixers. It stops after a failing fixer;
earlier edits remain. Inspect `git diff` and rerun `alphus`, because a fixer
may leave nonfixable findings. The [fix contract](FIXES.md) describes the
available fixers and argument rules.

## Add another language

Add native check commands and optional file-scoped `fix_argv` in the same
policy. Give the language a named profile and include it in `check`. A new gate
can use `rollout = "provisional"` to report results without blocking `check`.
When the language grows beyond a few steps, move those declarations to
`languages/<name>.toml` and list it in `orchestration_files`. Keep native lint,
formatter, compiler, and build settings with their native tool. Alphus needs
new Python rule code only for a reusable policy that native tools do not cover.

# Environment propagation review

Issue #111 starts with an [executable synthetic regression recipe](ENVIRONMENT-BOUNDARY-RECIPE.md).
It demonstrates a reported failure mode, not a newly reproduced failure in current Alphus or a private consumer.
The optional `environment-boundary` review then checks only consumer-declared, statically supported Python boundaries.
Neither component introduces a runner, rewrites environments, or changes default profiles.

## Existing ownership and native tools

Alphus already owns command execution in `execution/orchestration.py`, validated execution settings in
`policy/orchestration.py`, native-tool selection, and shared structured findings/profile results.
`scripts/ci.py` passes history options to the intended self-profile command rather than exporting a global history mode.
This review reuses the existing policy, catalog, review-runner, selector and finding paths.
It does not replace configuration conventions (#51), execution identity (#59), audit completion (#44),
or CI-duplication review (#61).

Ruff/Pyright check syntax, bindings, types and selected subprocess API/security patterns; pytest can execute an
explicitly selected regression. They do not know which consumer-owned setting should reach which command.
Keep those tools and the runtime recipe. The small opt-in advisory adds only a declared propagation contract,
not a general environment-security scanner or an execution-safety guarantee.

## Consumer opt-in

Start with [the example policy](../examples/review/environment-boundary.toml). Declare a symbolic setting name,
exact repository-relative Python source path, top-level function name, and every child command's exact literal argv.
Each child has a non-sensitive slug and `allow_setting = true` or `false`. There is no implicit child allowlist.
Do not put credentials in argv, setting names, contract names or source paths. Values are never configured here.
The scanner compares argv in memory but omits both argv and setting values from findings.

For example, this source produces a candidate for `tests`, but not `report`:

```python
import os
import subprocess


def orchestrate():
    os.environ["ALPHUS_SYNTHETIC_REPORT"] = "enabled"
    subprocess.run(["tool", "report"])
    subprocess.run(["tool", "test"])
```

Run the installed checker against the consumer, without executing that source:

```sh
alphus --root /path/to/consumer --config environment-boundary.toml \
  --rule environment-boundary --json
alphus --root /path/to/consumer --config environment-boundary.toml \
  --run --profile environment-review
```

Prefer a command-local option. If a child requires an environment variable, copy the ordinary environment and
modify only that child's setting. Keep PATH, locale, proxies, compiler configuration and other intentional inheritance.
For the declared setting above, this corrected sequence is supported:

```python
import os
import subprocess


def orchestrate():
    os.environ.pop("ALPHUS_SYNTHETIC_REPORT", None)
    report_env = os.environ.copy()
    report_env["ALPHUS_SYNTHETIC_REPORT"] = "enabled"
    tests_env = os.environ.copy()
    subprocess.run(["tool", "report"], env=report_env)
    subprocess.run(["tool", "test"], env=tests_env)
```

In a real orchestrator prefer constructing a clean per-child copy without altering the parent at all.
The synthetic recipe covers that pattern, including a preexisting parent setting.
If a global mutation is unavoidable, restore the original presence and value in `finally`, including on exceptions.
An empty string is present, not equivalent to an unset key. Temporary mutation is process-wide and is unsafe as
an isolation strategy when concurrent threads or callbacks can launch children.

## Supported evidence and limits

The first advisory intentionally has a closed grammar:

- Plain, undecorated top-level functions in a module containing only direct `import os`, `import subprocess`,
  plain function definitions, docstrings and `pass`. Definition-time expressions and annotations are unassessed.
- Straight-line literal string writes to `os.environ["KEY"]` or a named `os.environ.copy()` snapshot,
  literal-key deletion, and `.pop("KEY", None)`. Only presence and source line are retained.
- Standalone `subprocess.run`, `call`, `check_call` and `check_output` expressions with one literal list/tuple argv
  matching a declared child exactly. Assigned results are currently unassessed. No shell.
  The supported literal options are `check`, `capture_output`, `text`,
  `encoding`, `errors`, `timeout`, `cwd` and `shell=False`. `check`/`capture_output` apply only to `run`;
  Encoding is limited to UTF-8 and errors to strict/replace/ignore (or defaults).
  Invalid literal options are unassessed.
- Omitted `env`, `env=None`, `env=os.environ`, `env=os.environ.copy()`, and a named snapshot are understood.
  Snapshots are separate from later parent mutations. Allowed inheritance and explicit allowed child opt-in are valid.

A forbidden child's known-present setting produces `environment-setting-propagation`, linking the contract name,
setting name, source line and observed child launch line. This is conditional static evidence, not a reproduced leak.
The process's entry environment is unknown. An unknown entry value is never assumed absent or clean.
External monkeypatches, import-path shadowing and concurrent runtime changes cannot be proven absent.

One unsupported statement invalidates the whole selected function's analysis, including any earlier tentative findings.
Helpers, aliases, dynamic values/keys/argv/mappings, `Popen`, shell commands, extra launch callbacks, expansion,
control flow, nested functions, temporary-mutation context managers, `try/finally`, and interprocedural/nested-process
propagation are explicitly unassessed by static review. The runtime recipe tests several of those behaviors separately.
This deliberate limitation avoids pretending that a symbolic variable name or a copied dictionary proves isolation.

## Coverage and exit behavior

Every configured contract emits an informational `environment-boundary-status` finding, separate from candidates:

- `disabled`: explicit `enabled=false`, no source read. An absent policy remains opt-out.
- `excluded`: excluded by the rule, no source read.
- `not-selected`: source absent from the selected file inventory, no source read.
- `unassessed`: unavailable/unsafe source, unsupported syntax, no assessed launches, or unknown source.
- `partially-assessed`: some launches assessed, but unknown sources or unobserved declared children remain.
- `inspected`: all declared children observed and supported, with candidate findings.
- `inspected-zero`: all declared children observed and supported, without candidates. Not a runtime safety proof.

Counts distinguish assessed launches, candidates, unknown sources and missing declared children. Missing inventory
is not converted into inspected-zero. Symlink escapes and undecodable source are not read as usable evidence.
Status diagnostics stay informational. Candidate severity defaults to `info`, with existing profile threshold and
step-severity behavior unchanged. An explicit `info` failure threshold includes status findings;
use the default threshold for advisory review. The example uses the existing provisional rollout option.
Scans never edit code, import it, launch children, execute fixtures, install dependencies, or change CI.

## Registration and portability

The feature owns its typed policy, executable feature declaration, and morphology metadata.
Catalog discovery reads declarations without importing the detector. Execution remains opt-in.
Its bounded-heuristic morphology records synthetic-only evaluation maturity, not runtime proof.

A case-variant spelling of the declared setting makes the function unassessed. Windows normalizes
`os.environ` keys, while POSIX environments and copied Python dictionaries have different casing
semantics. The advisory does not silently equate copied dictionary keys or assume a target platform.

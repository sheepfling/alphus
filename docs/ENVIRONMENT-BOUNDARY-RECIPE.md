# Subprocess environment boundary regression recipe

The synthetic recipe for issue #111 demonstrates a command-specific setting
escaping from its intended command A into unrelated commands B and C. It runs
real parent, child, and grandchild Python processes. The bad case is an expected
regression witness, so observing that leak makes the recipe pass, not fail.

This is an explicitly selected runtime experiment, separate from static review.
It does not scan, import, or execute a consumer application, start a shell, make
network requests, or change an Alphus execution profile. Importing the recipe
module does not run the experiment. Its only dependency is Python 3.11 or newer.

## Run explicitly

From this repository, after the development environment setup in `AGENTS.md`:

```sh
.venv/bin/python examples/consumer/environment_boundary_recipe.py
.venv/bin/python -m pytest -q tests/execution/test_environment_boundary_recipe.py
```

The first command prints one JSON report and exits zero when every expected
contract holds. Its `checks.expected_ambient_leak_observed` field must be true:
this confirms that the negative control actually reproduced the mistake. The
other check fields validate corrections, restoration, and passthrough. A failed
child or malformed private probe produces a generic error without environment
details. No report file is written unless the caller explicitly redirects stdout.

A consumer can copy the standalone script and run it with its own Python. It
does not need to install Alphus. The recipe tests are not a substitute for
consumer-owned integration tests of the consumer's real command contracts.

## Cases and expected contracts

| Report field | What the controlled subprocesses establish |
| --- | --- |
| `ambient_leak` | Parent assignment intended for A reaches unrelated B and C and B's grandchild. |
| `command_local` | A and B get separate CLI options; ambient state and A's grandchild stay unset. |
| `explicit_child_env` | Each child gets a copied environment: A keeps the setting, B removes it, C overrides it. |
| `nested_boundaries` | Grandchildren can inherit or remove the setting; B's subtree stays unset. |
| `unset_and_empty` | An absent variable, an explicitly empty variable, and an empty CLI option remain distinct. |
| `intentional_inheritance` | A shared setting reaches both children and the intended grandchild. |
| `temporary_restoration` | Normal exit and nested exceptions restore absent, empty, and nonempty initial states. |
| `adjacent_commands` | A command-specific environment does not contaminate the next command. |

The tests also run the recipe repeatedly inside one pytest process, check that
it restores its caller's environment exactly, and exercise nested exceptions
independently of the recipe's own assertions. They do not depend on test order.

## Prefer command-local options or a copied child environment

Use a native command's CLI option when it defines the desired behavior. CLI
options do not automatically propagate to descendants; forwarding an option to
a grandchild is a separate, explicit contract.

When a child genuinely requires an environment variable, start from
`os.environ.copy()`, then change or remove only the specific declared key:

```python
child_env = os.environ.copy()
child_env["ALPHUS_RECIPE_COMMAND_SETTING"] = "a-only"
subprocess.run(command_a, env=child_env, check=True)

other_env = os.environ.copy()
other_env.pop("ALPHUS_RECIPE_COMMAND_SETTING", None)
subprocess.run(command_b, env=other_env, check=True)
```

Passing `env={}` or a tiny allowlist is not the correction demonstrated here:
it can silently remove PATH, locale, proxy, SDK, compiler, and toolchain settings.
The recipe privately checks representative requirements in those categories at
every child boundary. The tests also compare every unrelated key in copied
mappings without printing those keys or values. Unknown ordinary keys are kept.

Do not normalize an empty string to absence without a consumer-defined reason.
An empty value may disable a setting, while an absent key may select a default.
Likewise, intentional inheritance is a valid contract, not automatically a leak.

The temporary-mutation helper is included to test cleanup of legacy code. Its
`finally` block restores whether the key existed and its exact prior value,
including an empty string. It is not thread-safe: another thread or an async
task launching a child during the scope can still observe the temporary value.
Prefer per-child mappings instead of mutating shared `os.environ` in concurrent
or reusable orchestration code.

## Privacy and limits

- The only environment key whose observed value can appear in a report is the
  declared synthetic `ALPHUS_RECIPE_COMMAND_SETTING`. The recipe replaces any
  caller-supplied value before probing and restores it privately afterward.
- Observed values are restricted to fixed synthetic strings. Unexpected values
  in child mode and invalid CLI arguments are rejected without echoing them.
  Do not use the internal child
  flags to pass credentials or real settings.
- PATH, locale, proxy, and toolchain expectations travel only through an
  anonymous stdin pipe to the synthetic child. Values are compared in memory;
  output contains category-level booleans, never those values or their hashes.
- No complete process environment is serialized, logged, or written to disk.
  Full copies are used only in memory to construct children and check cleanup.
- The probe uses the current Python executable with `-I` so user site modules
  and Python startup paths cannot import consumer code. Environment strings are
  still passed through, but this does not test Python's interpretation of
  `PYTHONPATH` or other interpreter settings, or a real tool's behavior.
- A passing synthetic recipe cannot establish that arbitrary wrappers, dynamic
  commands, concurrent launches, shell startup files, native libraries, or
  deployment systems obey a consumer's propagation contract. Validate those
  with narrowly scoped consumer-owned tests, without logging real environments.

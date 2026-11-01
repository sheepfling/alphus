# Agent guidance

## Project structure

- Python package code lives in `src/alphus/` and `src/alphus_stub_quality/`.
- JavaScript quality-policy package code lives in `javascript/`.
- Tests live in `tests/` and `javascript/tests/`.
- Repository policy and documentation live in `quality-gates.toml`, `quality_gates/`, and `docs/`.
- Follow the ownership boundaries described in `docs/ARCHITECTURE.md`; keep shared contracts, policy, execution, and support code in their respective packages.

## Development conventions

- Support Python 3.11 through 3.15 for the main package.
- Keep Python typing strict and follow the existing Ruff configuration.
- Preserve the package's public boundaries; avoid adding root-level modules without a clear need.
- Keep consumer-facing policy configurable rather than embedding repository-specific paths or assumptions in reusable rules.
- For JavaScript package changes, follow the existing ESM exports and package scripts in `package.json`.
- Update relevant documentation when changing public behavior, configuration, or supported toolchains.

## Validation

- Python checks are defined by the repository self-check and `pyproject.toml` (Ruff, Pyright, and pytest).
- JavaScript checks are defined by the `lint`, `format:check`, `typecheck`, and `test` scripts in `package.json`.
- Run the checks relevant to the files changed and report any checks not run.

## Quality policy integrity

- Before changing `quality-gates.toml`, native-tool configuration, or CI
  quality jobs, inspect the current `check` profile with
  `alphus --plan --profile check --json` and compare it with package manifests,
  existing tool configuration, and CI commands.
- Do not weaken a gate just to make a code change pass. Preserve selected steps
  and relevant file coverage; do not widen exclusions, lower a rule's severity,
  change a mainline step to provisional, relax the failure threshold, or alter
  native-tool rules unless the task explicitly calls for a policy change.
- For a suspected false positive, identify the rule and reproduce the finding.
  Prefer correcting a general rule defect or adding the narrowest
  repository-specific exception with a nearby rationale. Keep the gate enabled
  for unrelated files.
- When adding coverage, select tools and Alphus sniffers based on the
  repository's actual languages and workflow. Consult `docs/ADOPTION.md`,
  `docs/CONSUMER-PROFILES.md`, `docs/SUBTOOLS.md`, and `docs/REVIEW-CHECKS.md`;
  do not assume available checks are automatically enabled.
- Summarize policy changes separately from code fixes and report the final
  selected profile and checks not run.

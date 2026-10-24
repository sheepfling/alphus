# Portable gate packages

`portable_gates/` contains standalone gate implementations intended to be
copied into consumer repositories. These files use the Python standard library
and do not import Alphus. They are intentionally kept outside `src/alphus` and
are not included in the Alphus wheel. Alphus remains the policy and
orchestration layer: consumer profiles invoke the copied tools as command
steps and retain their native reports and exit codes.

## Packages

- `cpp/` checks C++ source ownership, build and test evidence, packages, and
  binary artifact budgets.
- `repository/` contains language-neutral repository checks, currently
  worktree hygiene.

Copy only the package a consumer needs. Keep its policies, build-system
adapters, thresholds, and CI configuration in that consumer repository. The
packages are tested from the Alphus checkout with
`python -m pytest tests/test_cpp_quality_portable.py` and
`python -m pytest tests/test_cpp_quality.py`.

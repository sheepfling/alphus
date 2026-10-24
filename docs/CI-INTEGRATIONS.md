# CI integrations

Alphus uses the same Python CLI in every provider: `python -m alphus`. The
provider templates only provision Python, install a pinned Alphus revision and
the consumer's native tools, then pass the checkout, policy, and profile to
that CLI. Alphus resolves the policy, runs the selected checks, and returns the
pipeline exit status. The templates do not duplicate gate behavior.

Alphus is not currently installed from a package index. Pin both the reusable
workflow/template and the installed package to the same full Alphus commit SHA.
Keep native tool versions in a consumer-owned requirements file; runtime
requirements used by tests can be passed separately. The Python
requirements file installs Python-based native tools. Other selected tools,
such as Node.js or a compiler, must also be available on the runner. Use
the existing GitHub composite action in a caller-controlled job when you
need to add setup steps before running Alphus.

## GitHub Actions

In this repository, `self-*` workflows run Alphus's own CI. The
`reusable-*` workflow is a `workflow_call` entry point for consumer repositories.
GitHub requires reusable workflow files to live in `.github/workflows`, beside
the event-triggered workflows. The YAML below is a caller example for a
consumer repository.

Create a caller workflow such as `.github/workflows/quality.yml`:

```yaml
name: Quality

on: [pull_request, push]

permissions:
  contents: read

jobs:
  alphus:
    uses: sheepfling/alphus/.github/workflows/reusable-consumer-quality.yml@<ALPHUS_COMMIT_SHA>
    with:
      alphus-ref: <ALPHUS_COMMIT_SHA>
      requirements-file: requirements-ci.txt
      config-file: quality-gates.toml
      profile: check
      python-version: "3.12"
```

The reusable workflow checks out the caller's repository. The caller controls
events and permissions. Its `requirements-file` contains the native tools named
by the selected profile. Set `runtime-requirements-file` when tests need the
consumer's runtime dependencies.

For profiles that need additional setup steps, use the existing
[composite action](../ci/quality/action.yml) in the caller's job:

```yaml
steps:
  - uses: actions/checkout@v7
  - uses: actions/setup-node@v7
    with:
      node-version: 22
  - uses: sheepfling/alphus/ci/quality@<ALPHUS_COMMIT_SHA>
    with:
      requirements-file: requirements-ci.txt
      config-file: quality-gates.toml
      profile: check
```

## GitLab CI

Include the shared hidden job from `.gitlab-ci.yml`, then extend it with a job
in the consumer project:

```yaml
include:
  - project: sheepfling/alphus
    ref: <ALPHUS_COMMIT_SHA>
    file: /ci/gitlab/quality.yml

alphus-quality:
  extends: .alphus-quality
  stage: test
  variables:
    ALPHUS_REF: <ALPHUS_COMMIT_SHA>
    ALPHUS_REQUIREMENTS_FILE: requirements-ci.txt
    ALPHUS_CONFIG_FILE: quality-gates.toml
    ALPHUS_PROFILE: check
```

The included job uses `python:3.12-slim`; override `image` on the extending job
to select another supported Python image. Set
`ALPHUS_RUNTIME_REQUIREMENTS_FILE` when needed. The included template contributes
only the hidden job, so the consumer keeps its own stage, job name, rules, and
pipeline triggers. Add a consumer `before_script` or override the image when the
selected profile needs other native tools.

## Azure Pipelines

Declare the pinned template repository, then insert its step template into the
consumer pipeline:

```yaml
resources:
  repositories:
    - repository: alphus
      type: github
      name: sheepfling/alphus
      ref: <ALPHUS_COMMIT_SHA>
      endpoint: github-service-connection

pool:
  vmImage: ubuntu-latest

steps:
  - checkout: self
  - template: ci/azure/quality-steps.yml@alphus
    parameters:
      alphusRef: <ALPHUS_COMMIT_SHA>
      requirementsFile: requirements-ci.txt
      configFile: quality-gates.toml
      profile: check
      pythonVersion: '3.12'
```

Configure `github-service-connection` as a GitHub service connection available
to the Azure pipeline. The step template uses the caller's checked-out source
at `$(Build.SourcesDirectory)`. Set `runtimeRequirementsFile` if tests need
consumer runtime dependencies. The template uses a Bash step, so select a Linux
or macOS agent. Add other native tool setup steps before this template when the
selected profile needs them.

Each provider accepts a custom TOML policy and profile. Start with the
consumer-owned `quality-gates.toml`, select only the tools that repository
installs, and pin those tool versions in its requirements file. See
[consumer profiles](CONSUMER-PROFILES.md) for profile composition and
[installation](../README.md#use-from-another-repository) for installing Alphus
outside CI.

For provider syntax and versioning details, see the official guides for
[GitHub reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
[GitLab included configuration](https://docs.gitlab.com/ci/yaml/), and
[Azure YAML templates](https://learn.microsoft.com/azure/devops/pipelines/process/templates).

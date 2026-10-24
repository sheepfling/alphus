# Installed-package polyglot example

This consumer example uses the installed Alphus package to coordinate Ruff for
Python, Lizard for C/C++, and ESLint for JavaScript. Copy the policy and sample
source files into a Git working tree, then adjust the include and exclude
patterns for that consumer.

Install Alphus and its optional pinned Lizard API dependency from a source
checkout:

```sh
python -m pip install "/path/to/alphus[cyclomatic-lizard]"
```

Install Ruff and ESLint in the consumer's normal locked tool environment at the
exact versions declared in `quality-gates.toml`:

```sh
python -m pip install "ruff==0.16.1"
npm install --save-dev "eslint@10.13.0"
```

The `eslint` command must be on `PATH` when Alphus starts. For an npm-managed
install, run Alphus through an npm script or add `node_modules/.bin` to the
invocation's `PATH`.

Resolve the invocations before running a tool:

```sh
alphus --root /path/to/consumer \
  --config /path/to/consumer/quality-gates.toml \
  --rule cyclomatic-complexity --plan
```

Run all configured language backends and inspect their provenance and
coverage:

```sh
alphus --root /path/to/consumer \
  --config /path/to/consumer/quality-gates.toml \
  --rule cyclomatic-complexity --json
```

The sample functions deliberately include different branch constructs. Each
backend applies its own documented counting semantics; the example does not
compare scores across tools.

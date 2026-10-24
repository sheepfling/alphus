# Agent setup

For Python work in this repository, create a virtual environment in the repository and install Alphus in editable mode with its Python development tools:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[python]"
```

Use `.venv/bin/python` and the tools installed in `.venv/bin` for development and validation. `.venv/` is ignored by Git.

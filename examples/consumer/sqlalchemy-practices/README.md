# SQLAlchemy practices consumer example

This synthetic consumer selects Alphus's `sqlalchemy-practices` rule in a
provisional profile. Its legacy files intentionally contain a few findings;
`modern_models.py` shows typed SQLAlchemy 2.x models, `select()`, and
`selectinload()` that pass.

The scanner reads Python text only. It does not import these example modules
or connect to the consumer's database.
To try it against an installed Alphus wheel, copy this directory outside the
Alphus checkout, initialize it as a Git repository, and run:

```sh
git init
alphus --config quality-gates.toml --plan
alphus --config quality-gates.toml --run --json
```

The plan lists the selected `src/**/*.py` files and the provisional step. The
JSON report includes a warning for `Session.query()`, one for
`declarative_base()`, one for `relationship(backref=...)`, a warning for a plain
SQL string passed to `Connection.execute()`, and a warning for a module-level
`Session` instance. The policy sets `target_sqlalchemy = ">=2.0,<3.0"` and
explicitly enables the optional `module-session` M1b advisory, which is off by
default. Provisional rollout keeps the profile non-blocking while
the consumer reviews its findings. No finding is emitted for the typed model
and loader patterns in `modern_models.py`.

`repository-commit` is disabled by default because transaction ownership is a
consumer decision. To enable the scoped advisory for this example, change the
policy to:

```toml
report_repository_commit = true
repository_paths = ["src/**"]
```

It then reports the visible `session.commit()` in `legacy_repository.py`.
Review that call against the application's actual transaction boundary; a
repository may intentionally own its transaction.

## Runtime and database checks

Use the consumer's own SQLAlchemy and Alembic environment against a disposable
database. Typical migration checks are:

```sh
alembic upgrade head
alembic check
```

`alembic check` covers differences visible to Alembic autogenerate. Review
generated revisions manually for table/column renames, constraints, data
backfills, and downgrade behavior. See the [Alembic autogenerate guide](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).

For N+1 and loader behavior, count statements in a consumer pytest using the
`before_cursor_execute` engine event and compare counts for increasing fixture
sizes:

```python
from sqlalchemy import event

statements: list[str] = []


def count_statement(connection, cursor, statement, parameters, context, executemany):
    statements.append(statement)


event.listen(engine, "before_cursor_execute", count_statement)
try:
    parents = load_parents_with_children(session)
finally:
    event.remove(engine, "before_cursor_execute", count_statement)

assert len(statements) <= expected_for_fixture_size
```

Add separate tests for intentional `selectinload`/joined loading, `Result.unique()`
when joined collection results require it, transaction rollback, and async
session sharing/implicit I/O. These tests need the consumer's runtime and
fixtures; Alphus does not infer them from source.

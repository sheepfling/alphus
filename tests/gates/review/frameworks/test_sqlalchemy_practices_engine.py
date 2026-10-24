"""Synthetic SQLAlchemy source contracts for the optional practice gate."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from alphus.config import SqlAlchemyPracticePolicy
from alphus.gates.review.frameworks.sqlalchemy_practices import (
    check_sqlalchemy_practices,
    sqlalchemy_practice_findings,
)


def _policy(
    **options: bool | str | tuple[str, ...],
) -> SqlAlchemyPracticePolicy:
    return SqlAlchemyPracticePolicy.model_validate(
        {"extensions": (".py",), "target_sqlalchemy": ">=2.0,<3.0", **options}
    )


def _ids(source: str, policy: SqlAlchemyPracticePolicy | None = None) -> list[str]:
    return [
        finding.rule_id
        for finding in sqlalchemy_practice_findings(source, policy or _policy())
    ]


def test_legacy_query_resolves_session_and_query_import_aliases() -> None:
    source = (
        "from sqlalchemy.orm import Session as DbSession, Query as OldQuery\n"
        "def load(session: DbSession):\n"
        "    return session.query(User).all()\n"
        "def legacy(query: OldQuery[User]):\n"
        "    return query\n"
        "def construct(session: DbSession):\n"
        "    return OldQuery(session, User)\n"
        "def unrelated(query):\n"
        "    return query.query(User)\n"
        "def shadowed(DbSession):\n"
        "    return DbSession.query(User)\n"
    )

    findings = sqlalchemy_practice_findings(source, _policy())

    assert [(finding.rule_id, finding.line) for finding in findings] == [
        ("alphus/python/sqlalchemy/style/legacy-query", 3),
        ("alphus/python/sqlalchemy/style/legacy-query", 7),
    ]


def test_qualified_sqlalchemy_imports_resolve_session_and_query_types() -> None:
    source = (
        "import sqlalchemy.orm as orm\n"
        "def load(session: orm.Session):\n"
        "    return session.query(User).all()\n"
        "def legacy(query: orm.Query):\n"
        "    return query\n"
        "def construct(session: orm.Session):\n"
        "    return orm.Query(session, User)\n"
    )

    findings = sqlalchemy_practice_findings(source, _policy())

    assert [(finding.rule_id, finding.line) for finding in findings] == [
        ("alphus/python/sqlalchemy/style/legacy-query", 3),
        ("alphus/python/sqlalchemy/style/legacy-query", 7),
    ]


def test_declarative_base_only_reports_a_base_used_by_local_models() -> None:
    source = (
        "from sqlalchemy.ext.declarative import declarative_base as make_base\n"
        "Base = make_base()\n"
        "OrmBase = Base\n"
        "class Item(OrmBase):\n"
        "    pass\n"
        "Unused = make_base()\n"
        "class Plain:\n"
        "    pass\n"
    )

    findings = sqlalchemy_practice_findings(source, _policy())

    assert [(finding.rule_id, finding.line) for finding in findings] == [
        ("alphus/python/sqlalchemy/style/legacy-declarative-base", 2)
    ]


def test_backref_requires_a_resolved_sqlalchemy_relationship_call() -> None:
    source = (
        "from sqlalchemy.orm import relationship as rel\n"
        "items = rel('Item', back_populates='owner')\n"
        "children = rel('Child', backref='parent')\n"
        "none = rel('Other', backref=None)\n"
        "computed = rel('Other', backref=make_backref('owner'))\n"
        "def unrelated(relationship):\n"
        "    return relationship('Child', backref='parent')\n"
    )

    findings = sqlalchemy_practice_findings(source, _policy())

    assert [(finding.rule_id, finding.line) for finding in findings] == [
        ("alphus/python/sqlalchemy/style/legacy-backref", 3)
    ]


def test_forward_string_annotations_resolve_known_sqlalchemy_types() -> None:
    source = (
        "from sqlalchemy.engine import Connection as Conn\n"
        "from sqlalchemy.orm import Session as DbSession\n"
        "def load(connection: 'Conn', session: 'DbSession'):\n"
        '    connection.execute("SELECT 1")\n'
        '    session.execute("SELECT 2")\n'
    )

    findings = sqlalchemy_practice_findings(source, _policy())

    assert [(finding.rule_id, finding.line) for finding in findings] == [
        ("alphus/python/sqlalchemy/correctness/literal-execute", 4),
        ("alphus/python/sqlalchemy/correctness/literal-execute", 5),
    ]


def test_literal_execute_recognizes_typed_connections_sessions_and_engine_scopes() -> (
    None
):
    source = (
        "from sqlalchemy import create_engine, text\n"
        "from sqlalchemy.engine import Connection as Conn\n"
        "from sqlalchemy.orm import Session as DbSession, sessionmaker\n"
        "engine = create_engine('sqlite://')\n"
        "SessionLocal = sessionmaker(bind=engine)\n"
        "def load(connection: Conn, session: DbSession):\n"
        '    connection.execute("SELECT * FROM users")\n'
        '    session.execute("DELETE FROM users")\n'
        '    connection.execute(text("SELECT 1"))\n'
        '    connection.exec_driver_sql("SELECT 1")\n'
        '    unknown.execute("SELECT 1")\n'
        "def load_with_context():\n"
        "    with engine.connect() as connection:\n"
        '        connection.execute("WITH active AS (SELECT 1) SELECT * FROM active")\n'
        "    with SessionLocal() as session:\n"
        '        session.execute("UPDATE users SET active = 1")\n'
        "def merge(connection: Conn):\n"
        '    connection.execute("MERGE INTO users USING updates ON users.id = updates.id")\n'
    )

    findings = sqlalchemy_practice_findings(source, _policy())

    assert [
        (finding.rule_id, finding.line, finding.severity) for finding in findings
    ] == [
        ("alphus/python/sqlalchemy/correctness/literal-execute", 7, "warning"),
        ("alphus/python/sqlalchemy/correctness/literal-execute", 8, "warning"),
        ("alphus/python/sqlalchemy/correctness/literal-execute", 14, "warning"),
        ("alphus/python/sqlalchemy/correctness/literal-execute", 16, "warning"),
        ("alphus/python/sqlalchemy/correctness/literal-execute", 18, "warning"),
    ]


def test_module_session_does_not_flag_factories_or_function_local_instances() -> None:
    source = (
        "from sqlalchemy.ext.asyncio import (\n"
        "    AsyncSession as AsyncDbSession, async_sessionmaker\n"
        ")\n"
        "from sqlalchemy.orm import Session as DbSession, sessionmaker\n"
        "Factory = sessionmaker()\n"
        "session = Factory()\n"
        "other = DbSession()\n"
        "async_factory = async_sessionmaker()\n"
        "async_session = AsyncDbSession()\n"
        "def make_local():\n"
        "    local = DbSession()\n"
        "    return local\n"
        "class Holder:\n"
        "    session = DbSession()\n"
    )

    findings = sqlalchemy_practice_findings(source, _policy(report_module_session=True))

    assert [(finding.rule_id, finding.line) for finding in findings] == [
        ("alphus/python/sqlalchemy/architecture/module-session", 6),
        ("alphus/python/sqlalchemy/architecture/module-session", 7),
        ("alphus/python/sqlalchemy/architecture/module-session", 9),
    ]
    assert sqlalchemy_practice_findings(source, _policy()) == []


def test_sqlalchemy_target_range_is_required_and_limited_to_2_x() -> None:
    with pytest.raises(ValidationError, match="target_sqlalchemy"):
        SqlAlchemyPracticePolicy.model_validate({"extensions": (".py",)})

    assert (
        _policy(target_sqlalchemy=">=2.0.52,<2.2").target_sqlalchemy == ">=2.0.52,<2.2"
    )

    for unsupported in (
        ">=1.4,<3.0",
        ">=2.0,<4.0",
        "~=2.0",
        ">=2.0,<3.0,!=2.1",
        "not-a-version-range",
    ):
        with pytest.raises(ValidationError, match="target_sqlalchemy"):
            _policy(target_sqlalchemy=unsupported)


def test_repository_commit_requires_enabled_rule_scoped_path_and_known_transaction() -> (
    None
):
    source = (
        "from sqlalchemy.orm import Session\n"
        "from sqlalchemy.engine import Connection\n"
        "def save(session: Session, unknown):\n"
        "    session.commit()\n"
        "    unknown.commit()\n"
        "def save_core(connection: Connection):\n"
        "    connection.commit()\n"
    )
    configured = _policy(
        report_repository_commit=True,
        repository_paths=("src/repositories/**",),
    )

    findings = sqlalchemy_practice_findings(
        source, configured, path="src/repositories/items.py"
    )
    assert [finding.line for finding in findings] == [4, 7]
    assert all(
        finding.rule_id == "alphus/python/sqlalchemy/architecture/repository-commit"
        for finding in findings
    )
    assert (
        sqlalchemy_practice_findings(source, configured, path="src/services/items.py")
        == []
    )
    assert (
        sqlalchemy_practice_findings(
            source,
            _policy(repository_paths=("src/repositories/**",)),
            path="src/repositories/items.py",
        )
        == []
    )


def test_repository_commit_policy_requires_a_consumer_path() -> None:
    with pytest.raises(ValidationError, match="repository_paths"):
        SqlAlchemyPracticePolicy.model_validate(
            {
                "extensions": (".py",),
                "target_sqlalchemy": ">=2.0,<3.0",
                "report_repository_commit": True,
            }
        )
    with pytest.raises(ValidationError):
        SqlAlchemyPracticePolicy.model_validate(
            {
                "extensions": (".py",),
                "target_sqlalchemy": ">=2.0,<3.0",
                "report_repository_commit": True,
                "repository_paths": ("../src/**",),
            }
        )


@pytest.mark.parametrize(
    ("suffix", "switch"),
    [
        ("legacy-query", "report_legacy_query"),
        ("legacy-declarative-base", "report_legacy_declarative_base"),
        ("legacy-backref", "report_backref"),
        ("literal-execute", "report_literal_execute"),
        ("module-session", "report_module_session"),
        ("repository-commit", "report_repository_commit"),
    ],
)
def test_each_sqlalchemy_rule_can_be_disabled_independently(
    suffix: str, switch: str
) -> None:
    source = (
        "from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker\n"
        "Base = declarative_base()\n"
        "class Item(Base):\n"
        "    parent = relationship('Parent', backref='items')\n"
        "SessionFactory = sessionmaker()\n"
        "session = SessionFactory()\n"
        "def update(session: Session):\n"
        "    session.query(Item).all()\n"
        '    session.execute("UPDATE items SET active = 1")\n'
        "    session.commit()\n"
    )
    options: dict[str, bool | tuple[str, ...]] = {
        "report_repository_commit": True,
        "repository_paths": ("src/repositories/**",),
        switch: False,
    }

    findings = sqlalchemy_practice_findings(
        source, _policy(**options), path="src/repositories/items.py"
    )

    assert all(not finding.rule_id.endswith(f"/{suffix}") for finding in findings)


def test_modern_core_and_typed_orm_patterns_are_nonviolations() -> None:
    source = (
        "from sqlalchemy import Column, ForeignKey, Table, create_engine, select, text\n"
        "from sqlalchemy.engine import Connection\n"
        "from sqlalchemy.orm import (\n"
        "    DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload\n"
        ")\n"
        "class Base(DeclarativeBase):\n"
        "    pass\n"
        "class User(Base):\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    posts: Mapped[list['Post']] = relationship(back_populates='user')\n"
        "class Post(Base):\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    user_id: Mapped[int] = mapped_column(ForeignKey('user.id'))\n"
        "    user: Mapped[User] = relationship(back_populates='posts')\n"
        "engine = create_engine('sqlite://')\n"
        "def list_users(session: Session, connection: Connection):\n"
        "    statement = select(User).options(selectinload(User.posts))\n"
        "    session.scalars(statement).all()\n"
        "    connection.execute(text('SELECT 1'))\n"
        "    connection.exec_driver_sql('SELECT 1')\n"
        "    table = Table('legacy_schema', metadata, Column('id', Integer))\n"
    )

    assert sqlalchemy_practice_findings(source, _policy()) == []


def test_nested_scopes_and_unknown_same_named_methods_are_not_inferred() -> None:
    source = (
        "from sqlalchemy.orm import Session\n"
        "def outer(session: Session):\n"
        "    session = object()\n"
        "    session.query(User)\n"
        "def branch(session: Session, enabled: bool):\n"
        "    if enabled:\n"
        "        session = object()\n"
        "    session.query(User)\n"
        "    def nested(session):\n"
        "        session.query(User)\n"
        "    def closure():\n"
        "        session.query(User)\n"
        "    class Local:\n"
        "        def run(self):\n"
        "            self.session.query(User)\n"
        "    client = object()\n"
        "    client.execute('SELECT 1')\n"
    )

    assert sqlalchemy_practice_findings(source, _policy()) == []


def test_file_scope_and_exclusions_are_applied_before_source_reads(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text(
        "from sqlalchemy.orm import Session\n"
        "def load(session: Session):\n"
        "    session.query(Item)\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "skip.py").write_text(
        "from sqlalchemy.orm import Session\n"
        "def load(session: Session):\n"
        "    session.query(Item)\n",
        encoding="utf-8",
    )
    policy = _policy(exclude=("src/skip.py",))

    findings = check_sqlalchemy_practices(
        tmp_path,
        (Path("src/skip.py"), Path("src/keep.py"), Path("src/ignore.pyi")),
        policy,
    )

    assert [(finding.path, finding.rule_id) for finding in findings] == [
        ("src/keep.py", "alphus/python/sqlalchemy/style/legacy-query")
    ]

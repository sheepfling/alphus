"""Typed SQLAlchemy 2.x declarations that the default profile allows."""

from __future__ import annotations

from sqlalchemy import ForeignKey, select
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    selectinload,
)


class Base(DeclarativeBase):
    pass


class Parent(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    children: Mapped[list[Child]] = relationship(back_populates="parent")


class Child(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"))
    parent: Mapped[Parent] = relationship(back_populates="children")


def list_parents(session: Session) -> list[Parent]:
    statement = select(Parent).options(selectinload(Parent.children))
    return list(session.scalars(statement).all())

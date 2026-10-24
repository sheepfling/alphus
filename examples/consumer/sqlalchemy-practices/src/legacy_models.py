"""Intentional legacy ORM examples; this file is source-scanned, never imported."""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Parent(Base):
    children = relationship("Child", backref="parent")

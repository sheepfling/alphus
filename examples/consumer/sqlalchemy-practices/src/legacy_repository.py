"""Intentional legacy query and textual execute examples for the scanner."""

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from src.legacy_models import Record


def find_active(session: Session, connection: Connection) -> object:
    session.query(Record).filter_by(active=True).all()
    return connection.execute("SELECT id FROM record WHERE active = 1")


def save(session: Session, record: object) -> None:
    session.add(record)
    session.commit()

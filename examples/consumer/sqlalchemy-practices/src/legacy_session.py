"""Intentional import-time session example; source-scanned, never imported."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

engine = create_engine("sqlite:///example.db")
session = Session(engine)

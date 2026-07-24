"""Infrastructure adapters: database engines and low-level I/O.

This layer owns SQLAlchemy engine construction and connection concerns. Higher
layers depend on the *interfaces* it exposes (engine factories, session helpers)
rather than on SQLAlchemy directly where practical.
"""

from __future__ import annotations

from text_to_sql.infrastructure.database import (
    Database,
    build_engine,
    make_database,
)

__all__ = ["Database", "build_engine", "make_database"]

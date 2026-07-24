"""Initial reference schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-24

Creates all reference tables from the single-source
``text_to_sql.infrastructure.reference_schema.metadata``. Using the shared
metadata (rather than hand-written ``op.create_table`` calls) guarantees the
migrated schema and the app's reflected schema never drift.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from text_to_sql.infrastructure.reference_schema import metadata as reference_metadata

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    reference_metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    reference_metadata.drop_all(bind=op.get_bind())

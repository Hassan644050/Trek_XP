"""Record which district and division a place belongs to.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: only Bangladeshi places have these, and places added before
    # this migration were resolved by the geocoder without them.
    op.add_column("places", sa.Column("district", sa.String(60)))
    op.add_column("places", sa.Column("division", sa.String(60)))


def downgrade() -> None:
    op.drop_column("places", "division")
    op.drop_column("places", "district")

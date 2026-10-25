"""Anonymous visitor analytics: daily counters, daily visitor hashes, salts.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_counts",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("event", sa.String(20), primary_key=True),
        sa.Column("label", sa.String(120), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "analytics_visitors",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("visitor_hash", sa.String(32), primary_key=True),
    )
    op.create_table(
        "analytics_salts",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("salt", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("analytics_salts")
    op.drop_table("analytics_visitors")
    op.drop_table("analytics_counts")

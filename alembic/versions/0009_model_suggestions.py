"""Model-suggested gadgets awaiting coordinator review.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gadgets", sa.Column("origin", sa.String(20), nullable=False, server_default="coordinator"))
    op.add_column("gadgets", sa.Column("review_status", sa.String(20)))
    op.add_column("gadgets", sa.Column("suggestion_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    for column in ("suggestion_count", "review_status", "origin"):
        op.drop_column("gadgets", column)

"""Gadget pairs a coordinator confirmed are different items.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "distinct_gadget_pairs",
        sa.Column("low_id", sa.Integer(), sa.ForeignKey("gadgets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("high_id", sa.Integer(), sa.ForeignKey("gadgets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("low_id < high_id", name="ck_distinct_pairs_order"),
    )


def downgrade() -> None:
    op.drop_table("distinct_gadget_pairs")

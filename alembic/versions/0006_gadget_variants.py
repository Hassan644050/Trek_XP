"""Buyable variants of a gadget (brand, price, colour, quality, vendor).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gadget_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "gadget_id", sa.Integer(),
            sa.ForeignKey("gadgets.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("brand", sa.String(80), nullable=False),
        sa.Column("model_name", sa.String(80)),
        sa.Column("color", sa.String(40)),
        sa.Column("quality", sa.String(20), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BDT"),
        sa.Column("vendor", sa.String(80)),
        sa.Column("url", sa.String(300)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_gadget_variants_gadget_id", "gadget_variants", ["gadget_id"])


def downgrade() -> None:
    op.drop_index("ix_gadget_variants_gadget_id", table_name="gadget_variants")
    op.drop_table("gadget_variants")

"""Stock on hand for each buying option (variant).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gadget_variants", sa.Column("stock_quantity", sa.Integer()))
    op.add_column("gadget_variants", sa.Column("stock_updated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_gadget_variants_stock_not_negative", "gadget_variants", "stock_quantity >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_gadget_variants_stock_not_negative", "gadget_variants", type_="check")
    op.drop_column("gadget_variants", "stock_updated_at")
    op.drop_column("gadget_variants", "stock_quantity")

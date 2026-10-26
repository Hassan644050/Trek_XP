"""Every buying option must carry a stock count.

Options added before stock was required have none. Their real stock is
unknown, so they become 0 -- shown as "Out of stock" -- until a coordinator
enters the count; nothing is promised as available without a number.
Their stock_updated_at stays empty: the 0 was never confirmed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE gadget_variants SET stock_quantity = 0 WHERE stock_quantity IS NULL")
    op.alter_column("gadget_variants", "stock_quantity", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.alter_column("gadget_variants", "stock_quantity", existing_type=sa.Integer(), nullable=True)

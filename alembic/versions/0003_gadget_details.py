"""Add brand, model, colour and an active flag to gadgets.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable: gadgets entered before this knew none of them, and a
    # generic item (a dry bag) may genuinely have no brand or model.
    op.add_column("gadgets", sa.Column("brand", sa.String(80)))
    op.add_column("gadgets", sa.Column("model_name", sa.String(80)))
    op.add_column("gadgets", sa.Column("color", sa.String(40)))
    # server_default backfills existing rows as active; the column is then
    # NOT NULL, which the model also expects.
    op.add_column(
        "gadgets",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("gadgets", "is_active")
    op.drop_column("gadgets", "color")
    op.drop_column("gadgets", "model_name")
    op.drop_column("gadgets", "brand")

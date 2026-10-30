"""Cache the model's suggestions per kind of trip.

A packing list waited 12-30 seconds (sometimes over a minute) on the model,
and the free tier allows ~20 calls a day -- yet most travellers plan the
same few trips. The first list for a trip now stores the model's fresh
items; the next traveller with the same trip gets them straight away and
costs no model call.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_list_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("items", JSONB(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("model_list_cache")

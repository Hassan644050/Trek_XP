"""Admin-uploaded home page hero photos, per destination.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hero_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("place_slug", sa.String(140), nullable=False),
        sa.Column("place_name", sa.String(200)),
        sa.Column("alt", sa.String(200), nullable=False),
        sa.Column("image_key", sa.String(100), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("country_code", "place_slug", name="uq_hero_images_place"),
    )


def downgrade() -> None:
    op.drop_table("hero_images")

"""Add a search-friendly slug to gadgets for their public detail page.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _slug(text: str) -> str:
    cleaned = text.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")[:120].strip("-")


def upgrade() -> None:
    op.add_column("gadgets", sa.Column("slug", sa.String(140)))

    # Backfill a unique slug for every existing gadget, in id order so the
    # suffix (-2, -3) is assigned deterministically on a collision.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, name FROM gadgets ORDER BY id")).fetchall()

    taken: set[str] = set()
    for gadget_id, name in rows:
        base = _slug(name) or "gadget"
        slug = base
        n = 1
        while slug in taken:
            n += 1
            slug = f"{base}-{n}"
        taken.add(slug)
        bind.execute(
            sa.text("UPDATE gadgets SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": gadget_id},
        )

    op.create_unique_constraint("uq_gadgets_slug", "gadgets", ["slug"])


def downgrade() -> None:
    op.drop_constraint("uq_gadgets_slug", "gadgets", type_="unique")
    op.drop_column("gadgets", "slug")

"""Coordinator catalog: users, sessions, places, gadgets, placements.

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("failed_logins", sa.Integer, server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'coordinator')", name="user_role"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    op.create_table(
        "places",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country_code", sa.String(2)),
        sa.Column("country_name", sa.String(100)),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "latitude", "longitude", name="uq_places_name_coords"),
    )

    op.create_table(
        "gadgets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(60)),
        sa.Column("description", sa.Text),
        sa.Column("image_key", sa.String(100)),
        *_audit_columns(),
        *_timestamps(),
    )
    op.create_index(
        "uq_gadgets_name_lower", "gadgets", [sa.text("lower(name)")], unique=True
    )

    op.create_table(
        "placements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("gadget_id", sa.Integer, sa.ForeignKey("gadgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place_id", sa.Integer, sa.ForeignKey("places.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("trip_types", sa.ARRAY(sa.String(20)), nullable=False),
        sa.Column("activities", sa.ARRAY(sa.String(20)), server_default="{}", nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("why", sa.Text, nullable=False),
        *_audit_columns(),
        *_timestamps(),
        sa.CheckConstraint("cardinality(trip_types) > 0", name="ck_placements_trip_types"),
        sa.CheckConstraint(
            "priority IN ('essential', 'recommended', 'optional')", name="placement_priority"
        ),
    )
    op.create_index("ix_placements_gadget_id", "placements", ["gadget_id"])
    op.create_index("ix_placements_place_id", "placements", ["place_id"])


def downgrade() -> None:
    op.drop_table("placements")
    op.drop_table("gadgets")
    op.drop_table("places")
    op.drop_table("auth_sessions")
    op.drop_table("users")

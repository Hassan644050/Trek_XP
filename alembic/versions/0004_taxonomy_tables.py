"""Admin-managed divisions, trip types and activities.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14

Moves the trip-type and activity lists out of hardcoded enums into tables
the admin panel can edit, and adds a divisions table for grouping
destinations. Seeded with the current values so existing placements (which
store these as plain strings) stay valid.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TRIP_TYPES = [
    ("hiking", "Hiking"), ("business", "Business"), ("beach", "Beach"),
    ("city", "City"), ("backpacking", "Backpacking"), ("winter_sports", "Winter sports"),
]
ACTIVITIES = [
    ("photography", "Photography"), ("diving", "Diving"), ("camping", "Camping"),
    ("cycling", "Cycling"), ("climbing", "Climbing"), ("remote_work", "Remote work"),
]
# The eight Bangladesh divisions, matching app/data/countries/bd/admin.json.
BD_DIVISIONS = [
    "Barishal", "Chattogram", "Dhaka", "Khulna",
    "Mymensingh", "Rajshahi", "Rangpur", "Sylhet",
]


def _options_table(name: str):
    return op.create_table(
        name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.String(30), nullable=False, unique=True),
        sa.Column("label", sa.String(60), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def upgrade() -> None:
    divisions = op.create_table(
        "divisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("country_code", "name", name="uq_divisions_country_name"),
    )
    trip_types = _options_table("trip_types")
    activities = _options_table("activities")

    op.bulk_insert(divisions, [
        {"country_code": "BD", "name": name, "sort_order": i}
        for i, name in enumerate(BD_DIVISIONS)
    ])
    op.bulk_insert(trip_types, [
        {"value": v, "label": label, "is_active": True, "sort_order": i}
        for i, (v, label) in enumerate(TRIP_TYPES)
    ])
    op.bulk_insert(activities, [
        {"value": v, "label": label, "is_active": True, "sort_order": i}
        for i, (v, label) in enumerate(ACTIVITIES)
    ])


def downgrade() -> None:
    op.drop_table("activities")
    op.drop_table("trip_types")
    op.drop_table("divisions")

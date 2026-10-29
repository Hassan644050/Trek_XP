"""More activities for the trip form.

The original six (plus any a coordinator added) left out much of what
people do on a Bangladesh trip -- boat trips on the haors, surfing and
paragliding at Cox's Bazar, wildlife in the Sundarbans, tea estates in
Sylhet -- and each of those changes what gear is worth packing. They are
added after the existing ones; a value that already exists (a coordinator
may have added it) is left as it is.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACTIVITIES = [
    ("swimming", "Swimming"),
    ("snorkelling", "Snorkelling"),
    ("surfing", "Surfing"),
    ("kayaking", "Kayaking"),
    ("boat_trips", "Boat trips"),
    ("fishing", "Fishing"),
    ("paragliding", "Paragliding"),
    ("wildlife_watching", "Wildlife watching"),
    ("birdwatching", "Birdwatching"),
    ("stargazing", "Stargazing"),
    ("tea_garden_tours", "Tea garden tours"),
    ("heritage_sites", "Heritage sites"),
    ("motorbike_touring", "Motorbike touring"),
    ("drone_flying", "Drone flying"),
    ("vlogging", "Vlogging"),
    ("running", "Running"),
]


def upgrade() -> None:
    for value, label in ACTIVITIES:
        op.execute(
            sa.text(
                "INSERT INTO activities (value, label, is_active, sort_order) "
                "SELECT :value, :label, true, COALESCE(MAX(sort_order), 0) + 1 FROM activities "
                "ON CONFLICT (value) DO NOTHING"
            ).bindparams(value=value, label=label)
        )


def downgrade() -> None:
    # Only the ones no placement uses: a gadget tagged "surfing" keeps its
    # activity rather than pointing at a value the form no longer knows.
    op.execute(
        sa.text(
            "DELETE FROM activities WHERE value = ANY(:values) "
            "AND NOT EXISTS (SELECT 1 FROM placements WHERE activities.value = ANY(placements.activities))"
        ).bindparams(values=[v for v, _ in ACTIVITIES])
    )

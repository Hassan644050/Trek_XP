"""Orders: buying from the checkout page.

Guest checkout with cash on delivery. An order copies each line's gadget,
option and price as bought; stock is taken when it is placed and given back
if it is cancelled.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(12), nullable=False, unique=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("customer_name", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(120)),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("area", sa.String(80), nullable=False),
        sa.Column("delivery_zone", sa.String(30), nullable=False),
        sa.Column("note", sa.String(300)),
        sa.Column("payment_method", sa.String(10), nullable=False, server_default="cod"),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("delivery_fee", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BDT"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint("payment_method IN ('cod')", name="ck_orders_payment_method"),
    )
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", sa.Integer(), sa.ForeignKey("gadget_variants.id", ondelete="SET NULL")),
        sa.Column("gadget_name", sa.String(120), nullable=False),
        sa.Column("option", sa.String(200), nullable=False),
        sa.Column("vendor", sa.String(80)),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")

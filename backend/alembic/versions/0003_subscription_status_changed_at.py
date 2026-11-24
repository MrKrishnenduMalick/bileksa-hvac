"""Track when the subscription status last changed (payment grace period).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("subscription_status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_calls_meter_pending",
        "calls",
        ["meter_status"],
        postgresql_where=sa.text("meter_status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_calls_meter_pending", table_name="calls")
    op.drop_column("businesses", "subscription_status_changed_at")

"""Persist demo live-voice reservations (per-visitor/per-day limits survive restarts).
Additive only.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_voice_reservations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("client_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_demo_voice_reservations_client_hash", "demo_voice_reservations", ["client_hash"]
    )
    # platform table: RLS on with no policy, so only the backend's own role can touch it
    op.execute("ALTER TABLE public.demo_voice_reservations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("demo_voice_reservations")

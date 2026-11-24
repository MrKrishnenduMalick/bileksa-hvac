"""Demo voice controls and per-client phone provider. Additive only.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # vapi = number bought/assigned through Vapi; twilio = client's/BILEKSA's Twilio number
    # imported into Vapi
    op.add_column(
        "phone_lines",
        sa.Column("phone_provider", sa.String(10), nullable=False, server_default="vapi"),
    )
    # Demo deployments only: live voice switch and automatic pause (e.g. credits exhausted)
    op.add_column(
        "platform_settings",
        sa.Column("demo_voice_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "platform_settings",
        sa.Column("demo_voice_budget_usd", sa.Numeric(8, 2), nullable=False, server_default="4"),
    )
    op.add_column(
        "platform_settings", sa.Column("demo_voice_paused_until", sa.DateTime(timezone=True))
    )
    op.add_column("platform_settings", sa.Column("demo_voice_pause_reason", sa.String(200)))


def downgrade() -> None:
    for col in (
        "demo_voice_pause_reason",
        "demo_voice_paused_until",
        "demo_voice_budget_usd",
        "demo_voice_enabled",
    ):
        op.drop_column("platform_settings", col)
    op.drop_column("phone_lines", "phone_provider")

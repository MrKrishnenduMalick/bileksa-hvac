"""Managed-service upgrade: packages, hard minute limits, notifications, manual payments,
upgrade requests, FAQs, expenses, cost settings, routing/emergency settings.

Additive only: no table or column is dropped and no row is deleted. Stripe columns stay
unused. Existing businesses keep their status ("active") and their included minutes; a
usage period is opened for any business that has none.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UUID = sa.UUID()


def _id():
    return sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True)


def _created():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _biz(nullable=False, ondelete="CASCADE"):
    return sa.Column(
        "business_id",
        UUID,
        sa.ForeignKey("businesses.id", ondelete=ondelete),
        nullable=nullable,
        index=True,
    )


def upgrade() -> None:
    op.create_table(
        "packages",
        _id(),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("included_minutes", sa.Integer, nullable=False),
        sa.Column("features", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        _created(),
    )

    # businesses
    for col in (
        sa.Column("package_id", UUID, sa.ForeignKey("packages.id", ondelete="SET NULL")),
        sa.Column("usage_alert_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("limit_reached_at", sa.DateTime(timezone=True)),
        sa.Column("notification_email", sa.String(254)),
        sa.Column("fallback_number", sa.String(20)),
        sa.Column("emergency_number", sa.String(20)),
        sa.Column("transfer_mode", sa.String(10), nullable=False, server_default="blind"),
        sa.Column("unavailable_message", sa.String(300)),
        sa.Column("emergency_rules", postgresql.JSONB),
    ):
        op.add_column("businesses", col)
    op.execute(
        "UPDATE businesses SET current_period_start = date_trunc('month', now()), "
        "current_period_end = date_trunc('month', now()) + interval '1 month' "
        "WHERE current_period_start IS NULL OR current_period_end IS NULL"
    )

    # phone lines: existing numbers must be moved to assistant-request routing
    op.add_column(
        "phone_lines",
        sa.Column("needs_sync", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.add_column("phone_lines", sa.Column("synced_at", sa.DateTime(timezone=True)))

    # calls
    op.alter_column("calls", "vapi_assistant_id", existing_type=sa.String(100), nullable=True)
    for col in (
        sa.Column("lead_id", UUID),
        sa.Column("routing", sa.String(30), nullable=False, server_default="ai"),
        sa.Column("summary", sa.String(2000)),
        sa.Column("transfer_attempts", sa.Integer, nullable=False, server_default="0"),
    ):
        op.add_column("calls", col)
    op.create_foreign_key(
        "fk_calls_lead_id", "calls", "leads", ["lead_id"], ["id"], ondelete="SET NULL"
    )
    op.execute(
        "UPDATE calls c SET lead_id = l.id FROM leads l "
        "WHERE l.source_call_id = c.id AND c.lead_id IS NULL"
    )

    # leads
    for col in (
        sa.Column("equipment_type", sa.String(30)),
        sa.Column("customer_type", sa.String(10)),
        sa.Column("notes", sa.String(1000)),
        sa.Column("appointment_status", sa.String(20), nullable=False, server_default="none"),
        sa.Column("preferred_appointment", sa.String(160)),
        sa.Column("last_call_id", UUID),
    ):
        op.add_column("leads", col)
    op.create_index("ix_leads_business_number", "leads", ["business_id", "callback_number"])

    op.create_table(
        "faqs",
        _id(),
        _biz(),
        sa.Column("category", sa.String(10), nullable=False, server_default="faq"),
        sa.Column("question", sa.String(300), nullable=False),
        sa.Column("answer", sa.String(1500), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        _created(),
    )
    op.create_table(
        "upgrade_requests",
        _id(),
        _biz(),
        sa.Column("requested_package_id", UUID, sa.ForeignKey("packages.id", ondelete="SET NULL")),
        sa.Column("message", sa.String(1000)),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("admin_notes", sa.String(1000)),
        sa.Column("requested_by", UUID),
        _created(),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "payment_records",
        _id(),
        _biz(),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("payment_type", sa.String(30), nullable=False),
        sa.Column("paid_on", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("period_start", sa.Date),
        sa.Column("period_end", sa.Date),
        sa.Column("notes", sa.String(1000)),
        sa.Column("recorded_by", sa.String(80), nullable=False),
        _created(),
    )
    op.create_table(
        "expenses",
        _id(),
        _biz(nullable=True, ondelete="SET NULL"),
        sa.Column("incurred_on", sa.Date, nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("recorded_by", sa.String(80), nullable=False),
        _created(),
    )
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vapi_cost_per_minute", sa.Numeric(8, 4), nullable=False),
        sa.Column("telephony_cost_per_minute", sa.Numeric(8, 4), nullable=False),
        sa.Column("fixed_monthly_per_client", sa.Numeric(10, 2), nullable=False),
        sa.Column("approaching_limit_percent", sa.Integer, nullable=False, server_default="80"),
        sa.Column("admin_notification_email", sa.String(254)),
        sa.Column("vapi_tool_ids", sa.String(1000)),
        sa.Column("updated_by", sa.String(80)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "notifications",
        _id(),
        sa.Column(
            "business_id", UUID, sa.ForeignKey("businesses.id", ondelete="CASCADE"), index=True
        ),
        sa.Column("audience", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(4000), nullable=False),
        sa.Column("dedupe_key", sa.String(200), unique=True),
        sa.Column("email_to", sa.String(254)),
        sa.Column("email_status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("email_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("email_error", sa.String(300)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        _created(),
    )
    op.create_index(
        "ix_notifications_email_pending",
        "notifications",
        ["email_status"],
        postgresql_where=sa.text("email_status = 'pending'"),
    )

    # seeds (the app also ensures these exist at startup; see app/services/catalog.py)
    op.execute(
        """
        INSERT INTO packages (code, name, price_cents, included_minutes, features, sort_order)
        VALUES
        ('starter', 'Starter', 19900, 300, '["AI receptionist", "HVAC FAQs", "Lead capture",
          "Emergency detection", "Basic call transfer", "Callback requests", "Call summaries",
          "Client dashboard", "Call history", "Usage tracking", "Standard support"]', 1),
        ('professional', 'Professional', 39900, 700, '["Everything in Starter",
          "Advanced call handling", "Lead qualification", "Appointment workflows",
          "Follow-up workflows", "Reporting", "Priority support"]', 2),
        ('premium', 'Premium', 69900, 1500, '["Everything in Professional", "Custom workflows",
          "Multiple locations", "Custom integrations", "Advanced routing", "Premium support"]', 3)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        "INSERT INTO platform_settings (id, vapi_cost_per_minute, telephony_cost_per_minute, "
        "fixed_monthly_per_client) VALUES (1, 0.15, 0.01, 41) ON CONFLICT (id) DO NOTHING"
    )

    # Row Level Security (same model as 0002: customers may only SELECT their own rows)
    for table in ("faqs", "upgrade_requests"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM anon")
        op.execute(f"GRANT SELECT ON public.{table} TO authenticated")
        op.execute(
            f"CREATE POLICY member_read ON public.{table} FOR SELECT TO authenticated "
            "USING (business_id IN (SELECT public.bileksa_member_business_ids()))"
        )
    op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON public.notifications FROM anon")
    op.execute("GRANT SELECT ON public.notifications TO authenticated")
    op.execute(
        "CREATE POLICY member_read ON public.notifications FOR SELECT TO authenticated "
        "USING (audience = 'owner' AND business_id IN "
        "(SELECT public.bileksa_member_business_ids()))"
    )
    op.execute("ALTER TABLE public.packages ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON public.packages FROM anon")
    op.execute("GRANT SELECT ON public.packages TO authenticated")
    op.execute(
        "CREATE POLICY catalog_read ON public.packages FOR SELECT TO authenticated USING (active)"
    )
    # admin-only: RLS on, no policy -> invisible to customer sessions
    for table in ("payment_records", "expenses", "platform_settings"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON public.{table} FROM anon, authenticated")


def downgrade() -> None:
    for table in ("faqs", "upgrade_requests", "notifications"):
        op.execute(f"DROP POLICY IF EXISTS member_read ON public.{table}")
    op.execute("DROP POLICY IF EXISTS catalog_read ON public.packages")
    for table in (
        "notifications",
        "platform_settings",
        "expenses",
        "payment_records",
        "upgrade_requests",
        "faqs",
    ):
        op.drop_table(table)
    op.drop_index("ix_leads_business_number", table_name="leads")
    op.drop_column("phone_lines", "needs_sync")
    op.drop_column("phone_lines", "synced_at")
    for col in (
        "equipment_type",
        "customer_type",
        "notes",
        "appointment_status",
        "preferred_appointment",
        "last_call_id",
    ):
        op.drop_column("leads", col)
    op.drop_constraint("fk_calls_lead_id", "calls", type_="foreignkey")
    for col in ("lead_id", "routing", "summary", "transfer_attempts"):
        op.drop_column("calls", col)
    op.execute("UPDATE calls SET vapi_assistant_id = '' WHERE vapi_assistant_id IS NULL")
    op.alter_column("calls", "vapi_assistant_id", existing_type=sa.String(100), nullable=False)
    for col in (
        "package_id",
        "usage_alert_level",
        "limit_reached_at",
        "notification_email",
        "fallback_number",
        "emergency_number",
        "transfer_mode",
        "unavailable_message",
        "emergency_rules",
    ):
        op.drop_column("businesses", col)
    op.drop_table("packages")

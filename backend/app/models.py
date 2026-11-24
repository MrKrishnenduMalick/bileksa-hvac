"""BILEKSA tables. Every tenant table carries business_id."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _biz() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))
    website: Mapped[str | None] = mapped_column(String(300))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    # Service status: onboarding | active | limit_reached | suspended (see services/usage.py)
    account_status: Mapped[str] = mapped_column(String(20), nullable=False, default="onboarding")
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packages.id", ondelete="SET NULL")
    )
    usage_alert_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limit_reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_email: Mapped[str | None] = mapped_column(String(254))
    # routing: direct line (transfer_number), backup, emergency line, what to say when no one can
    fallback_number: Mapped[str | None] = mapped_column(String(20))
    emergency_number: Mapped[str | None] = mapped_column(String(20))
    transfer_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="blind")
    unavailable_message: Mapped[str | None] = mapped_column(String(300))
    emergency_rules: Mapped[list | None] = mapped_column(JSONB)
    # transfer settings (merged from transfer_settings)
    transfer_number: Mapped[str | None] = mapped_column(String(20))
    transfer_in_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    transfer_after_hours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transfer_emergencies_after_hours: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    emergency_preference: Mapped[str] = mapped_column(
        String(30), nullable=False, default="transfer_then_callback"
    )
    after_hours_message: Mapped[str | None] = mapped_column(String(300))
    # subscription (merged from subscriptions)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    plan: Mapped[str | None] = mapped_column(String(50))
    subscription_status: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    subscription_status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    included_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()


class Package(Base):
    __tablename__ = "packages"
    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    included_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    features: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()


class BusinessMember(Base):
    __tablename__ = "business_members"
    __table_args__ = (UniqueConstraint("user_id", "business_id"),)
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    business_id: Mapped[uuid.UUID] = _biz()
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")
    created_at: Mapped[datetime] = _created()


class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (UniqueConstraint("business_id", "weekday"),)
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = Monday
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)


class HolidayClosure(Base):
    __tablename__ = "holiday_closures"
    __table_args__ = (UniqueConstraint("business_id", "date"),)
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    price_min_cents: Mapped[int | None] = mapped_column(Integer)
    price_max_cents: Mapped[int | None] = mapped_column(Integer)
    price_note: Mapped[str | None] = mapped_column(String(200))
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()


class ServiceArea(Base):
    __tablename__ = "service_areas"
    __table_args__ = (UniqueConstraint("business_id", "zip_code"),)
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    zip_code: Mapped[str] = mapped_column(String(5), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))


class Assistant(Base):
    __tablename__ = "assistants"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    vapi_assistant_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provisioning_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()")
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    claim_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_epoch: Mapped[int | None] = mapped_column(Integer)
    duplicate_check_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    template_version: Mapped[int | None] = mapped_column(Integer)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_config_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class PhoneLine(Base):
    __tablename__ = "phone_lines"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    business_number: Mapped[str] = mapped_column(String(20), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(40))
    vapi_phone_number_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    destination_number: Mapped[str | None] = mapped_column(String(20))
    forwarding_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="conditional")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="collected")
    test_window_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_call_id: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(String(300))
    # Vapi number configuration (assistant-request routing + fallback) must be re-pushed
    needs_sync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    phone_provider: Mapped[str] = mapped_column(String(10), nullable=False, default="vapi")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        Index(
            "ix_calls_meter_pending",
            "meter_status",
            postgresql_where=text("meter_status = 'pending'"),
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    vapi_call_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    vapi_assistant_id: Mapped[str | None] = mapped_column(String(100))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL", use_alter=True, name="fk_calls_lead_id"),
    )
    # ai | forwarded_limit | forwarded_suspended | unavailable (decided at call start)
    routing: Mapped[str] = mapped_column(String(30), nullable=False, default="ai")
    summary: Mapped[str | None] = mapped_column(String(2000))
    transfer_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caller_number: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    ended_reason: Mapped[str | None] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, default="in_progress")
    urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_type: Mapped[str | None] = mapped_column(String(30))
    transfer_destination: Mapped[str | None] = mapped_column(String(20))
    transfer_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    provider_cost_cents: Mapped[int | None] = mapped_column(Integer)
    numbers_to_check: Mapped[list | None] = mapped_column(JSONB)
    report_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # billing event (plan section 11)
    billable_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overage_seconds: Mapped[int | None] = mapped_column(Integer)
    meter_event_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    meter_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unallocated")
    meter_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meter_first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meter_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meter_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meter_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created()


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("business_id", "source_call_id"),
        Index("ix_leads_business_number", "business_id", "callback_number"),
    )
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    source_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    customer_name: Mapped[str | None] = mapped_column(String(120))
    callback_number: Mapped[str | None] = mapped_column(String(20))
    number_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    address: Mapped[str | None] = mapped_column(String(300))
    zip_code: Mapped[str | None] = mapped_column(String(5))
    issue_summary: Mapped[str | None] = mapped_column(String(1000))
    service_type: Mapped[str | None] = mapped_column(String(60))
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="live_tool")
    callback_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    callback_preferred_time: Mapped[str | None] = mapped_column(String(120))
    callback_reason: Mapped[str | None] = mapped_column(String(300))
    equipment_type: Mapped[str | None] = mapped_column(String(30))
    customer_type: Mapped[str | None] = mapped_column(String(10))  # new | existing
    notes: Mapped[str | None] = mapped_column(String(1000))
    appointment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    preferred_appointment: Mapped[str | None] = mapped_column(String(160))
    last_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LeadEvent(Base):
    __tablename__ = "lead_events"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(60), nullable=False, default="system")
    created_at: Mapped[datetime] = _created()


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)
    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    processed_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")
    created_at: Mapped[datetime] = _created()


class AdminUser(Base):
    __tablename__ = "admin_users"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = _created()


class Faq(Base):
    __tablename__ = "faqs"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    category: Mapped[str] = mapped_column(String(10), nullable=False, default="faq")  # faq|policy
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answer: Mapped[str] = mapped_column(String(1500), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()


class UpgradeRequest(Base):
    __tablename__ = "upgrade_requests"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    requested_package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("packages.id", ondelete="SET NULL")
    )
    message: Mapped[str | None] = mapped_column(String(1000))
    # open | contacted | payment_verified | completed | declined
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    admin_notes: Mapped[str | None] = mapped_column(String(1000))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentRecord(Base):
    """Payments are taken outside the app and recorded by BILEKSA (admin only)."""

    __tablename__ = "payment_records"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID] = _biz()
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(1000))
    recorded_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = _created()


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="SET NULL"), index=True
    )
    incurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    recorded_by: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = _created()


class PlatformSettings(Base):
    """One row (id = 1): admin-editable cost assumptions and alert settings."""

    __tablename__ = "platform_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vapi_cost_per_minute: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    telephony_cost_per_minute: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    fixed_monthly_per_client: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    approaching_limit_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    admin_notification_email: Mapped[str | None] = mapped_column(String(254))
    # comma-separated Vapi tool ids written by "Sync tools"; overrides VAPI_TOOL_IDS when set
    vapi_tool_ids: Mapped[str | None] = mapped_column(String(1000))
    # demo deployments only
    demo_voice_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    demo_voice_budget_usd: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=4)
    demo_voice_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demo_voice_pause_reason: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = _created()


class Notification(Base):
    """Owner and BILEKSA notifications: always visible in the dashboard, emailed when SMTP is
    configured. dedupe_key makes each notification happen at most once."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_email_pending",
            "email_status",
            postgresql_where=text("email_status = 'pending'"),
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    audience: Mapped[str] = mapped_column(String(10), nullable=False)  # owner | admin
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    email_to: Mapped[str | None] = mapped_column(String(254))
    # pending | sent | failed | skipped (no address or email not configured)
    email_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    email_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    email_error: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class DemoVoiceReservation(Base):
    """Public demo only: one row per live browser call started. Kept in Postgres so the
    per-visitor and per-day limits survive restarts (free hosts restart at will). The
    visitor key is a salted hash of the IP, never the IP itself."""

    __tablename__ = "demo_voice_reservations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = _created()


TENANT_TABLES = [
    "businesses",
    "business_members",
    "business_hours",
    "holiday_closures",
    "services",
    "service_areas",
    "assistants",
    "phone_lines",
    "calls",
    "leads",
    "lead_events",
    "faqs",
    "upgrade_requests",
]
# admin-only tables (RLS on, no customer policy) and catalog/settings
PLATFORM_TABLES = [
    "webhook_events",
    "audit_logs",
    "admin_users",
    "payment_records",
    "expenses",
    "demo_voice_reservations",
]
ALL_TABLES = TENANT_TABLES + PLATFORM_TABLES + ["notifications", "packages", "platform_settings"]

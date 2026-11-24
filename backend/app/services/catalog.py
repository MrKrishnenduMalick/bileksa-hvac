"""Package catalog and platform settings defaults (spec §9, §13).

Prices, minutes and features are admin-editable rows; these defaults are only inserted when
the catalog is empty or the settings row is missing, so admin edits are never overwritten."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Package, PlatformSettings

STARTER = [
    "AI receptionist",
    "HVAC FAQs",
    "Lead capture",
    "Emergency detection",
    "Basic call transfer",
    "Callback requests",
    "Call summaries",
    "Client dashboard",
    "Call history",
    "Usage tracking",
    "Standard support",
]
DEFAULT_PACKAGES = [
    {
        "code": "starter",
        "name": "Starter",
        "price_cents": 19900,
        "included_minutes": 300,
        "features": STARTER,
        "sort_order": 1,
    },
    {
        "code": "professional",
        "name": "Professional",
        "price_cents": 39900,
        "included_minutes": 700,
        "features": [
            "Everything in Starter",
            "Advanced call handling",
            "Lead qualification",
            "Appointment workflows",
            "Follow-up workflows",
            "Reporting",
            "Priority support",
        ],
        "sort_order": 2,
    },
    {
        "code": "premium",
        "name": "Premium",
        "price_cents": 69900,
        "included_minutes": 1500,
        "features": [
            "Everything in Professional",
            "Custom workflows",
            "Multiple locations",
            "Custom integrations",
            "Advanced routing",
            "Premium support",
        ],
        "sort_order": 3,
    },
]
DEFAULT_SETTINGS = {
    "vapi_cost_per_minute": Decimal("0.15"),
    "telephony_cost_per_minute": Decimal("0.01"),
    "fixed_monthly_per_client": Decimal("41"),
    "approaching_limit_percent": 80,
}


async def ensure_defaults(session: AsyncSession) -> None:
    if not (await session.execute(select(func.count()).select_from(Package))).scalar():
        for p in DEFAULT_PACKAGES:
            session.add(Package(**p))
    if await session.get(PlatformSettings, 1) is None:
        session.add(PlatformSettings(id=1, **DEFAULT_SETTINGS))
    await session.commit()


async def platform_settings(session: AsyncSession) -> PlatformSettings:
    row = await session.get(PlatformSettings, 1)
    if row is None:
        await ensure_defaults(session)
        row = await session.get(PlatformSettings, 1)
    assert row is not None
    return row


def package_out(p: Package) -> dict:
    return {
        "id": str(p.id),
        "code": p.code,
        "name": p.name,
        "price_cents": p.price_cents,
        "included_minutes": p.included_minutes,
        "features": list(p.features or []),
        "active": p.active,
        "sort_order": p.sort_order,
    }

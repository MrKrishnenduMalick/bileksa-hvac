"""Internal cost tracking (spec §13). Admin only; never exposed to clients.

Per client and month:
  revenue           = payments recorded by BILEKSA with status "received", paid that month
  usage minutes     = billable seconds of AI calls that ended that month / 60
  Vapi cost (est.)  = minutes x vapi_cost_per_minute          (default $0.15)
  telephony (est.)  = minutes x telephony_cost_per_minute     (default $0.01)
  fixed allocation  = fixed_monthly_per_client for every launched client (default $41)
  other expenses    = expenses recorded for that client that month
  total cost, gross profit = revenue - total cost
Expenses not tied to a client appear only in the totals. Vapi's own reported call cost is
shown alongside the estimate for comparison."""

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, Call, Expense, PaymentRecord
from app.services.catalog import platform_settings


def month_bounds(month: str | None) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            start = date(y, m, 1)
        except ValueError as exc:
            raise ValueError("Use YYYY-MM") from exc
    else:
        start = today.replace(day=1)
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return start, end


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def report(session: AsyncSession, month: str | None) -> dict:
    start, end = month_bounds(month)
    start_dt = datetime(start.year, start.month, 1, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, 1, tzinfo=UTC)
    st = await platform_settings(session)
    vapi_rate = Decimal(str(st.vapi_cost_per_minute))
    tel_rate = Decimal(str(st.telephony_cost_per_minute))
    fixed = Decimal(str(st.fixed_monthly_per_client))

    usage = dict(
        (
            await session.execute(
                select(Call.business_id, func.coalesce(func.sum(Call.billable_seconds), 0))
                .where(Call.routing == "ai", Call.ended_at >= start_dt, Call.ended_at < end_dt)
                .group_by(Call.business_id)
            )
        ).all()
    )
    reported = dict(
        (
            await session.execute(
                select(Call.business_id, func.coalesce(func.sum(Call.provider_cost_cents), 0))
                .where(Call.ended_at >= start_dt, Call.ended_at < end_dt)
                .group_by(Call.business_id)
            )
        ).all()
    )
    revenue = dict(
        (
            await session.execute(
                select(PaymentRecord.business_id, func.sum(PaymentRecord.amount_cents))
                .where(
                    PaymentRecord.status == "received",
                    PaymentRecord.paid_on >= start,
                    PaymentRecord.paid_on < end,
                )
                .group_by(PaymentRecord.business_id)
            )
        ).all()
    )
    in_month = and_(Expense.incurred_on >= start, Expense.incurred_on < end)
    expenses = dict(
        (
            await session.execute(
                select(Expense.business_id, func.sum(Expense.amount_cents))
                .where(in_month)
                .group_by(Expense.business_id)
            )
        ).all()
    )
    businesses = (await session.execute(select(Business).order_by(Business.name))).scalars().all()

    rows = []
    totals = {
        k: 0
        for k in (
            "revenue_cents",
            "vapi_cost_cents",
            "telephony_cost_cents",
            "fixed_allocation_cents",
            "other_expenses_cents",
            "total_cost_cents",
            "gross_profit_cents",
            "vapi_reported_cost_cents",
        )
    }
    total_minutes = Decimal(0)
    for b in businesses:
        seconds = int(usage.get(b.id, 0) or 0)
        minutes = Decimal(seconds) / Decimal(60)
        launched = b.account_status != "onboarding" or seconds > 0
        row = {
            "business_id": str(b.id),
            "name": b.name,
            "service_status": b.account_status,
            "usage_minutes": float(minutes.quantize(Decimal("0.1"))),
            "revenue_cents": int(revenue.get(b.id, 0) or 0),
            "vapi_cost_cents": _cents(minutes * vapi_rate * 100),
            "telephony_cost_cents": _cents(minutes * tel_rate * 100),
            "fixed_allocation_cents": _cents(fixed * 100) if launched else 0,
            "other_expenses_cents": int(expenses.get(b.id, 0) or 0),
            "vapi_reported_cost_cents": int(reported.get(b.id, 0) or 0),
        }
        row["total_cost_cents"] = (
            row["vapi_cost_cents"]
            + row["telephony_cost_cents"]
            + row["fixed_allocation_cents"]
            + row["other_expenses_cents"]
        )
        row["gross_profit_cents"] = row["revenue_cents"] - row["total_cost_cents"]
        total_minutes += minutes
        for k in totals:
            totals[k] += row[k]
        rows.append(row)
    unassigned = int(expenses.get(None, 0) or 0)
    totals["other_expenses_cents"] += unassigned
    totals["total_cost_cents"] += unassigned
    totals["gross_profit_cents"] -= unassigned
    totals["usage_minutes"] = float(total_minutes.quantize(Decimal("0.1")))
    return {
        "month": start.strftime("%Y-%m"),
        "assumptions": {
            "vapi_cost_per_minute": float(vapi_rate),
            "telephony_cost_per_minute": float(tel_rate),
            "fixed_monthly_per_client": float(fixed),
            "formula": "fixed allocation + usage minutes x (Vapi + telephony per minute) + "
            "other expenses",
        },
        "rows": rows,
        "unassigned_expenses_cents": unassigned,
        "totals": totals,
    }

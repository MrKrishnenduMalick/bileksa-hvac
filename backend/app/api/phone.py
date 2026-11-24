"""Phone line status for the client (read-only). The client keeps their number and forwards it
to the BILEKSA number; BILEKSA assigns and configures numbers from the admin panel
(app/services/phone_config.py). Live only after a real test call is verified."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.models import PhoneLine
from app.security.rls import rls_read_session
from app.security.shared import rate_limit_dashboard

router = APIRouter(
    prefix="/api/phone", tags=["phone"], dependencies=[Depends(rate_limit_dashboard)]
)


def forwarding_steps(carrier: str | None, mode: str, destination: str | None) -> list[str]:
    """Typical codes. Codes differ by carrier and plan; the owner confirms with their carrier
    (assumption A9, confirmed per carrier in live testing)."""
    d = (destination or "").lstrip("+1") or "<destination number>"
    if carrier in ("att", "tmobile") and mode == "conditional":
        return [
            f"From the business phone dial **004*1{d}# and press Call (forward when busy, unanswered or unreachable).",
            "To turn it off later dial ##004#.",
        ]
    if carrier in ("att", "tmobile"):
        return [
            f"From the business phone dial **21*1{d}# and press Call.",
            "To turn it off dial ##21#.",
        ]
    if carrier == "verizon" and mode == "conditional":
        return [f"From the business phone dial *71{d} and press Call.", "To turn it off dial *73."]
    if carrier == "verizon":
        return [f"From the business phone dial *72{d} and press Call.", "To turn it off dial *73."]
    return [
        "Open your phone provider's call-forwarding settings (web portal or app) or call their support.",
        f"Forward {'unanswered and busy calls' if mode == 'conditional' else 'all calls'} to {destination or 'your BILEKSA number'}.",
    ]


def line_out(line: PhoneLine | None) -> dict | None:
    if line is None:
        return None
    return {
        "business_number": line.business_number,
        "carrier": line.carrier,
        "destination_number": line.destination_number,
        "forwarding_mode": line.forwarding_mode,
        "state": line.state,
        "test_window_until": line.test_window_until.isoformat() if line.test_window_until else None,
        "verified_at": line.verified_at.isoformat() if line.verified_at else None,
        "last_error": line.last_error,
        "routing_synced": not line.needs_sync,
        "phone_provider": line.phone_provider,
        "synced_at": line.synced_at.isoformat() if line.synced_at else None,
        "steps": forwarding_steps(line.carrier, line.forwarding_mode, line.destination_number),
    }


@router.get("")
async def get_phone(ctx=Depends(rls_read_session)):
    session, m = ctx
    line = (
        await session.execute(select(PhoneLine).where(PhoneLine.business_id == m.business_id))
    ).scalar_one_or_none()
    return line_out(line)

"""/internal/sweep: called every 15 minutes by Supabase pg_cron (decision D10)."""

from fastapi import APIRouter, Depends

from app.security.shared import verify_internal
from app.services.sweep import run_sweep

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal)])


@router.post("/sweep")
async def sweep():
    return await run_sweep()

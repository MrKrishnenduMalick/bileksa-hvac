"""Operator commands.

uv run python -m app.cli setup-vapi-tools   create or update the standard Vapi tools (by
                                            name) and store their ids; every assistant is
                                            then re-synced by the sweep
uv run python -m app.cli sweep              run the recovery sweep once
uv run python -m app.cli add-admin <user-uuid> [email]
"""

import asyncio
import json
import sys
import uuid

from app.db import sessionmaker
from app.models import AdminUser
from app.services.catalog import ensure_defaults
from app.services.sweep import run_sweep
from app.vapi.template import sync_tools


async def setup_tools() -> None:
    async with sessionmaker()() as session:
        await ensure_defaults(session)
    result = await sync_tools()
    for name, tool_id in result["tool_ids"].items():
        state = "created" if name in result["created"] else "updated"
        print(f"{state} {name}: {tool_id}")
    print("\nTool ids stored in platform settings; assistants will be re-synced by the sweep.")


async def add_admin(user_id: str, email: str | None) -> None:
    async with sessionmaker()() as session:
        session.add(AdminUser(user_id=uuid.UUID(user_id), email=email))
        await session.commit()
    print("admin added")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "setup-vapi-tools":
        asyncio.run(setup_tools())
    elif cmd == "sweep":
        print(json.dumps(asyncio.run(run_sweep()), indent=2, default=str))
    elif cmd == "add-admin" and len(sys.argv) >= 3:
        asyncio.run(add_admin(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

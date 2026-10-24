"""``python -m pareeksha.seed``: seed the database named by ``DATABASE_URL`` and print a summary."""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from pareeksha.db.session import make_engine
from pareeksha.seed.runner import seed_database


async def _run() -> int:
    engine = make_engine()
    try:
        result = await seed_database(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()
    print(json.dumps({"created": result.created, "existing": result.existing}, indent=2))
    if result.demo_key:
        print(f"\nDemo API key (shown once, admin scope): {result.demo_key}")
        print("Set it as PAREEKSHA_API_KEY for the web app and CLI.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))

import asyncio
import os
import sys

# Ensure repo root is on sys.path when running as a script.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


async def main() -> None:
    from bot.database.db import init_db, get_referral_stats_detailed, get_user_premium_status

    await init_db()
    print("ok:init_db")
    s = await get_referral_stats_detailed(1)
    print("stats", s)
    st = await get_user_premium_status(1)
    print("premium_status_keys", sorted(st.keys()))


if __name__ == "__main__":
    asyncio.run(main())


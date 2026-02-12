#!/usr/bin/env python3
import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv


def pick_primary_tg_id(raw: str | None) -> int | None:
    if not raw:
        return None
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            return int(chunk)
    return None


async def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    load_dotenv(env_path)

    tg_id = pick_primary_tg_id(os.getenv("ALLOWED_TG_IDS"))
    if tg_id is None:
        print("[i] skip USER.md sync: ALLOWED_TG_IDS is empty")
        return 0

    db_host = os.getenv("DB_HOST")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USERNAME")
    db_password = os.getenv("DB_PASSWORD")

    if not all([db_host, db_name, db_user, db_password]):
        print("[i] skip USER.md sync: DB settings are incomplete")
        return 0

    conn = await asyncpg.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_password,
        ssl=False,
    )
    try:
        row = await conn.fetchrow(
            """
            select
              tg_id,
              max_id,
              first_name,
              username,
              last_name,
              language_code,
              time_zone
            from public.tg_users
            where tg_id = $1
            limit 1
            """,
            tg_id,
        )
    finally:
        await conn.close()

    if not row:
        print(f"[i] USER.md sync: no tg_users row for tg_id={tg_id} yet")
        return 0

    name = row["first_name"] or row["username"] or str(row["tg_id"])
    tz = row["time_zone"] or "Europe/Moscow"
    lang = row["language_code"] or "ru"

    content = (
        "# USER.md - About Your Human\n\n"
        "- **Name:** {name}\n"
        "- **What to call them:** {name}\n"
        "- **Telegram ID:** {tg_id}\n"
        "- **MAX ID:** {max_id}\n"
        "- **Timezone:** {tz}\n"
        "- **Language:** {lang}\n"
    ).format(
        name=name,
        tg_id=row["tg_id"],
        max_id=row["max_id"] or "",
        tz=tz,
        lang=lang,
    )

    user_md = root / "USER.md"
    user_md.write_text(content, encoding="utf-8")
    print(f"[+] USER.md synced from tg_users (tg_id={row['tg_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

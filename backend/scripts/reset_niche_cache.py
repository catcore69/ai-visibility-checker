"""Сброс кеша по нише и/или домену перед тест-прогоном.

Использование (из контейнера backend):
    python -m scripts.reset_niche_cache --domain manomadv.ru
    python -m scripts.reset_niche_cache --niche "база отдыха"
    python -m scripts.reset_niche_cache --domain manomadv.ru --niche "база отдыха"

Что чистит:
- reports по domain_normalized (если указан --domain) — все статусы.
- niche_prompt_templates по category/subcategory ILIKE pattern (если --niche).
- Redis: LLM-ответы по pattern *<keyword>* (если --niche).

Без --domain и --niche скрипт ничего не делает.
"""

import argparse
import asyncio
import sys

import redis.asyncio as aioredis
from sqlalchemy import text

from app.config import settings
from app.db.session import AsyncSessionLocal


async def wipe_reports_by_domain(domain: str) -> int:
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text("DELETE FROM reports WHERE domain_normalized = :d RETURNING id"),
            {"d": domain},
        )
        rows = res.fetchall()
        await db.commit()
        return len(rows)


async def wipe_prompt_templates_by_niche(niche_pattern: str) -> list[str]:
    """niche_pattern — например, «база отдыха» или «аккумулят». Удаляем
    все niche_prompt_templates, где category ИЛИ subcategory ILIKE '%pattern%'."""
    p = f"%{niche_pattern}%"
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            text(
                "DELETE FROM niche_prompt_templates "
                "WHERE category ILIKE :p OR subcategory ILIKE :p "
                "RETURNING niche_key"
            ),
            {"p": p},
        )
        keys = [r[0] for r in res.fetchall()]
        await db.commit()
        return keys


async def wipe_redis_by_keyword(keyword: str) -> int:
    """Удаляет все Redis-ключи, содержащие keyword (LLM-ответы pollers).

    Redis-ключи LLM-кеша имеют формат {model}:{niche_key}:{md5}, где niche_key
    слагифицирован (пробелы → подчёркивания, lowercase). Пробуем несколько
    форм keyword: оригинал + с подчёркиваниями + по каждому слову.
    """
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    total = 0
    try:
        kw = keyword.strip()
        forms: set[str] = set()
        forms.add(kw)
        forms.add(kw.lower())
        # Слагифицированная форма (как в niche_key)
        forms.add(kw.lower().replace(" ", "_"))
        # Каждое значимое слово отдельно (≥4 букв) — на случай частичного матча
        for w in kw.lower().split():
            w = w.strip("«»\"'.,()-—:;_")
            if len(w) >= 4:
                forms.add(w)

        patterns = [f"*{f}*" for f in forms if f]
        for pat in patterns:
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=pat, count=500)
                if keys:
                    total += await client.delete(*keys)
                if cursor == 0:
                    break
    finally:
        await client.close()
    return total


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", help="Удалить все reports по этому домену")
    ap.add_argument(
        "--niche",
        help="Удалить niche_prompt_templates и Redis-ключи по этому фрагменту "
        "(например: «база отдыха», «аккумулят», «бухгалтер»)",
    )
    args = ap.parse_args()

    if not args.domain and not args.niche:
        print("Укажите хотя бы --domain или --niche.")
        sys.exit(1)

    if args.domain:
        n = await wipe_reports_by_domain(args.domain)
        print(f"reports удалено по '{args.domain}': {n}")

    if args.niche:
        keys = await wipe_prompt_templates_by_niche(args.niche)
        print(f"niche_prompt_templates удалено: {len(keys)}")
        for k in keys:
            print(f"  - {k}")
        r = await wipe_redis_by_keyword(args.niche)
        print(f"Redis ключей удалено: {r}")


if __name__ == "__main__":
    asyncio.run(main())

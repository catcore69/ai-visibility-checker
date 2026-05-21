"""Этап 2 ТЗ: site_analyzer + переименование alisa → yandex_ai_search

Revision ID: 003
Revises: 002
Create Date: 2026-05-21

Добавляет:
- reports.client_site_analysis     JSONB — результат site_analyzer для сайта клиента
- reports.competitors_site_analysis JSONB — массив результатов для конкурентов
- reports.competitor_urls          JSONB — массив {name, url} — URL конкурентов
- reports.gap_analysis             JSONB — лидер vs клиент (для страницы 6 PDF)

Переименование (часть 2.4 ТЗ):
- В существующих reports.raw_responses и reports.analysis JSONB:
  ключ "alisa" → "yandex_ai_search".
- Новый код будет писать сразу под новым ключом.
- Старые отчёты остаются открываемыми (значения те же, ключ переименован
  на месте). PDF старых отчётов уже в S3 — их не перегенерируем.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Новые колонки для site_analyzer (этап 2.1–2.3) ---
    op.add_column("reports", sa.Column("client_site_analysis", JSONB(), nullable=True))
    op.add_column("reports", sa.Column("competitors_site_analysis", JSONB(), nullable=True))
    op.add_column("reports", sa.Column("competitor_urls", JSONB(), nullable=True))
    op.add_column("reports", sa.Column("gap_analysis", JSONB(), nullable=True))

    # --- Переименование "alisa" → "yandex_ai_search" в существующих отчётах ---
    # raw_responses: { "alisa": { prompt: text, ... }, ... }
    op.execute(
        """
        UPDATE reports
        SET raw_responses = (raw_responses - 'alisa')
                          || jsonb_build_object('yandex_ai_search', raw_responses->'alisa')
        WHERE raw_responses ? 'alisa'
        """
    )

    # analysis: структура сложнее (есть results[].model_name = "alisa") — обновляем массив.
    # JSONB-функции PG позволяют сделать это одним UPDATE через jsonb_set + replace.
    # Делаем максимально безопасно: только если analysis.results — массив, проходим через
    # jsonb_array_elements и собираем заново. Для простоты используем строковую замену
    # имени модели только в массиве results.
    op.execute(
        r"""
        UPDATE reports
        SET analysis = jsonb_set(
            analysis,
            '{results}',
            (
                SELECT jsonb_agg(
                    CASE
                        WHEN elem->>'model_name' = 'alisa'
                        THEN jsonb_set(elem, '{model_name}', '"yandex_ai_search"')
                        ELSE elem
                    END
                )
                FROM jsonb_array_elements(analysis->'results') elem
            )
        )
        WHERE analysis ? 'results'
          AND jsonb_typeof(analysis->'results') = 'array'
          AND analysis->'results' @> '[{"model_name":"alisa"}]'::jsonb
        """
    )


def downgrade() -> None:
    # Reverse rename: yandex_ai_search → alisa
    op.execute(
        """
        UPDATE reports
        SET raw_responses = (raw_responses - 'yandex_ai_search')
                          || jsonb_build_object('alisa', raw_responses->'yandex_ai_search')
        WHERE raw_responses ? 'yandex_ai_search'
        """
    )
    op.execute(
        r"""
        UPDATE reports
        SET analysis = jsonb_set(
            analysis,
            '{results}',
            (
                SELECT jsonb_agg(
                    CASE
                        WHEN elem->>'model_name' = 'yandex_ai_search'
                        THEN jsonb_set(elem, '{model_name}', '"alisa"')
                        ELSE elem
                    END
                )
                FROM jsonb_array_elements(analysis->'results') elem
            )
        )
        WHERE analysis ? 'results'
          AND jsonb_typeof(analysis->'results') = 'array'
          AND analysis->'results' @> '[{"model_name":"yandex_ai_search"}]'::jsonb
        """
    )

    op.drop_column("reports", "gap_analysis")
    op.drop_column("reports", "competitor_urls")
    op.drop_column("reports", "competitors_site_analysis")
    op.drop_column("reports", "client_site_analysis")

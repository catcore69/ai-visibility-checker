"""Срочные фиксы: дедуп по домену + флаг качества конкурентов.

Revision ID: 006
Revises: 005
Create Date: 2026-05-21

- reports.domain_normalized — корневой домен (example.com) для дедупликации
  и подсчёта лимитов. Индексируется.
- reports.competitor_quality_low — флаг «мало релевантных конкурентов»
  (подсветить эксперту, попросить клиента указать вручную).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("domain_normalized", sa.String(255), nullable=True))
    op.add_column(
        "reports",
        sa.Column("competitor_quality_low", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_reports_domain_normalized", "reports", ["domain_normalized"])

    # Бэкофилл домена для уже существующих отчётов из url_normalized — насколько
    # возможно простым SQL (берём часть до первого '/'). Точную нормализацию
    # новые отчёты получают из extract_root_domain.
    op.execute(
        """
        UPDATE reports
        SET domain_normalized = split_part(url_normalized, '/', 1)
        WHERE domain_normalized IS NULL AND url_normalized IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_reports_domain_normalized", table_name="reports")
    op.drop_column("reports", "competitor_quality_low")
    op.drop_column("reports", "domain_normalized")

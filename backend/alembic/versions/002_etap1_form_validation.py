"""Этап 1 ТЗ: клиентские конкуренты, чекбоксы согласия, кеш промптов

Revision ID: 002
Revises: 001
Create Date: 2026-05-21

Что добавляет:
- reports.client_competitors      — список конкурентов, указанных клиентом
- reports.competitors_source      — source: "client" / "mixed" / "llm"
- reports.consent_personal_data_at — timestamp согласия на ОПД
- reports.consent_cross_border_at  — timestamp согласия на трансгран. передачу
- reports.consent_ip              — IP клиента в момент согласия (для НЦЗПД РБ)

- new table niche_prompt_templates — детерминированный кеш промптов по нише
  (чтобы два отчёта в одной нише давали сравнимые цифры).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- reports: новые колонки ---
    op.add_column("reports", sa.Column("client_competitors", JSONB(), nullable=True))
    op.add_column("reports", sa.Column("competitors_source", sa.String(20), nullable=True))
    op.add_column("reports", sa.Column("consent_personal_data_at", sa.DateTime(), nullable=True))
    op.add_column("reports", sa.Column("consent_cross_border_at", sa.DateTime(), nullable=True))
    op.add_column("reports", sa.Column("consent_ip", sa.String(45), nullable=True))

    # --- niche_prompt_templates: новая таблица ---
    op.create_table(
        "niche_prompt_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("niche_key", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("prompts", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_unique_constraint(
        "uq_niche_prompt_templates_niche_key",
        "niche_prompt_templates",
        ["niche_key"],
    )
    op.create_index(
        "ix_niche_prompt_templates_category",
        "niche_prompt_templates",
        ["category"],
    )


def downgrade() -> None:
    op.drop_index("ix_niche_prompt_templates_category", table_name="niche_prompt_templates")
    op.drop_constraint(
        "uq_niche_prompt_templates_niche_key",
        "niche_prompt_templates",
        type_="unique",
    )
    op.drop_table("niche_prompt_templates")

    op.drop_column("reports", "consent_ip")
    op.drop_column("reports", "consent_cross_border_at")
    op.drop_column("reports", "consent_personal_data_at")
    op.drop_column("reports", "competitors_source")
    op.drop_column("reports", "client_competitors")

"""Этап 5.2.3 ТЗ: контактные поля для заявки на разговор.

Revision ID: 005
Revises: 004
Create Date: 2026-05-21

Bitrix24 убран (на free-тарифе нет ни API, ни виджета записи). Заявку на
разговор собирает наша форма, контакты пишем прямо в reports.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("client_name", sa.String(200), nullable=True))
    op.add_column("reports", sa.Column("client_phone", sa.String(32), nullable=True))
    op.add_column("reports", sa.Column("client_telegram", sa.String(100), nullable=True))
    op.add_column("reports", sa.Column("preferred_call_time", sa.String(20), nullable=True))
    op.add_column("reports", sa.Column("contact_given_at", sa.DateTime(), nullable=True))
    op.add_column("reports", sa.Column("contact_consent_personal_data_at", sa.DateTime(), nullable=True))
    op.add_column("reports", sa.Column("contact_consent_cross_border_at", sa.DateTime(), nullable=True))
    op.add_column("reports", sa.Column("contact_consent_ip", sa.String(45), nullable=True))
    op.add_column("reports", sa.Column("spam_suspect", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("reports", sa.Column("contact_dismissed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in (
        "contact_dismissed_at",
        "spam_suspect",
        "contact_consent_ip",
        "contact_consent_cross_border_at",
        "contact_consent_personal_data_at",
        "contact_given_at",
        "preferred_call_time",
        "client_telegram",
        "client_phone",
        "client_name",
    ):
        op.drop_column("reports", col)

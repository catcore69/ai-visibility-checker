"""Этап 4.2 ТЗ: таблица email_followups для запланированной цепочки писем.

Revision ID: 004
Revises: 003
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_followups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", UUID(as_uuid=True), nullable=False),
        # Тип цепочки: "day_3" / "day_10" / "day_30"
        sa.Column("type", sa.String(20), nullable=False),
        # Когда планируется отправить
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        # Когда фактически отправлено (NULL = ещё не отправлено)
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        # Статус: "pending" / "sent" / "cancelled" / "failed"
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # Причина отмены: "user_unsubscribed" / "user_replied" /
        # "call_scheduled" / "checklist_downloaded" / "report_failed"
        sa.Column("cancelled_reason", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_email_followups_status_scheduled",
        "email_followups",
        ["status", "scheduled_at"],
    )
    op.create_index(
        "ix_email_followups_report_id",
        "email_followups",
        ["report_id"],
    )

    # Token для unsubscribe-ссылки в письмах. Хранится в Report, не в EmailFollowup,
    # чтобы одна ссылка отписывала от всех писем по этому отчёту.
    op.add_column(
        "reports",
        sa.Column("unsubscribe_token", sa.String(64), nullable=True, unique=True),
    )
    op.add_column(
        "reports",
        sa.Column("unsubscribed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reports", "unsubscribed_at")
    op.drop_column("reports", "unsubscribe_token")
    op.drop_index("ix_email_followups_report_id", table_name="email_followups")
    op.drop_index("ix_email_followups_status_scheduled", table_name="email_followups")
    op.drop_table("email_followups")

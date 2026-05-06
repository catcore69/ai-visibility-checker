"""Initial migration

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("url_normalized", sa.String(500), nullable=False),
        sa.Column("canonical_key", sa.String(500), nullable=True),
        sa.Column("brand_name", sa.String(200), nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("email_verification_token", sa.String(100), nullable=True, unique=True),
        sa.Column("email_verification_sent_at", sa.DateTime(), nullable=True),
        sa.Column("email_verification_expires_at", sa.DateTime(), nullable=True),
        sa.Column("browser_fingerprint", sa.String(200), nullable=True),
        sa.Column("niche_data", JSONB(), nullable=True),
        sa.Column("competitors", JSONB(), nullable=True),
        sa.Column("prompts", JSONB(), nullable=True),
        sa.Column("raw_responses", JSONB(), nullable=True),
        sa.Column("analysis", JSONB(), nullable=True),
        sa.Column("visibility_score", sa.Integer(), nullable=True),
        sa.Column("presence_rate", sa.Integer(), nullable=True),
        sa.Column("share_of_voice", sa.Integer(), nullable=True),
        sa.Column("sentiment_score", sa.Integer(), nullable=True),
        sa.Column("recommendations", JSONB(), nullable=True),
        sa.Column("expert_note", sa.Text(), nullable=True),
        sa.Column("pdf_s3_key", sa.String(500), nullable=True),
        sa.Column("pdf_url", sa.String(1000), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("referrer", sa.String(500), nullable=True),
        sa.Column("utm_source", sa.String(100), nullable=True),
        sa.Column("utm_medium", sa.String(100), nullable=True),
        sa.Column("utm_campaign", sa.String(100), nullable=True),
    )
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_email", "reports", ["email"])
    op.create_index("ix_reports_created_at", "reports", ["created_at"])
    op.create_index("ix_reports_url_normalized", "reports", ["url_normalized"])

    op.create_table(
        "lead_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lead_events_report_id", "lead_events", ["report_id"])
    op.create_index("ix_lead_events_event_type", "lead_events", ["event_type"])
    op.create_index("ix_lead_events_created_at", "lead_events", ["created_at"])

    op.create_table(
        "cached_llm_responses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key", sa.String(500), nullable=False, unique=True),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cached_llm_responses_cache_key", "cached_llm_responses", ["cache_key"])
    op.create_index("ix_cached_llm_responses_expires_at", "cached_llm_responses", ["expires_at"])


def downgrade() -> None:
    op.drop_table("cached_llm_responses")
    op.drop_table("lead_events")
    op.drop_table("reports")

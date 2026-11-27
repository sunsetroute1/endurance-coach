"""Add activity detail collection status and chart samples.

Revision ID: 003
Revises: 002
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_detail_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_activity_id", sa.String(length=128), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("metric_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("median_interval_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("source_payload_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_payload_id"], ["raw_payloads.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "provider_activity_id",
            name="uq_activity_detail_collection",
        ),
    )
    op.create_index(
        "ix_activity_detail_collections_status",
        "activity_detail_collections",
        ["user_id", "status"],
    )
    op.create_table(
        "activity_detail_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_payload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("heart_rate_bpm", sa.Float(), nullable=True),
        sa.Column("power_watts", sa.Float(), nullable=True),
        sa.Column("run_cadence_spm", sa.Float(), nullable=True),
        sa.Column("step_cadence_spm", sa.Float(), nullable=True),
        sa.Column("potential_stamina", sa.Float(), nullable=True),
        sa.Column("available_stamina", sa.Float(), nullable=True),
        sa.Column("elevation_meters", sa.Float(), nullable=True),
        sa.Column("speed_mps", sa.Float(), nullable=True),
        sa.Column("grade_adjusted_speed_mps", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_payload_id"], ["raw_payloads.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("activity_id", "sample_index", name="uq_activity_detail_sample"),
    )
    op.create_index(
        "ix_activity_detail_samples_activity",
        "activity_detail_samples",
        ["activity_id", "elapsed_seconds"],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_detail_samples_activity", table_name="activity_detail_samples")
    op.drop_table("activity_detail_samples")
    op.drop_index("ix_activity_detail_collections_status", table_name="activity_detail_collections")
    op.drop_table("activity_detail_collections")

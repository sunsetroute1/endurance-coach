"""Add steps_records table.

Revision ID: 002
Revises: 001
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "steps_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("step_date", sa.Date(), nullable=False),
        sa.Column("source_payload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("step_goal", sa.Integer(), nullable=True),
        sa.Column("distance_meters", sa.Float(), nullable=True),
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
        sa.ForeignKeyConstraint(["source_payload_id"], ["raw_payloads.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_steps_user_date", "steps_records", ["user_id", "step_date"])
    op.create_index(
        "uq_steps_user_provider_date",
        "steps_records",
        ["user_id", "provider", "step_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_steps_user_provider_date", table_name="steps_records")
    op.drop_index("ix_steps_user_date", table_name="steps_records")
    op.drop_table("steps_records")

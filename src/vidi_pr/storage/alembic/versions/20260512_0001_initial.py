"""
initial

Revision ID: 0001
Revises:
Create Date: 2026-05-12 15:45:25.760119+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "job_type",
            sa.Enum("review", name="jobtype", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(), nullable=False),
        sa.Column(
            "trigger_kind",
            sa.Enum("auto", "comment", name="triggerkind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("extra_context", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "done",
                "failed",
                name="jobstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("status_detail", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("jobs_status_created_at_idx", "jobs", ["status", "created_at"], unique=False)
    op.create_table(
        "pr_locks",
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("repo", "pr_number"),
    )
    op.create_table(
        "reviews_posted",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "webhook_deliveries",
        sa.Column("delivery_id", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("delivery_id"),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("reviews_posted")
    op.drop_table("pr_locks")
    op.drop_index("jobs_status_created_at_idx", table_name="jobs")
    op.drop_table("jobs")

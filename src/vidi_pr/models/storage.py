from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.DONE, JobStatus.FAILED})


class JobType(StrEnum):
    REVIEW = "review"


class TriggerKind(StrEnum):
    AUTO = "auto"
    COMMENT = "comment"


def _string_enum(enum_class: type[StrEnum], length: int = 16) -> SAEnum:
    return SAEnum(
        enum_class,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda enum: [member.value for member in enum],
    )


class Base(DeclarativeBase):
    pass


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("jobs_status_created_at_idx", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_type: Mapped[JobType] = mapped_column(_string_enum(JobType))
    installation_id: Mapped[int]
    repo: Mapped[str]
    pr_number: Mapped[int]
    head_sha: Mapped[str]
    trigger_kind: Mapped[TriggerKind] = mapped_column(_string_enum(TriggerKind))
    extra_context: Mapped[str | None]
    status: Mapped[JobStatus] = mapped_column(_string_enum(JobStatus))
    status_detail: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    error: Mapped[str | None]


class PrLock(Base):
    __tablename__ = "pr_locks"

    repo: Mapped[str] = mapped_column(primary_key=True)
    pr_number: Mapped[int] = mapped_column(primary_key=True)
    locked_at: Mapped[datetime] = mapped_column(DateTime)
    job_id: Mapped[int]


class ReviewPosted(Base):
    __tablename__ = "reviews_posted"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repo: Mapped[str]
    pr_number: Mapped[int]
    head_sha: Mapped[str]
    review_id: Mapped[int]
    posted_at: Mapped[datetime] = mapped_column(DateTime)
    duration_ms: Mapped[int]
    chunk_count: Mapped[int]

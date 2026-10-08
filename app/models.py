"""SQLAlchemy ORM models for the Veloxi pipeline."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enums (stored as plain strings for portability)
# --------------------------------------------------------------------------- #
class SourceType(str, enum.Enum):
    rss = "rss"
    api = "api"
    apify = "apify"
    scraper = "scraper"
    manual = "manual"


class SourceStatus(str, enum.Enum):
    unverified = "unverified"
    verified = "verified"
    unreachable = "unreachable"
    disabled = "disabled"


class RawStatus(str, enum.Enum):
    pending = "pending"
    promoted = "promoted"
    rejected = "rejected"


class Difficulty(str, enum.Enum):
    beginner = "Beginner"
    intermediate = "Intermediate"
    advanced = "Advanced"


class OpportunityKind(str, enum.Enum):
    course = "course"
    job = "job"
    scholarship = "scholarship"
    research = "research"
    summer_school = "summer_school"
    conference = "conference"
    competition = "competition"


# Categories are grouped into sections so the catalog serves every field of
# study, not just tech. Order here is display order. The original seven
# category names are preserved verbatim — live rows reference them by string.
CATEGORY_GROUPS: dict[str, list[str]] = {
    "Technology": [
        "Data & AI",
        "Software Development",
        "Cybersecurity",
        "Cloud Computing",
        "IT Support",
        "Design",
    ],
    "Science & Health": [
        "Mathematics",
        "Physics",
        "Chemistry",
        "Biology",
        "Medicine",
        "Pharmacy",
        "Public Health",
        "Neuroscience",
    ],
    "Engineering": [
        "Mechanical Engineering",
        "Electrical Engineering",
        "Civil Engineering",
        "Industrial Engineering",
        "Renewable Energy",
    ],
    "Business & Social Sciences": [
        "Business & PM",
        "Marketing",
        "Finance",
        "Economics",
        "Psychology",
        "Law",
        "Education",
    ],
}

CATEGORIES = [c for group in CATEGORY_GROUPS.values() for c in group]


class ValidationResult(str, enum.Enum):
    ok = "ok"
    redirect = "redirect"
    client_error = "client_error"
    server_error = "server_error"
    timeout = "timeout"
    connection_error = "connection_error"


class AlertType(str, enum.Enum):
    new_opportunity = "new_opportunity"
    deadline_approaching = "deadline_approaching"
    price_changed = "price_changed"
    scholarship_opened = "scholarship_opened"
    scholarship_closing = "scholarship_closing"
    source_down = "source_down"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20), index=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=SourceStatus.unverified.value, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[int] = mapped_column(Integer, default=70)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    raw_opportunities: Mapped[list["RawOpportunity"]] = relationship(back_populates="source")
    ingestion_logs: Mapped[list["IngestionLog"]] = relationship(back_populates="source")


class RawOpportunity(Base):
    """Staging table — everything ingestion produces lands here as PENDING."""

    __tablename__ = "raw_opportunities"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_source_external"),
        Index("ix_raw_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    canonical_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    suggested_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=RawStatus.pending.value)
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    promoted_opportunity_id: Mapped[int | None] = mapped_column(
        ForeignKey("opportunities.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped["Source | None"] = relationship(back_populates="raw_opportunities")


# Career graph: which skills an opportunity teaches (many-to-many).
opportunity_skills = Table(
    "opportunity_skills",
    Base.metadata,
    Column("opportunity_id", ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)


class Opportunity(Base):
    """Clean, deduplicated, served table — the only one the public API reads."""

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_opp_canonical_url"),
        Index("ix_opp_active", "is_active"),
        Index("ix_opp_category", "category"),
        Index("ix_opp_difficulty", "difficulty"),
        Index("ix_opp_freshness", "freshness_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)

    # Fields consumed by the existing frontend
    provider: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20), default=OpportunityKind.course.value, index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default=Difficulty.beginner.value)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    audit: Mapped[bool] = mapped_column(Boolean, default=False)
    certificate: Mapped[bool] = mapped_column(Boolean, default=False)
    duration: Mapped[str] = mapped_column(String(100), default="Self-paced")

    # Provenance / freshness / lifecycle
    url: Mapped[str] = mapped_column(String(1000))
    canonical_url: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source_provider: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False)
    freshness_score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    validation_fail_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    validation_logs: Mapped[list["ValidationLog"]] = relationship(back_populates="opportunity")
    # Eager-loaded (selectin) so serialization/ranking never triggers N+1 queries.
    skills: Mapped[list["Skill"]] = relationship(
        secondary=opportunity_skills, back_populates="opportunities", lazy="selectin"
    )


class Skill(Base):
    """A discrete, teachable skill — the nodes of the career graph."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    opportunities: Mapped[list["Opportunity"]] = relationship(
        secondary=opportunity_skills, back_populates="skills"
    )


class ValidationLog(Base):
    __tablename__ = "validation_logs"
    __table_args__ = (Index("ix_vlog_checked_at", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(String(30))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="validation_logs")


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"
    __table_args__ = (Index("ix_ilog_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_promoted: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    source: Mapped["Source | None"] = relationship(back_populates="ingestion_logs")


class CareerReport(Base):
    """A Career Agent run. Stores only *derived* data — never the raw CV.

    CVs are processed transiently; we persist the extracted skills, the gap,
    and which opportunities were recommended so the admin can review past runs.
    """

    __tablename__ = "career_reports"
    __table_args__ = (Index("ix_career_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    goal: Mapped[str] = mapped_column(String(300), default="")
    have_skills: Mapped[list] = mapped_column(JSON, default=list)
    target_skills: Mapped[list] = mapped_column(JSON, default=list)
    gap_skills: Mapped[list] = mapped_column(JSON, default=list)
    matched_ids: Mapped[list] = mapped_column(JSON, default=list)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_created_at", "created_at"),
        Index("ix_alert_type", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

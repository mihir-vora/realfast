"""
SQLAlchemy ORM models — the database representation of domain entities.

These are separate from the domain dataclasses intentionally:
- Domain entities are pure Python, used by the adjudication engine.
- ORM models handle persistence. The repository layer converts between them.

Table names and column names match the domain model document.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _gen_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MemberModel(Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    policies: Mapped[list["PolicyModel"]] = relationship(back_populates="member")
    claims: Mapped[list["ClaimModel"]] = relationship(back_populates="member")


class PolicyModel(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    policy_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    annual_deductible: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    member: Mapped["MemberModel"] = relationship(back_populates="policies")
    coverage_rules: Mapped[list["CoverageRuleModel"]] = relationship(
        back_populates="policy"
    )
    accumulators: Mapped[list["AccumulatorModel"]] = relationship(
        back_populates="policy"
    )


class CoverageRuleModel(Base):
    __tablename__ = "coverage_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String, nullable=False)
    is_covered: Mapped[bool] = mapped_column(Boolean, default=True)
    coinsurance_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.80")
    )
    annual_limit: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )
    per_visit_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    policy: Mapped["PolicyModel"] = relationship(back_populates="coverage_rules")


class ClaimModel(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="SUBMITTED")
    provider: Mapped[str] = mapped_column(String, nullable=False)
    diagnosis_code: Mapped[str] = mapped_column(String, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    member: Mapped["MemberModel"] = relationship(back_populates="claims")
    line_items: Mapped[list["ClaimLineItemModel"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimLineItemModel(Base):
    __tablename__ = "claim_line_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_charged: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_allowed: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )
    status: Mapped[str] = mapped_column(String, default="PENDING")
    denial_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    claim: Mapped["ClaimModel"] = relationship(back_populates="line_items")


class AccumulatorModel(Base):
    __tablename__ = "accumulators"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_gen_id)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), nullable=False)
    service_type: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_used: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0")
    )

    policy: Mapped["PolicyModel"] = relationship(back_populates="accumulators")

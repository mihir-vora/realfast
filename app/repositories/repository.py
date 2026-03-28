"""
Data access layer — converts between ORM models and domain entities.

Each function does one thing:
    1. Query the database using SQLAlchemy ORM models
    2. Convert the result to domain dataclasses (or vice versa)

The service layer calls these functions; the domain layer never imports
SQLAlchemy. This keeps the adjudication engine pure and testable.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import (
    AccumulatorModel,
    ClaimLineItemModel,
    ClaimModel,
    CoverageRuleModel,
    MemberModel,
    PolicyModel,
)
from app.domain.entities import (
    Accumulator,
    Claim,
    ClaimLineItem,
    CoverageRule,
    Member,
    Policy,
)
from app.domain.enums import ClaimStatus, LineItemStatus, ServiceType


# ---------------------------------------------------------------------------
# Conversion helpers  (ORM model ↔ domain entity)
# ---------------------------------------------------------------------------


def _member_to_domain(m: MemberModel) -> Member:
    return Member(id=m.id, name=m.name, created_at=m.created_at)


def _policy_to_domain(p: PolicyModel) -> Policy:
    return Policy(
        id=p.id,
        member_id=p.member_id,
        policy_number=p.policy_number,
        effective_date=p.effective_date,
        end_date=p.end_date,
        annual_deductible=Decimal(str(p.annual_deductible)),
        created_at=p.created_at,
    )


def _rule_to_domain(r: CoverageRuleModel) -> CoverageRule:
    return CoverageRule(
        id=r.id,
        policy_id=r.policy_id,
        service_type=ServiceType(r.service_type),
        is_covered=r.is_covered,
        coinsurance_rate=Decimal(str(r.coinsurance_rate)),
        annual_limit=Decimal(str(r.annual_limit)),
        per_visit_limit=Decimal(str(r.per_visit_limit)) if r.per_visit_limit is not None else None,
    )


def _accumulator_to_domain(a: AccumulatorModel) -> Accumulator:
    return Accumulator(
        id=a.id,
        policy_id=a.policy_id,
        service_type=ServiceType(a.service_type) if a.service_type else None,
        year=a.year,
        amount_used=Decimal(str(a.amount_used)),
    )


def _line_item_to_domain(li: ClaimLineItemModel) -> ClaimLineItem:
    item = ClaimLineItem(
        id=li.id,
        claim_id=li.claim_id,
        service_type=ServiceType(li.service_type),
        service_date=li.service_date,
        amount_charged=Decimal(str(li.amount_charged)),
    )
    item.amount_allowed = Decimal(str(li.amount_allowed))
    item.status = LineItemStatus(li.status)
    item.denial_reason = li.denial_reason
    return item


def _claim_to_domain(c: ClaimModel) -> Claim:
    claim = Claim(
        id=c.id,
        member_id=c.member_id,
        policy_id=c.policy_id,
        provider=c.provider,
        diagnosis_code=c.diagnosis_code,
    )
    claim.status = ClaimStatus(c.status)
    claim.submitted_at = c.submitted_at
    claim.updated_at = c.updated_at
    claim.line_items = [_line_item_to_domain(li) for li in c.line_items]
    return claim


# ---------------------------------------------------------------------------
# Member queries
# ---------------------------------------------------------------------------


def get_member(db: Session, member_id: str) -> Optional[Member]:
    row = db.query(MemberModel).filter(MemberModel.id == member_id).first()
    return _member_to_domain(row) if row else None


# ---------------------------------------------------------------------------
# Policy queries
# ---------------------------------------------------------------------------


def get_policy_for_member(db: Session, member_id: str) -> Optional[Policy]:
    """Return the (single) policy for a member. We assume one active policy."""
    row = (
        db.query(PolicyModel)
        .filter(PolicyModel.member_id == member_id)
        .first()
    )
    return _policy_to_domain(row) if row else None


def get_policy(db: Session, policy_id: str) -> Optional[Policy]:
    row = db.query(PolicyModel).filter(PolicyModel.id == policy_id).first()
    return _policy_to_domain(row) if row else None


def get_coverage_rules(db: Session, policy_id: str) -> list[CoverageRule]:
    rows = (
        db.query(CoverageRuleModel)
        .filter(CoverageRuleModel.policy_id == policy_id)
        .all()
    )
    return [_rule_to_domain(r) for r in rows]


# ---------------------------------------------------------------------------
# Accumulator queries
# ---------------------------------------------------------------------------


def get_accumulators(
    db: Session, policy_id: str, year: int
) -> dict[Optional[ServiceType], Accumulator]:
    """Load all accumulators for a policy+year as a dict keyed by service_type.

    The deductible accumulator has key=None.
    """
    rows = (
        db.query(AccumulatorModel)
        .filter(
            AccumulatorModel.policy_id == policy_id,
            AccumulatorModel.year == year,
        )
        .all()
    )
    result: dict[Optional[ServiceType], Accumulator] = {}
    for row in rows:
        acc = _accumulator_to_domain(row)
        result[acc.service_type] = acc
    return result


def save_accumulators(
    db: Session, accumulators: dict[Optional[ServiceType], Accumulator]
) -> None:
    """Persist accumulators — upsert by id."""
    for acc in accumulators.values():
        row = db.query(AccumulatorModel).filter(AccumulatorModel.id == acc.id).first()
        if row:
            row.amount_used = acc.amount_used
        else:
            db.add(AccumulatorModel(
                id=acc.id,
                policy_id=acc.policy_id,
                service_type=acc.service_type.value if acc.service_type else None,
                year=acc.year,
                amount_used=acc.amount_used,
            ))


# ---------------------------------------------------------------------------
# Claim queries
# ---------------------------------------------------------------------------


def save_claim(db: Session, claim: Claim) -> None:
    """Persist a claim and all its line items."""
    claim_row = ClaimModel(
        id=claim.id,
        member_id=claim.member_id,
        policy_id=claim.policy_id,
        status=claim.status.value,
        provider=claim.provider,
        diagnosis_code=claim.diagnosis_code,
        submitted_at=claim.submitted_at,
        updated_at=claim.updated_at,
    )
    for li in claim.line_items:
        claim_row.line_items.append(ClaimLineItemModel(
            id=li.id,
            claim_id=claim.id,
            service_type=li.service_type.value,
            service_date=li.service_date,
            amount_charged=li.amount_charged,
            amount_allowed=li.amount_allowed,
            status=li.status.value,
            denial_reason=li.denial_reason,
        ))
    db.merge(claim_row)


def get_claim(db: Session, claim_id: str) -> Optional[Claim]:
    row = db.query(ClaimModel).filter(ClaimModel.id == claim_id).first()
    return _claim_to_domain(row) if row else None


def get_claims_for_member(db: Session, member_id: str) -> list[Claim]:
    rows = (
        db.query(ClaimModel)
        .filter(ClaimModel.member_id == member_id)
        .order_by(ClaimModel.submitted_at.desc())
        .all()
    )
    return [_claim_to_domain(c) for c in rows]


def get_all_claims(db: Session) -> list[Claim]:
    rows = db.query(ClaimModel).order_by(ClaimModel.submitted_at.desc()).all()
    return [_claim_to_domain(c) for c in rows]

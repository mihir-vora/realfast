"""
Members API — read-only endpoints for member and policy info.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.repositories import repository

router = APIRouter(prefix="/members", tags=["members"])


class CoverageRuleResponse(BaseModel):
    service_type: str
    is_covered: bool
    coinsurance_rate: Decimal
    annual_limit: Decimal
    per_visit_limit: Decimal | None = None


class PolicyResponse(BaseModel):
    id: str
    policy_number: str
    effective_date: date
    end_date: date
    annual_deductible: Decimal
    coverage_rules: list[CoverageRuleResponse]


class BenefitBalanceResponse(BaseModel):
    label: str
    limit: Decimal
    used: Decimal
    remaining: Decimal


class MemberResponse(BaseModel):
    id: str
    name: str
    policy: PolicyResponse | None = None
    benefits: list[BenefitBalanceResponse] = []


@router.get("/{member_id}", response_model=MemberResponse)
def get_member(member_id: str, db: Session = Depends(get_db)):
    """Return member info with their policy, coverage rules, and benefit balances."""
    from app.domain.adjudication import get_benefit_summary

    member = repository.get_member(db, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")

    policy = repository.get_policy_for_member(db, member_id)
    policy_resp = None
    benefits = []

    if policy:
        rules = repository.get_coverage_rules(db, policy.id)
        accumulators = repository.get_accumulators(db, policy.id, date.today().year)
        benefit_summary = get_benefit_summary(policy, rules, accumulators)

        policy_resp = PolicyResponse(
            id=policy.id,
            policy_number=policy.policy_number,
            effective_date=policy.effective_date,
            end_date=policy.end_date,
            annual_deductible=policy.annual_deductible,
            coverage_rules=[
                CoverageRuleResponse(
                    service_type=r.service_type.value,
                    is_covered=r.is_covered,
                    coinsurance_rate=r.coinsurance_rate,
                    annual_limit=r.annual_limit,
                    per_visit_limit=r.per_visit_limit,
                )
                for r in rules
            ],
        )
        benefits = [
            BenefitBalanceResponse(
                label=b.label,
                limit=b.limit,
                used=b.used,
                remaining=b.remaining,
            )
            for b in benefit_summary
        ]

    return MemberResponse(
        id=member.id,
        name=member.name,
        policy=policy_resp,
        benefits=benefits,
    )

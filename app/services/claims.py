"""
Claim submission service — orchestrates validation, domain construction, and persistence.

This is the use-case layer: it knows about repositories and domain objects,
but has no HTTP concepts (no Request/Response, no status codes).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.entities import Claim, ClaimLineItem
from app.repositories import repository
from app.schemas.claims import ClaimSubmitRequest


class MemberNotFoundError(Exception):
    def __init__(self, member_id: str):
        self.member_id = member_id
        super().__init__(f"Member '{member_id}' not found")


class PolicyNotFoundError(Exception):
    def __init__(self, member_id: str):
        self.member_id = member_id
        super().__init__(f"No active policy found for member '{member_id}'")


def submit_claim(db: Session, request: ClaimSubmitRequest) -> Claim:
    """Create a new claim in SUBMITTED state.

    Steps:
        1. Verify the member exists
        2. Look up the member's active policy
        3. Build domain Claim + ClaimLineItem objects
        4. Persist via repository
        5. Return the domain Claim

    Raises:
        MemberNotFoundError: if member_id doesn't match any member.
        PolicyNotFoundError: if the member has no active policy.
    """
    member = repository.get_member(db, request.member_id)
    if member is None:
        raise MemberNotFoundError(request.member_id)

    policy = repository.get_policy_for_member(db, request.member_id)
    if policy is None:
        raise PolicyNotFoundError(request.member_id)

    claim = Claim(
        member_id=member.id,
        policy_id=policy.id,
        provider=request.provider,
        diagnosis_code=request.diagnosis_code,
    )

    for li_req in request.line_items:
        claim.line_items.append(
            ClaimLineItem(
                claim_id=claim.id,
                service_type=li_req.service_type,
                service_date=li_req.service_date,
                amount_charged=li_req.amount_charged,
            )
        )

    repository.save_claim(db, claim)
    db.commit()

    return claim

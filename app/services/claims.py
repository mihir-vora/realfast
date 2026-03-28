"""
Claims service — orchestrates submission, adjudication, and persistence.

This is the use-case layer: it knows about repositories and domain objects,
but has no HTTP concepts (no Request/Response, no status codes).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.adjudication import adjudicate_claim
from app.domain.entities import AdjudicationResult, Claim, ClaimLineItem
from app.domain.enums import ClaimStatus
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


class ClaimNotFoundError(Exception):
    def __init__(self, claim_id: str):
        self.claim_id = claim_id
        super().__init__(f"Claim '{claim_id}' not found")


class ClaimNotAdjudicableError(Exception):
    """Raised when a claim is not in SUBMITTED state."""
    def __init__(self, claim_id: str, current_status: str):
        self.claim_id = claim_id
        self.current_status = current_status
        super().__init__(
            f"Claim '{claim_id}' cannot be adjudicated "
            f"(current status: {current_status}, must be SUBMITTED)"
        )


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


@dataclass
class AdjudicationOutcome:
    """Everything the API needs to build the response."""
    claim: Claim
    results: list[AdjudicationResult]
    total_charged: Decimal
    total_approved: Decimal
    total_denied: Decimal


def adjudicate_existing_claim(db: Session, claim_id: str) -> AdjudicationOutcome:
    """Load a submitted claim, run adjudication, persist results.

    Steps:
        1. Load the claim from the database
        2. Verify it's in SUBMITTED state
        3. Load policy, coverage rules, and accumulators
        4. Run the domain adjudication engine
        5. Persist the updated claim and accumulators
        6. Compute totals and return

    Raises:
        ClaimNotFoundError: if claim_id doesn't exist.
        ClaimNotAdjudicableError: if the claim isn't in SUBMITTED state.
        PolicyNotFoundError: if the policy is missing.
    """
    claim = repository.get_claim(db, claim_id)
    if claim is None:
        raise ClaimNotFoundError(claim_id)

    if claim.status != ClaimStatus.SUBMITTED:
        raise ClaimNotAdjudicableError(claim_id, claim.status.value)

    policy = repository.get_policy(db, claim.policy_id)
    if policy is None:
        raise PolicyNotFoundError(claim.member_id)

    rules = repository.get_coverage_rules(db, policy.id)
    year = claim.submitted_at.year
    accumulators = repository.get_accumulators(db, policy.id, year)

    results = adjudicate_claim(claim, policy, rules, accumulators)

    repository.save_claim(db, claim)
    repository.save_accumulators(db, accumulators)
    db.commit()

    total_charged = sum(li.amount_charged for li in claim.line_items)
    total_approved = sum(li.amount_allowed for li in claim.line_items)
    total_denied = total_charged - total_approved

    return AdjudicationOutcome(
        claim=claim,
        results=results,
        total_charged=total_charged,
        total_approved=total_approved,
        total_denied=total_denied,
    )

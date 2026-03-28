"""
Claims API — thin HTTP layer.

Parses the request, delegates to the service layer, formats the response.
Error handling converts service exceptions to appropriate HTTP status codes.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.schemas.claims import (
    AdjudicatedLineItemResponse,
    AdjudicationResponse,
    ClaimResponse,
    ClaimSubmitRequest,
    LineItemResponse,
)
from app.services.claims import (
    ClaimNotAdjudicableError,
    ClaimNotFoundError,
    MemberNotFoundError,
    PolicyNotFoundError,
    adjudicate_existing_claim,
    submit_claim,
)

router = APIRouter(prefix="/claims", tags=["claims"])


def _to_response(claim) -> ClaimResponse:
    return ClaimResponse(
        id=claim.id,
        member_id=claim.member_id,
        policy_id=claim.policy_id,
        status=claim.status.value,
        provider=claim.provider,
        diagnosis_code=claim.diagnosis_code,
        submitted_at=claim.submitted_at,
        line_items=[
            LineItemResponse(
                id=li.id,
                service_type=li.service_type.value,
                service_date=li.service_date,
                amount_charged=li.amount_charged,
                amount_allowed=li.amount_allowed,
                status=li.status.value,
                denial_reason=li.denial_reason,
            )
            for li in claim.line_items
        ],
    )


@router.post("", status_code=201, response_model=ClaimResponse)
def create_claim(
    request: ClaimSubmitRequest,
    db: Session = Depends(get_db),
):
    """Submit a new claim for adjudication."""
    try:
        claim = submit_claim(db, request)
    except MemberNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PolicyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(claim)


@router.post("/{claim_id}/adjudicate", response_model=AdjudicationResponse)
def adjudicate_claim(
    claim_id: str,
    db: Session = Depends(get_db),
):
    """Run adjudication on a submitted claim."""
    try:
        outcome = adjudicate_existing_claim(db, claim_id)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ClaimNotAdjudicableError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PolicyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    results_by_id = {r.line_item_id: r for r in outcome.results}

    return AdjudicationResponse(
        claim_id=outcome.claim.id,
        status=outcome.claim.status.value,
        provider=outcome.claim.provider,
        diagnosis_code=outcome.claim.diagnosis_code,
        total_charged=outcome.total_charged,
        total_approved=outcome.total_approved,
        total_denied=outcome.total_denied,
        line_items=[
            AdjudicatedLineItemResponse(
                id=li.id,
                service_type=li.service_type.value,
                service_date=li.service_date,
                amount_charged=li.amount_charged,
                amount_allowed=li.amount_allowed,
                status=li.status.value,
                denial_reason=li.denial_reason,
                explanation=list(results_by_id[li.id].explanation),
            )
            for li in outcome.claim.line_items
        ],
    )

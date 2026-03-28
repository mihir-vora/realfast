"""
Pydantic models for claim submission API.

These define the HTTP contract — what the client sends and receives.
Separate from domain entities so the API shape can evolve independently.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import ServiceType


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class LineItemRequest(BaseModel):
    service_type: ServiceType
    service_date: date
    amount_charged: Decimal = Field(gt=0, description="Billed amount (must be positive)")


class ClaimSubmitRequest(BaseModel):
    member_id: str = Field(min_length=1)
    provider: str = Field(min_length=1, description="Doctor or facility name")
    diagnosis_code: str = Field(min_length=1, description="ICD-style diagnosis code")
    line_items: list[LineItemRequest] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class LineItemResponse(BaseModel):
    id: str
    service_type: str
    service_date: date
    amount_charged: Decimal
    amount_allowed: Decimal
    status: str
    denial_reason: str | None = None


class ClaimResponse(BaseModel):
    id: str
    member_id: str
    policy_id: str
    status: str
    provider: str
    diagnosis_code: str
    submitted_at: datetime
    line_items: list[LineItemResponse]


# ---------------------------------------------------------------------------
# Adjudication response
# ---------------------------------------------------------------------------


class LineItemExplanation(BaseModel):
    reason_code: str
    member_explanation: str
    rule_trace: list[str]
    deductible_applied: Decimal
    remaining_annual_benefit: Decimal | None = None


class AdjudicatedLineItemResponse(BaseModel):
    id: str
    service_type: str
    service_date: date
    amount_charged: Decimal
    amount_allowed: Decimal
    status: str
    denial_reason: str | None = None
    explanation: LineItemExplanation


class AdjudicationResponse(BaseModel):
    claim_id: str
    status: str
    provider: str
    diagnosis_code: str
    total_charged: Decimal
    total_approved: Decimal
    total_denied: Decimal
    line_items: list[AdjudicatedLineItemResponse]

"""
Core domain entities for the claims processing system.

All entities are plain dataclasses — no ORM, no framework dependencies.
This keeps the domain logic testable in isolation and easy to explain.

Mapping to the problem statement:
    Member          → the insured person
    Policy          → the insurance plan with coverage terms
    CoverageRule    → one rule: "service X is covered at Y% up to $Z/year"
    Claim           → a reimbursement request containing line items
    ClaimLineItem   → one billable service on a claim
    Accumulator     → running total of deductible/limit usage per plan year
    AdjudicationResult → value object: what the engine decided for one line item
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Optional

from app.domain.enums import (
    CLAIM_TRANSITIONS,
    LINE_ITEM_TRANSITIONS,
    ClaimStatus,
    LineItemStatus,
    ServiceType,
)


class InvalidTransitionError(Exception):
    """Raised when a state transition violates the lifecycle rules."""

    def __init__(
        self, entity: str, from_status: str, to_status: str, allowed: list[str]
    ):
        self.entity = entity
        self.from_status = from_status
        self.to_status = to_status
        self.allowed = allowed
        detail = ", ".join(allowed) if allowed else "none (terminal state)"
        super().__init__(
            f"{entity}: cannot transition from {from_status} to {to_status}. "
            f"Allowed: [{detail}]"
        )


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass
class Member:
    """The insured person. Holds one or more policies."""

    name: str
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)


@dataclass
class Policy:
    """An insurance plan for a member.

    Defines the annual deductible and a validity window. Coverage details
    are in CoverageRule rows linked to this policy.
    """

    member_id: str
    policy_number: str
    effective_date: date
    end_date: date
    annual_deductible: Decimal = Decimal("0")
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)


@dataclass
class CoverageRule:
    """One coverage rule within a policy.

    Defines whether a service type is covered and under what terms.
    The adjudication engine looks up the matching rule for each line item's
    service type and applies it.

    Example: "LAB_WORK is covered at 80%, up to $1000/year, $200/visit"
    """

    policy_id: str
    service_type: ServiceType
    is_covered: bool = True
    coinsurance_rate: Decimal = Decimal("0.80")
    annual_limit: Decimal = Decimal("0")
    per_visit_limit: Optional[Decimal] = None
    id: str = field(default_factory=_new_id)


@dataclass
class Claim:
    """A reimbursement request submitted by a member.

    Contains one or more ClaimLineItems. The top-level status is derived
    from line item outcomes after adjudication.
    """

    member_id: str
    policy_id: str
    provider: str
    diagnosis_code: str
    line_items: list[ClaimLineItem] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.SUBMITTED
    id: str = field(default_factory=_new_id)
    submitted_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def can_transition_to(self, new_status: ClaimStatus) -> bool:
        """Check whether a transition is valid without performing it."""
        return new_status in CLAIM_TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status: ClaimStatus) -> None:
        """Move the claim to a new state, enforcing the state machine.

        Raises InvalidTransitionError if the transition is not allowed.
        """
        if not self.can_transition_to(new_status):
            allowed = CLAIM_TRANSITIONS.get(self.status, set())
            raise InvalidTransitionError(
                entity="Claim",
                from_status=self.status.value,
                to_status=new_status.value,
                allowed=[s.value for s in sorted(allowed, key=lambda s: s.value)],
            )
        self.status = new_status
        self.updated_at = _now()

    def derive_status(self) -> ClaimStatus:
        """Compute the claim-level status from line item outcomes.

        All APPROVED  → APPROVED
        All DENIED    → DENIED
        Mixed         → PARTIAL
        """
        if not self.line_items:
            return self.status

        statuses = {li.status for li in self.line_items}

        if statuses == {LineItemStatus.APPROVED}:
            return ClaimStatus.APPROVED
        if statuses == {LineItemStatus.DENIED}:
            return ClaimStatus.DENIED
        if LineItemStatus.PENDING in statuses:
            return ClaimStatus.PROCESSING
        return ClaimStatus.PARTIAL


@dataclass
class ClaimLineItem:
    """One billable service on a claim. Adjudicated independently.

    After adjudication:
    - APPROVED items have amount_allowed set (may be less than amount_charged)
    - DENIED items have denial_reason set
    """

    claim_id: str
    service_type: ServiceType
    service_date: date
    amount_charged: Decimal
    amount_allowed: Decimal = Decimal("0")
    status: LineItemStatus = LineItemStatus.PENDING
    denial_reason: Optional[str] = None
    id: str = field(default_factory=_new_id)

    def can_transition_to(self, new_status: LineItemStatus) -> bool:
        """Check whether a transition is valid without performing it."""
        return new_status in LINE_ITEM_TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status: LineItemStatus) -> None:
        """Move the line item to a new state, enforcing the state machine.

        Raises InvalidTransitionError if the transition is not allowed.
        """
        if not self.can_transition_to(new_status):
            allowed = LINE_ITEM_TRANSITIONS.get(self.status, set())
            raise InvalidTransitionError(
                entity="ClaimLineItem",
                from_status=self.status.value,
                to_status=new_status.value,
                allowed=[s.value for s in sorted(allowed, key=lambda s: s.value)],
            )
        self.status = new_status

    def approve(self, amount_allowed: Decimal) -> None:
        """Convenience: mark this line item as approved with a payout amount."""
        self.transition_to(LineItemStatus.APPROVED)
        self.amount_allowed = amount_allowed

    def deny(self, reason: str) -> None:
        """Convenience: mark this line item as denied with an explanation."""
        self.transition_to(LineItemStatus.DENIED)
        self.denial_reason = reason


@dataclass
class Accumulator:
    """Tracks how much of a limit or deductible has been consumed in a plan year.

    One row per (policy, service_type, year).
    A row with service_type=None tracks the overall annual deductible.
    """

    policy_id: str
    year: int
    amount_used: Decimal = Decimal("0")
    service_type: Optional[ServiceType] = None
    id: str = field(default_factory=_new_id)

    @property
    def is_deductible_tracker(self) -> bool:
        return self.service_type is None

    def apply(self, amount: Decimal) -> None:
        """Add to the running total."""
        self.amount_used += amount

    def remaining(self, limit: Decimal) -> Decimal:
        """How much of the limit is still available."""
        return max(Decimal("0"), limit - self.amount_used)


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionExplanation:
    """Structured explanation for an adjudication decision.

    Two audiences:
        - member_explanation: plain-English for the insured person
        - rule_trace: step-by-step processing log for internal reviewers

    Includes financial context so callers don't have to recompute.
    """

    reason_code: str
    member_explanation: str
    rule_trace: tuple[str, ...]
    deductible_applied: Decimal = Decimal("0")
    remaining_annual_benefit: Optional[Decimal] = None


@dataclass(frozen=True)
class AdjudicationResult:
    """The outcome of adjudicating a single line item.

    Returned by the adjudication engine, then applied to the ClaimLineItem.
    Frozen (immutable) because a decision, once made, doesn't change.
    """

    line_item_id: str
    status: LineItemStatus
    amount_allowed: Decimal
    denial_reason: Optional[str] = None
    explanation: DecisionExplanation = None  # type: ignore[assignment]

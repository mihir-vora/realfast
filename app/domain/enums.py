"""
Enums for the claims processing domain.

Three enums cover the vocabulary of the system:
- ServiceType: what kind of medical service was rendered
- ClaimStatus: where a claim is in its lifecycle
- LineItemStatus: where a single line item is in adjudication
"""

from enum import Enum


class ServiceType(str, Enum):
    """Types of medical services that can appear on a claim.

    Each maps to a CoverageRule on the member's policy. Kept intentionally
    small — a real system would have hundreds; six is enough to demonstrate
    the model.
    """

    OFFICE_VISIT = "OFFICE_VISIT"
    LAB_WORK = "LAB_WORK"
    IMAGING = "IMAGING"
    GENERIC_RX = "GENERIC_RX"
    SPECIALIST = "SPECIALIST"
    EMERGENCY = "EMERGENCY"


class ClaimStatus(str, Enum):
    """Lifecycle states for a claim.

    State machine:
        SUBMITTED → PROCESSING → APPROVED / DENIED / PARTIAL → PAID

    APPROVED / PARTIAL can transition to PAID.
    DENIED is terminal.
    The claim-level status is derived from its line item outcomes.
    """

    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


# Valid state transitions — used by Claim.transition_to()
CLAIM_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.SUBMITTED: {ClaimStatus.PROCESSING},
    ClaimStatus.PROCESSING: {ClaimStatus.APPROVED, ClaimStatus.DENIED, ClaimStatus.PARTIAL},
    ClaimStatus.APPROVED: {ClaimStatus.PAID},
    ClaimStatus.PARTIAL: {ClaimStatus.PAID},
    ClaimStatus.DENIED: set(),
    ClaimStatus.PAID: set(),
}


class LineItemStatus(str, Enum):
    """Lifecycle states for a single line item.

    State machine:
        PENDING → APPROVED / DENIED

    No intermediate states. The adjudication engine resolves each line item
    in a single pass.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


LINE_ITEM_TRANSITIONS: dict[LineItemStatus, set[LineItemStatus]] = {
    LineItemStatus.PENDING: {LineItemStatus.APPROVED, LineItemStatus.DENIED},
    LineItemStatus.APPROVED: set(),
    LineItemStatus.DENIED: set(),
}

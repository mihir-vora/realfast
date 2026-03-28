"""
Tests for claim and line-item state machine transitions.

Covers:
- Every valid transition
- Every invalid transition (including terminal states)
- can_transition_to() helper
- Claim.derive_status() from line item outcomes
- ClaimLineItem convenience methods (approve / deny)
"""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.entities import Claim, ClaimLineItem, InvalidTransitionError
from app.domain.enums import ClaimStatus, LineItemStatus, ServiceType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(**overrides) -> Claim:
    defaults = dict(
        member_id="m1",
        policy_id="p1",
        provider="Dr. Smith",
        diagnosis_code="J06.9",
    )
    defaults.update(overrides)
    return Claim(**defaults)


def _make_line_item(**overrides) -> ClaimLineItem:
    defaults = dict(
        claim_id="c1",
        service_type=ServiceType.LAB_WORK,
        service_date=date(2026, 1, 15),
        amount_charged=Decimal("200.00"),
    )
    defaults.update(overrides)
    return ClaimLineItem(**defaults)


# ===================================================================
# Claim transitions
# ===================================================================


class TestClaimTransitions:
    """Claim lifecycle: SUBMITTED → PROCESSING → APPROVED/DENIED/PARTIAL → PAID"""

    def test_submitted_to_processing(self):
        claim = _make_claim()
        claim.transition_to(ClaimStatus.PROCESSING)
        assert claim.status == ClaimStatus.PROCESSING

    def test_processing_to_approved(self):
        claim = _make_claim(status=ClaimStatus.PROCESSING)
        claim.transition_to(ClaimStatus.APPROVED)
        assert claim.status == ClaimStatus.APPROVED

    def test_processing_to_denied(self):
        claim = _make_claim(status=ClaimStatus.PROCESSING)
        claim.transition_to(ClaimStatus.DENIED)
        assert claim.status == ClaimStatus.DENIED

    def test_processing_to_partial(self):
        claim = _make_claim(status=ClaimStatus.PROCESSING)
        claim.transition_to(ClaimStatus.PARTIAL)
        assert claim.status == ClaimStatus.PARTIAL

    def test_approved_to_paid(self):
        claim = _make_claim(status=ClaimStatus.APPROVED)
        claim.transition_to(ClaimStatus.PAID)
        assert claim.status == ClaimStatus.PAID

    def test_partial_to_paid(self):
        claim = _make_claim(status=ClaimStatus.PARTIAL)
        claim.transition_to(ClaimStatus.PAID)
        assert claim.status == ClaimStatus.PAID

    # -- Invalid transitions --

    def test_cannot_skip_processing(self):
        claim = _make_claim()
        with pytest.raises(InvalidTransitionError, match="SUBMITTED.*APPROVED"):
            claim.transition_to(ClaimStatus.APPROVED)

    def test_cannot_go_backwards(self):
        claim = _make_claim(status=ClaimStatus.PROCESSING)
        with pytest.raises(InvalidTransitionError, match="PROCESSING.*SUBMITTED"):
            claim.transition_to(ClaimStatus.SUBMITTED)

    def test_denied_is_terminal(self):
        claim = _make_claim(status=ClaimStatus.DENIED)
        with pytest.raises(InvalidTransitionError, match="terminal"):
            claim.transition_to(ClaimStatus.PAID)

    def test_paid_is_terminal(self):
        claim = _make_claim(status=ClaimStatus.PAID)
        with pytest.raises(InvalidTransitionError, match="terminal"):
            claim.transition_to(ClaimStatus.SUBMITTED)

    def test_transition_updates_timestamp(self):
        claim = _make_claim()
        original = claim.updated_at
        claim.transition_to(ClaimStatus.PROCESSING)
        assert claim.updated_at >= original


class TestClaimCanTransitionTo:
    def test_valid_transition_returns_true(self):
        claim = _make_claim()
        assert claim.can_transition_to(ClaimStatus.PROCESSING) is True

    def test_invalid_transition_returns_false(self):
        claim = _make_claim()
        assert claim.can_transition_to(ClaimStatus.PAID) is False

    def test_terminal_state_returns_false_for_everything(self):
        claim = _make_claim(status=ClaimStatus.DENIED)
        for status in ClaimStatus:
            assert claim.can_transition_to(status) is False


# ===================================================================
# Claim.derive_status()
# ===================================================================


class TestClaimDeriveStatus:
    def test_all_approved(self):
        claim = _make_claim()
        claim.line_items = [
            _make_line_item(status=LineItemStatus.APPROVED),
            _make_line_item(status=LineItemStatus.APPROVED),
        ]
        assert claim.derive_status() == ClaimStatus.APPROVED

    def test_all_denied(self):
        claim = _make_claim()
        claim.line_items = [
            _make_line_item(status=LineItemStatus.DENIED),
            _make_line_item(status=LineItemStatus.DENIED),
        ]
        assert claim.derive_status() == ClaimStatus.DENIED

    def test_mixed_is_partial(self):
        claim = _make_claim()
        claim.line_items = [
            _make_line_item(status=LineItemStatus.APPROVED),
            _make_line_item(status=LineItemStatus.DENIED),
        ]
        assert claim.derive_status() == ClaimStatus.PARTIAL

    def test_pending_items_means_processing(self):
        claim = _make_claim()
        claim.line_items = [
            _make_line_item(status=LineItemStatus.APPROVED),
            _make_line_item(status=LineItemStatus.PENDING),
        ]
        assert claim.derive_status() == ClaimStatus.PROCESSING

    def test_no_line_items_keeps_current_status(self):
        claim = _make_claim(status=ClaimStatus.SUBMITTED)
        assert claim.derive_status() == ClaimStatus.SUBMITTED


# ===================================================================
# Line item transitions
# ===================================================================


class TestLineItemTransitions:
    """Line item lifecycle: PENDING → APPROVED / DENIED"""

    def test_pending_to_approved(self):
        li = _make_line_item()
        li.transition_to(LineItemStatus.APPROVED)
        assert li.status == LineItemStatus.APPROVED

    def test_pending_to_denied(self):
        li = _make_line_item()
        li.transition_to(LineItemStatus.DENIED)
        assert li.status == LineItemStatus.DENIED

    def test_cannot_go_backwards_from_approved(self):
        li = _make_line_item(status=LineItemStatus.APPROVED)
        with pytest.raises(InvalidTransitionError, match="terminal"):
            li.transition_to(LineItemStatus.PENDING)

    def test_cannot_go_backwards_from_denied(self):
        li = _make_line_item(status=LineItemStatus.DENIED)
        with pytest.raises(InvalidTransitionError, match="terminal"):
            li.transition_to(LineItemStatus.PENDING)

    def test_cannot_switch_between_terminal_states(self):
        li = _make_line_item(status=LineItemStatus.APPROVED)
        with pytest.raises(InvalidTransitionError):
            li.transition_to(LineItemStatus.DENIED)


class TestLineItemCanTransitionTo:
    def test_pending_can_go_to_approved(self):
        li = _make_line_item()
        assert li.can_transition_to(LineItemStatus.APPROVED) is True

    def test_pending_can_go_to_denied(self):
        li = _make_line_item()
        assert li.can_transition_to(LineItemStatus.DENIED) is True

    def test_approved_is_terminal(self):
        li = _make_line_item(status=LineItemStatus.APPROVED)
        for status in LineItemStatus:
            assert li.can_transition_to(status) is False

    def test_denied_is_terminal(self):
        li = _make_line_item(status=LineItemStatus.DENIED)
        for status in LineItemStatus:
            assert li.can_transition_to(status) is False


# ===================================================================
# Line item convenience methods
# ===================================================================


class TestLineItemConvenienceMethods:
    def test_approve_sets_status_and_amount(self):
        li = _make_line_item()
        li.approve(Decimal("160.00"))
        assert li.status == LineItemStatus.APPROVED
        assert li.amount_allowed == Decimal("160.00")

    def test_deny_sets_status_and_reason(self):
        li = _make_line_item()
        li.deny("Service type IMAGING is not covered under this policy")
        assert li.status == LineItemStatus.DENIED
        assert li.denial_reason == "Service type IMAGING is not covered under this policy"

    def test_approve_rejects_if_already_denied(self):
        li = _make_line_item(status=LineItemStatus.DENIED)
        with pytest.raises(InvalidTransitionError):
            li.approve(Decimal("100.00"))

    def test_deny_rejects_if_already_approved(self):
        li = _make_line_item(status=LineItemStatus.APPROVED)
        with pytest.raises(InvalidTransitionError):
            li.deny("too late")


# ===================================================================
# InvalidTransitionError structure
# ===================================================================


class TestInvalidTransitionError:
    def test_error_contains_useful_fields(self):
        claim = _make_claim(status=ClaimStatus.DENIED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            claim.transition_to(ClaimStatus.PAID)
        err = exc_info.value
        assert err.entity == "Claim"
        assert err.from_status == "DENIED"
        assert err.to_status == "PAID"
        assert err.allowed == []

    def test_error_message_is_human_readable(self):
        li = _make_line_item(status=LineItemStatus.APPROVED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            li.transition_to(LineItemStatus.PENDING)
        assert "ClaimLineItem" in str(exc_info.value)
        assert "APPROVED" in str(exc_info.value)
        assert "PENDING" in str(exc_info.value)

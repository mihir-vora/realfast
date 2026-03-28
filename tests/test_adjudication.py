"""
Tests for the adjudication engine.

Scenarios covered:
    1. Fully covered service  →  APPROVED with coinsurance applied
    2. Service not covered (no rule)  →  DENIED
    3. Service explicitly excluded (is_covered=False)  →  DENIED
    4. Deductible partially absorbs amount  →  APPROVED with reduced payout
    5. Deductible absorbs entire amount  →  APPROVED with $0 payout
    6. Per-visit limit caps payout  →  APPROVED with capped amount
    7. Annual limit partially caps payout  →  APPROVED with reduced amount
    8. Annual limit fully exhausted  →  DENIED
    9. Multiple line items deplete same annual limit across a claim
   10. Mixed claim (some approved, some denied)  →  claim status = PARTIAL
   11. All denied  →  claim status = DENIED
   12. All approved  →  claim status = APPROVED
   13. Explanation strings are human-readable
"""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.adjudication import adjudicate_claim, adjudicate_line_item
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
# Fixtures — reusable building blocks
# ---------------------------------------------------------------------------


def _policy(**overrides) -> Policy:
    defaults = dict(
        member_id="m1",
        policy_number="POL-001",
        effective_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        annual_deductible=Decimal("0"),
    )
    defaults.update(overrides)
    return Policy(**defaults)


def _rule(service_type: ServiceType = ServiceType.LAB_WORK, **overrides) -> CoverageRule:
    defaults = dict(
        policy_id="p1",
        service_type=service_type,
        is_covered=True,
        coinsurance_rate=Decimal("0.80"),
        annual_limit=Decimal("0"),
        per_visit_limit=None,
    )
    defaults.update(overrides)
    return CoverageRule(**defaults)


def _line_item(
    service_type: ServiceType = ServiceType.LAB_WORK,
    amount: str = "200.00",
    **overrides,
) -> ClaimLineItem:
    defaults = dict(
        claim_id="c1",
        service_type=service_type,
        service_date=date(2026, 3, 15),
        amount_charged=Decimal(amount),
    )
    defaults.update(overrides)
    return ClaimLineItem(**defaults)


def _deductible_acc(used: str = "0") -> Accumulator:
    return Accumulator(policy_id="p1", year=2026, amount_used=Decimal(used))


def _service_acc(
    service_type: ServiceType = ServiceType.LAB_WORK, used: str = "0"
) -> Accumulator:
    return Accumulator(
        policy_id="p1", year=2026, service_type=service_type,
        amount_used=Decimal(used),
    )


def _claim(**overrides) -> Claim:
    defaults = dict(
        member_id="m1",
        policy_id="p1",
        provider="Dr. Smith",
        diagnosis_code="J06.9",
    )
    defaults.update(overrides)
    return Claim(**defaults)


# ===================================================================
# Line-item level tests
# ===================================================================


class TestCoverageCheck:
    """Step 1: does a coverage rule exist and is it active?"""

    def test_no_rule_means_denied(self):
        li = _line_item(service_type=ServiceType.IMAGING)
        result = adjudicate_line_item(
            li, rule=None, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.status == LineItemStatus.DENIED
        assert "not covered" in result.denial_reason

    def test_explicitly_excluded_means_denied(self):
        li = _line_item()
        rule = _rule(is_covered=False)
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.status == LineItemStatus.DENIED
        assert "excluded" in result.denial_reason


class TestBasicApproval:
    """Covered service with no deductible, no limits — just coinsurance."""

    def test_80_percent_coinsurance(self):
        li = _line_item(amount="100.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"))
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.status == LineItemStatus.APPROVED
        assert result.amount_allowed == Decimal("80.00")

    def test_100_percent_coinsurance(self):
        li = _line_item(amount="250.00")
        rule = _rule(coinsurance_rate=Decimal("1.00"))
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.amount_allowed == Decimal("250.00")

    def test_50_percent_coinsurance(self):
        li = _line_item(amount="300.00")
        rule = _rule(coinsurance_rate=Decimal("0.50"))
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.amount_allowed == Decimal("150.00")


class TestDeductible:
    """Step 2: annual deductible reduces the amount before coinsurance."""

    def test_deductible_partially_applied(self):
        li = _line_item(amount="500.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"))
        policy = _policy(annual_deductible=Decimal("200.00"))
        result = adjudicate_line_item(
            li, rule=rule, policy=policy,
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        # $500 charged - $200 deductible = $300 subject to coinsurance
        # 80% of $300 = $240
        assert result.status == LineItemStatus.APPROVED
        assert result.amount_allowed == Decimal("240.00")

    def test_deductible_absorbs_entire_amount(self):
        li = _line_item(amount="100.00")
        policy = _policy(annual_deductible=Decimal("500.00"))
        result = adjudicate_line_item(
            li, rule=_rule(), policy=policy,
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        # $100 < $500 deductible → entire amount goes to deductible
        assert result.status == LineItemStatus.APPROVED
        assert result.amount_allowed == Decimal("0")
        assert any("deductible" in s.lower() for s in result.explanation)

    def test_deductible_already_partially_met(self):
        li = _line_item(amount="300.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"))
        policy = _policy(annual_deductible=Decimal("500.00"))
        # Member has already paid $400 of $500 deductible
        ded_acc = _deductible_acc(used="400.00")
        result = adjudicate_line_item(
            li, rule=rule, policy=policy,
            deductible_acc=ded_acc, service_acc=_service_acc(),
        )
        # Remaining deductible: $100.  $300 - $100 = $200 subject to coinsurance
        # 80% of $200 = $160
        assert result.amount_allowed == Decimal("160.00")
        assert ded_acc.amount_used == Decimal("500.00")

    def test_deductible_already_fully_met(self):
        li = _line_item(amount="200.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"))
        policy = _policy(annual_deductible=Decimal("500.00"))
        ded_acc = _deductible_acc(used="500.00")
        result = adjudicate_line_item(
            li, rule=rule, policy=policy,
            deductible_acc=ded_acc, service_acc=_service_acc(),
        )
        # Deductible fully met → full coinsurance: 80% of $200 = $160
        assert result.amount_allowed == Decimal("160.00")


class TestPerVisitLimit:
    """Step 4: per-visit limit caps the plan's payout on a single item."""

    def test_payout_capped_at_per_visit_limit(self):
        li = _line_item(amount="500.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"), per_visit_limit=Decimal("150.00"))
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        # 80% of $500 = $400, but per-visit limit caps at $150
        assert result.amount_allowed == Decimal("150.00")
        assert any("per-visit" in s.lower() for s in result.explanation)

    def test_payout_below_per_visit_limit_not_capped(self):
        li = _line_item(amount="100.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"), per_visit_limit=Decimal("150.00"))
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        # 80% of $100 = $80, below the $150 cap → no capping
        assert result.amount_allowed == Decimal("80.00")


class TestAnnualLimit:
    """Step 5: annual limit caps total plan payouts per service type per year."""

    def test_payout_capped_at_remaining_annual_limit(self):
        li = _line_item(amount="500.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"), annual_limit=Decimal("1000.00"))
        svc_acc = _service_acc(used="800.00")
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=svc_acc,
        )
        # 80% of $500 = $400, but only $200 remaining in annual limit
        assert result.amount_allowed == Decimal("200.00")
        assert svc_acc.amount_used == Decimal("1000.00")
        assert any("annual limit" in s.lower() for s in result.explanation)

    def test_annual_limit_exhausted_means_denied(self):
        li = _line_item(amount="200.00")
        rule = _rule(annual_limit=Decimal("500.00"))
        svc_acc = _service_acc(used="500.00")
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=svc_acc,
        )
        assert result.status == LineItemStatus.DENIED
        assert "exhausted" in result.denial_reason

    def test_no_annual_limit_means_unlimited(self):
        """annual_limit=0 means no cap — plan pays without limit tracking."""
        li = _line_item(amount="10000.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"), annual_limit=Decimal("0"))
        result = adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.status == LineItemStatus.APPROVED
        assert result.amount_allowed == Decimal("8000.00")


class TestAccumulatorUpdates:
    """Verify that accumulators are mutated correctly during adjudication."""

    def test_deductible_accumulator_updated(self):
        li = _line_item(amount="300.00")
        policy = _policy(annual_deductible=Decimal("200.00"))
        ded_acc = _deductible_acc()
        adjudicate_line_item(
            li, rule=_rule(), policy=policy,
            deductible_acc=ded_acc, service_acc=_service_acc(),
        )
        assert ded_acc.amount_used == Decimal("200.00")

    def test_service_accumulator_updated(self):
        li = _line_item(amount="200.00")
        rule = _rule(coinsurance_rate=Decimal("0.80"), annual_limit=Decimal("1000.00"))
        svc_acc = _service_acc()
        adjudicate_line_item(
            li, rule=rule, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=svc_acc,
        )
        # 80% of $200 = $160
        assert svc_acc.amount_used == Decimal("160.00")


# ===================================================================
# Combined: deductible + per-visit + annual limit
# ===================================================================


class TestCombinedRules:
    """Multiple rules interacting on a single line item."""

    def test_deductible_then_coinsurance_then_per_visit_cap(self):
        li = _line_item(amount="1000.00")
        rule = _rule(
            coinsurance_rate=Decimal("0.80"),
            per_visit_limit=Decimal("200.00"),
        )
        policy = _policy(annual_deductible=Decimal("100.00"))
        result = adjudicate_line_item(
            li, rule=rule, policy=policy,
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        # $1000 - $100 deductible = $900
        # 80% of $900 = $720
        # Per-visit cap: $200
        assert result.amount_allowed == Decimal("200.00")

    def test_deductible_then_coinsurance_then_annual_cap(self):
        li = _line_item(amount="1000.00")
        rule = _rule(
            coinsurance_rate=Decimal("0.80"),
            annual_limit=Decimal("500.00"),
        )
        policy = _policy(annual_deductible=Decimal("200.00"))
        svc_acc = _service_acc(used="200.00")
        result = adjudicate_line_item(
            li, rule=rule, policy=policy,
            deductible_acc=_deductible_acc(), service_acc=svc_acc,
        )
        # $1000 - $200 deductible = $800
        # 80% of $800 = $640
        # Annual limit remaining: $500 - $200 = $300 → capped to $300
        assert result.amount_allowed == Decimal("300.00")


# ===================================================================
# Claim-level adjudication
# ===================================================================


class TestAdjudicateClaim:
    def test_all_approved(self):
        claim = _claim()
        claim.line_items = [
            _line_item(service_type=ServiceType.LAB_WORK, amount="100.00"),
            _line_item(service_type=ServiceType.OFFICE_VISIT, amount="50.00"),
        ]
        policy = _policy()
        rules = [
            _rule(ServiceType.LAB_WORK, coinsurance_rate=Decimal("0.80")),
            _rule(ServiceType.OFFICE_VISIT, coinsurance_rate=Decimal("0.80")),
        ]
        results = adjudicate_claim(claim, policy, rules, {})
        assert len(results) == 2
        assert all(r.status == LineItemStatus.APPROVED for r in results)
        assert claim.status == ClaimStatus.APPROVED

    def test_all_denied(self):
        claim = _claim()
        claim.line_items = [
            _line_item(service_type=ServiceType.IMAGING, amount="100.00"),
        ]
        # No coverage rule for IMAGING → denied
        results = adjudicate_claim(claim, _policy(), [], {})
        assert results[0].status == LineItemStatus.DENIED
        assert claim.status == ClaimStatus.DENIED

    def test_mixed_gives_partial(self):
        claim = _claim()
        claim.line_items = [
            _line_item(service_type=ServiceType.LAB_WORK, amount="100.00"),
            _line_item(service_type=ServiceType.IMAGING, amount="200.00"),
        ]
        rules = [_rule(ServiceType.LAB_WORK)]  # No rule for IMAGING
        results = adjudicate_claim(claim, _policy(), rules, {})
        assert results[0].status == LineItemStatus.APPROVED
        assert results[1].status == LineItemStatus.DENIED
        assert claim.status == ClaimStatus.PARTIAL

    def test_line_items_share_accumulators(self):
        """Two line items of the same service type should deplete the same limit."""
        claim = _claim()
        claim.line_items = [
            _line_item(service_type=ServiceType.LAB_WORK, amount="400.00"),
            _line_item(service_type=ServiceType.LAB_WORK, amount="400.00"),
        ]
        rule = _rule(
            ServiceType.LAB_WORK,
            coinsurance_rate=Decimal("1.00"),
            annual_limit=Decimal("500.00"),
        )
        accumulators: dict = {}
        results = adjudicate_claim(claim, _policy(), [rule], accumulators)

        # First item: $400 (within $500 limit) → approved $400
        assert results[0].amount_allowed == Decimal("400.00")
        # Second item: $400 but only $100 remaining → approved $100
        assert results[1].amount_allowed == Decimal("100.00")
        assert accumulators[ServiceType.LAB_WORK].amount_used == Decimal("500.00")

    def test_line_items_share_deductible(self):
        """Two line items should both contribute to meeting the deductible."""
        claim = _claim()
        claim.line_items = [
            _line_item(service_type=ServiceType.LAB_WORK, amount="100.00"),
            _line_item(service_type=ServiceType.OFFICE_VISIT, amount="200.00"),
        ]
        policy = _policy(annual_deductible=Decimal("150.00"))
        rules = [
            _rule(ServiceType.LAB_WORK, coinsurance_rate=Decimal("1.00")),
            _rule(ServiceType.OFFICE_VISIT, coinsurance_rate=Decimal("1.00")),
        ]
        results = adjudicate_claim(claim, policy, rules, {})

        # First: $100 charged, $100 goes to deductible → plan pays $0
        assert results[0].amount_allowed == Decimal("0")
        # Second: $200 charged, $50 goes to deductible (now $150 met), plan pays $150
        assert results[1].amount_allowed == Decimal("150.00")


# ===================================================================
# Explanation quality
# ===================================================================


class TestExplanations:
    def test_approved_has_explanation_steps(self):
        li = _line_item(amount="200.00")
        result = adjudicate_line_item(
            li, rule=_rule(), policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert len(result.explanation) >= 2
        assert any("billed" in s.lower() for s in result.explanation)
        assert any("plan pays" in s.lower() for s in result.explanation)

    def test_denied_has_clear_reason(self):
        li = _line_item(service_type=ServiceType.EMERGENCY)
        result = adjudicate_line_item(
            li, rule=None, policy=_policy(),
            deductible_acc=_deductible_acc(), service_acc=_service_acc(),
        )
        assert result.denial_reason is not None
        assert "EMERGENCY" in result.denial_reason
        assert "not covered" in result.denial_reason

    def test_deductible_explanation_shows_progress(self):
        li = _line_item(amount="300.00")
        policy = _policy(annual_deductible=Decimal("500.00"))
        result = adjudicate_line_item(
            li, rule=_rule(), policy=policy,
            deductible_acc=_deductible_acc(used="100.00"), service_acc=_service_acc(),
        )
        # Find the main deductible step (the one showing member pays X)
        ded_step = [s for s in result.explanation if "member pays" in s.lower()]
        assert len(ded_step) == 1
        assert "$400.00" in ded_step[0]  # $100 existing + $300 applied = $400 met
        assert "$500.00" in ded_step[0]  # of $500 total

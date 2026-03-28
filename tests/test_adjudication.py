"""
Tests for the adjudication engine.

Scenarios covered:
    Single-claim:
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

    Multi-claim (accumulators persist across claims):
    14. First claim consumes part of deductible, second sees remainder
    15. Deductible fully met by first claim, second gets full coinsurance
    16. Annual limit decreases across claims
    17. Annual limit exhausted by prior claims → denial
    18. Benefit summary reflects accumulated usage
"""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.adjudication import (
    adjudicate_claim,
    adjudicate_line_item,
    get_benefit_summary,
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


# ===================================================================
# Multi-claim accumulation
# ===================================================================
#
# These tests simulate the real workflow: submit claim 1, then claim 2,
# with the SAME accumulators dict passed to both calls.  This proves
# that deductible and annual-limit tracking work across claims, not
# just within a single claim.
# ===================================================================


class TestMultiClaimDeductible:
    """Deductible consumption across sequential claims."""

    def _shared_setup(self):
        """Two claims against the same $500 deductible, 100% coinsurance."""
        policy = _policy(annual_deductible=Decimal("500.00"))
        rules = [_rule(ServiceType.LAB_WORK, coinsurance_rate=Decimal("1.00"))]
        accumulators: dict = {}
        return policy, rules, accumulators

    def test_first_claim_consumes_partial_deductible(self):
        policy, rules, accumulators = self._shared_setup()

        claim1 = _claim()
        claim1.line_items = [_line_item(amount="200.00")]
        results1 = adjudicate_claim(claim1, policy, rules, accumulators)

        # $200 goes to deductible → plan pays $0
        assert results1[0].amount_allowed == Decimal("0")
        assert accumulators[None].amount_used == Decimal("200.00")

    def test_second_claim_sees_reduced_deductible(self):
        policy, rules, accumulators = self._shared_setup()

        # Claim 1: $200 → all to deductible
        claim1 = _claim()
        claim1.line_items = [_line_item(amount="200.00")]
        adjudicate_claim(claim1, policy, rules, accumulators)

        # Claim 2: $400 → $300 to deductible (meeting $500), plan pays $100
        claim2 = _claim()
        claim2.line_items = [_line_item(amount="400.00")]
        results2 = adjudicate_claim(claim2, policy, rules, accumulators)

        assert results2[0].amount_allowed == Decimal("100.00")
        assert accumulators[None].amount_used == Decimal("500.00")

    def test_third_claim_deductible_already_met(self):
        policy, rules, accumulators = self._shared_setup()

        # Claim 1: $300 → all to deductible
        claim1 = _claim()
        claim1.line_items = [_line_item(amount="300.00")]
        adjudicate_claim(claim1, policy, rules, accumulators)

        # Claim 2: $300 → $200 to deductible (now met), plan pays $100
        claim2 = _claim()
        claim2.line_items = [_line_item(amount="300.00")]
        adjudicate_claim(claim2, policy, rules, accumulators)

        # Claim 3: $150 → deductible fully met, plan pays full $150
        claim3 = _claim()
        claim3.line_items = [_line_item(amount="150.00")]
        results3 = adjudicate_claim(claim3, policy, rules, accumulators)

        assert results3[0].amount_allowed == Decimal("150.00")
        assert accumulators[None].amount_used == Decimal("500.00")


class TestMultiClaimAnnualLimit:
    """Annual benefit exhaustion across sequential claims."""

    def _shared_setup(self):
        """Two claims against a $1000 annual limit for LAB_WORK, 100% coinsurance."""
        policy = _policy()
        rules = [_rule(
            ServiceType.LAB_WORK,
            coinsurance_rate=Decimal("1.00"),
            annual_limit=Decimal("1000.00"),
        )]
        accumulators: dict = {}
        return policy, rules, accumulators

    def test_annual_benefit_decreases_across_claims(self):
        policy, rules, accumulators = self._shared_setup()

        # Claim 1: $400 → approved, $600 remaining
        claim1 = _claim()
        claim1.line_items = [_line_item(amount="400.00")]
        results1 = adjudicate_claim(claim1, policy, rules, accumulators)
        assert results1[0].amount_allowed == Decimal("400.00")

        # Claim 2: $400 → approved, $200 remaining
        claim2 = _claim()
        claim2.line_items = [_line_item(amount="400.00")]
        results2 = adjudicate_claim(claim2, policy, rules, accumulators)
        assert results2[0].amount_allowed == Decimal("400.00")

        assert accumulators[ServiceType.LAB_WORK].amount_used == Decimal("800.00")

    def test_claim_partially_paid_when_limit_nearly_exhausted(self):
        policy, rules, accumulators = self._shared_setup()

        # Claim 1: $800 → approved
        claim1 = _claim()
        claim1.line_items = [_line_item(amount="800.00")]
        adjudicate_claim(claim1, policy, rules, accumulators)

        # Claim 2: $500 → only $200 remaining → capped at $200
        claim2 = _claim()
        claim2.line_items = [_line_item(amount="500.00")]
        results2 = adjudicate_claim(claim2, policy, rules, accumulators)

        assert results2[0].status == LineItemStatus.APPROVED
        assert results2[0].amount_allowed == Decimal("200.00")
        assert accumulators[ServiceType.LAB_WORK].amount_used == Decimal("1000.00")

    def test_claim_denied_when_limit_fully_exhausted(self):
        policy, rules, accumulators = self._shared_setup()

        # Claim 1: $1000 → approved, exhausts limit
        claim1 = _claim()
        claim1.line_items = [_line_item(amount="1000.00")]
        adjudicate_claim(claim1, policy, rules, accumulators)

        # Claim 2: $100 → denied, limit exhausted
        claim2 = _claim()
        claim2.line_items = [_line_item(amount="100.00")]
        results2 = adjudicate_claim(claim2, policy, rules, accumulators)

        assert results2[0].status == LineItemStatus.DENIED
        assert "exhausted" in results2[0].denial_reason
        assert claim2.status == ClaimStatus.DENIED

    def test_mixed_claim_when_limit_runs_out_mid_claim(self):
        """One line item approved, next denied when limit runs out."""
        policy, rules, accumulators = self._shared_setup()

        # Claim 1: exhaust $900 of $1000
        claim1 = _claim()
        claim1.line_items = [_line_item(amount="900.00")]
        adjudicate_claim(claim1, policy, rules, accumulators)

        # Claim 2: two line items — first gets $100 (remaining), second denied
        claim2 = _claim()
        claim2.line_items = [
            _line_item(amount="300.00"),
            _line_item(amount="200.00"),
        ]
        results2 = adjudicate_claim(claim2, policy, rules, accumulators)

        assert results2[0].status == LineItemStatus.APPROVED
        assert results2[0].amount_allowed == Decimal("100.00")
        assert results2[1].status == LineItemStatus.DENIED
        assert claim2.status == ClaimStatus.PARTIAL


# ===================================================================
# Benefit summary
# ===================================================================


class TestBenefitSummary:
    def test_fresh_policy_shows_full_benefits(self):
        policy = _policy(annual_deductible=Decimal("500.00"))
        rules = [
            _rule(ServiceType.LAB_WORK, annual_limit=Decimal("1000.00")),
            _rule(ServiceType.IMAGING, annual_limit=Decimal("2000.00")),
        ]
        summary = get_benefit_summary(policy, rules, {})

        assert len(summary) == 3  # deductible + 2 service types
        ded = summary[0]
        assert ded.label == "Annual deductible"
        assert ded.remaining == Decimal("500.00")
        assert ded.used == Decimal("0")

    def test_summary_reflects_accumulated_usage(self):
        policy = _policy(annual_deductible=Decimal("500.00"))
        rules = [_rule(ServiceType.LAB_WORK, annual_limit=Decimal("1000.00"))]
        accumulators: dict = {}

        # Submit a claim to consume some benefits
        claim = _claim()
        claim.line_items = [_line_item(amount="300.00")]
        adjudicate_claim(claim, policy, rules, accumulators)

        summary = get_benefit_summary(policy, rules, accumulators)

        ded = next(b for b in summary if b.label == "Annual deductible")
        assert ded.used == Decimal("300.00")
        assert ded.remaining == Decimal("200.00")

    def test_summary_after_limit_exhaustion(self):
        policy = _policy()
        rules = [_rule(
            ServiceType.LAB_WORK,
            coinsurance_rate=Decimal("1.00"),
            annual_limit=Decimal("500.00"),
        )]
        accumulators: dict = {}

        claim = _claim()
        claim.line_items = [_line_item(amount="500.00")]
        adjudicate_claim(claim, policy, rules, accumulators)

        summary = get_benefit_summary(policy, rules, accumulators)
        lab = next(b for b in summary if b.label == "LAB_WORK")
        assert lab.used == Decimal("500.00")
        assert lab.remaining == Decimal("0")

    def test_no_deductible_means_no_deductible_row(self):
        policy = _policy(annual_deductible=Decimal("0"))
        rules = [_rule(ServiceType.LAB_WORK, annual_limit=Decimal("1000.00"))]
        summary = get_benefit_summary(policy, rules, {})
        assert not any(b.label == "Annual deductible" for b in summary)

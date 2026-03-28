"""
Adjudication engine — the core business logic of the claims system.

Pure functions: take domain objects in, return results out. No database,
no HTTP, no side effects beyond mutating the entities passed in.

Flow for each line item:
    1. Find coverage rule  →  no rule / not covered = DENY
    2. Apply deductible    →  member pays remaining deductible first
    3. Apply coinsurance    →  plan pays its percentage
    4. Apply per-visit cap  →  cap payout per line item
    5. Apply annual limit   →  cap payout against yearly maximum
    6. Update accumulators  →  record deductible + plan payout

After all line items: derive claim-level status from outcomes.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.domain.entities import (
    Accumulator,
    AdjudicationResult,
    Claim,
    ClaimLineItem,
    CoverageRule,
    Policy,
)
from app.domain.enums import ClaimStatus, LineItemStatus, ServiceType


def _cents(amount: Decimal) -> Decimal:
    """Round to 2 decimal places (standard currency rounding)."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(amount: Decimal) -> str:
    """Format a decimal as a dollar string for explanations."""
    return f"${_cents(amount)}"


# ---------------------------------------------------------------------------
# Line-item adjudication
# ---------------------------------------------------------------------------


def adjudicate_line_item(
    line_item: ClaimLineItem,
    rule: Optional[CoverageRule],
    policy: Policy,
    deductible_acc: Accumulator,
    service_acc: Accumulator,
) -> AdjudicationResult:
    """Adjudicate a single line item against coverage rules and accumulators.

    This is the heart of the system. Each step either reduces the payable
    amount or denies the item outright. Every decision is recorded in the
    explanation list so the member can see exactly what happened.

    Args:
        line_item: The line item to adjudicate.
        rule: The CoverageRule for this service type (None if no rule exists).
        policy: The member's policy (needed for deductible info).
        deductible_acc: Accumulator tracking annual deductible usage.
        service_acc: Accumulator tracking annual limit usage for this service type.

    Returns:
        An immutable AdjudicationResult with status, amount, and explanation.
    """
    charged = line_item.amount_charged
    steps: list[str] = []

    # -- Step 1: Coverage check ------------------------------------------------

    if rule is None:
        reason = f"{line_item.service_type.value} is not covered under this policy"
        return AdjudicationResult(
            line_item_id=line_item.id,
            status=LineItemStatus.DENIED,
            amount_allowed=Decimal("0"),
            denial_reason=reason,
            explanation=(reason,),
        )

    if not rule.is_covered:
        reason = f"{line_item.service_type.value} is explicitly excluded from coverage"
        return AdjudicationResult(
            line_item_id=line_item.id,
            status=LineItemStatus.DENIED,
            amount_allowed=Decimal("0"),
            denial_reason=reason,
            explanation=(reason,),
        )

    steps.append(f"Billed {_fmt(charged)} for {line_item.service_type.value}")

    payable = charged

    # -- Step 2: Deductible ----------------------------------------------------

    if policy.annual_deductible > 0:
        remaining_ded = deductible_acc.remaining(policy.annual_deductible)
        if remaining_ded > 0:
            ded_applied = min(payable, remaining_ded)
            payable -= ded_applied
            deductible_acc.apply(ded_applied)
            steps.append(
                f"Deductible: member pays {_fmt(ded_applied)} "
                f"({_fmt(deductible_acc.amount_used)} of "
                f"{_fmt(policy.annual_deductible)} annual deductible met)"
            )
            if payable == 0:
                steps.append(
                    "Entire amount applied to deductible — plan pays {_fmt(Decimal('0'))}"
                    .replace("{_fmt(Decimal('0'))}", _fmt(Decimal("0")))
                )
                return AdjudicationResult(
                    line_item_id=line_item.id,
                    status=LineItemStatus.APPROVED,
                    amount_allowed=Decimal("0"),
                    explanation=tuple(steps),
                )

    # -- Step 3: Coinsurance ---------------------------------------------------

    plan_pays = _cents(payable * rule.coinsurance_rate)
    pct = int(rule.coinsurance_rate * 100)
    steps.append(f"Coinsurance: plan pays {pct}% of {_fmt(payable)} = {_fmt(plan_pays)}")

    # -- Step 4: Per-visit limit -----------------------------------------------

    if rule.per_visit_limit is not None and plan_pays > rule.per_visit_limit:
        steps.append(
            f"Per-visit limit: capped from {_fmt(plan_pays)} to "
            f"{_fmt(rule.per_visit_limit)}"
        )
        plan_pays = rule.per_visit_limit

    # -- Step 5: Annual limit --------------------------------------------------

    if rule.annual_limit > 0:
        remaining_limit = service_acc.remaining(rule.annual_limit)

        if remaining_limit <= 0:
            reason = (
                f"Annual limit of {_fmt(rule.annual_limit)} for "
                f"{line_item.service_type.value} exhausted "
                f"({_fmt(service_acc.amount_used)} of {_fmt(rule.annual_limit)} used)"
            )
            steps.append(reason)
            return AdjudicationResult(
                line_item_id=line_item.id,
                status=LineItemStatus.DENIED,
                amount_allowed=Decimal("0"),
                denial_reason=reason,
                explanation=tuple(steps),
            )

        if plan_pays > remaining_limit:
            steps.append(
                f"Annual limit: capped from {_fmt(plan_pays)} to "
                f"{_fmt(remaining_limit)} "
                f"({_fmt(service_acc.amount_used)} of {_fmt(rule.annual_limit)} used)"
            )
            plan_pays = remaining_limit

        service_acc.apply(plan_pays)

    # -- Result ----------------------------------------------------------------

    steps.append(f"Plan pays: {_fmt(plan_pays)}")

    return AdjudicationResult(
        line_item_id=line_item.id,
        status=LineItemStatus.APPROVED,
        amount_allowed=plan_pays,
        explanation=tuple(steps),
    )


# ---------------------------------------------------------------------------
# Claim-level adjudication
# ---------------------------------------------------------------------------


def adjudicate_claim(
    claim: Claim,
    policy: Policy,
    coverage_rules: list[CoverageRule],
    accumulators: dict[Optional[ServiceType], Accumulator],
) -> list[AdjudicationResult]:
    """Adjudicate an entire claim: process every line item, then derive status.

    Orchestration steps:
        1. Transition claim to PROCESSING
        2. For each line item, run adjudicate_line_item()
        3. Apply each result to its line item (approve / deny)
        4. Derive the claim-level status from line item outcomes
        5. Return the list of results

    Accumulators are mutated in-place so that line item N sees the effect of
    line items 1..N-1 (important when multiple items draw from the same limit).

    Missing accumulators are created automatically with amount_used=0.
    """
    rules_by_type: dict[ServiceType, CoverageRule] = {
        r.service_type: r for r in coverage_rules
    }

    claim.transition_to(ClaimStatus.PROCESSING)

    year = claim.submitted_at.year

    results: list[AdjudicationResult] = []
    for li in claim.line_items:
        # Ensure accumulators exist for this line item
        if None not in accumulators:
            accumulators[None] = Accumulator(policy_id=policy.id, year=year)
        if li.service_type not in accumulators:
            accumulators[li.service_type] = Accumulator(
                policy_id=policy.id, year=year, service_type=li.service_type,
            )

        result = adjudicate_line_item(
            line_item=li,
            rule=rules_by_type.get(li.service_type),
            policy=policy,
            deductible_acc=accumulators[None],
            service_acc=accumulators[li.service_type],
        )

        if result.status == LineItemStatus.APPROVED:
            li.approve(result.amount_allowed)
        else:
            li.deny(result.denial_reason or "Denied")

        results.append(result)

    derived = claim.derive_status()
    claim.transition_to(derived)

    return results

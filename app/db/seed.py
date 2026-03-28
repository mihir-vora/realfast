"""
Seed data — creates a sample member, policy, and coverage rules.

Called on startup if the database is empty. Provides a realistic
starting point so the API is immediately usable.

Sample policy: POL-2026-001 for Jane Smith
  - $500 annual deductible
  - 6 coverage rules with varying terms
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CoverageRuleModel, MemberModel, PolicyModel

MEMBER_ID = "m-jane-smith"
POLICY_ID = "p-jane-2026"


def seed_if_empty(db: Session) -> None:
    """Insert sample data only if the members table is empty."""
    if db.query(MemberModel).first() is not None:
        return

    member = MemberModel(id=MEMBER_ID, name="Jane Smith")
    db.add(member)

    policy = PolicyModel(
        id=POLICY_ID,
        member_id=MEMBER_ID,
        policy_number="POL-2026-001",
        effective_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        annual_deductible=Decimal("500.00"),
    )
    db.add(policy)

    rules = [
        CoverageRuleModel(
            policy_id=POLICY_ID,
            service_type="OFFICE_VISIT",
            is_covered=True,
            coinsurance_rate=Decimal("0.80"),
            annual_limit=Decimal("2000.00"),
            per_visit_limit=Decimal("150.00"),
        ),
        CoverageRuleModel(
            policy_id=POLICY_ID,
            service_type="LAB_WORK",
            is_covered=True,
            coinsurance_rate=Decimal("0.80"),
            annual_limit=Decimal("1000.00"),
            per_visit_limit=None,
        ),
        CoverageRuleModel(
            policy_id=POLICY_ID,
            service_type="IMAGING",
            is_covered=True,
            coinsurance_rate=Decimal("0.70"),
            annual_limit=Decimal("1500.00"),
            per_visit_limit=Decimal("500.00"),
        ),
        CoverageRuleModel(
            policy_id=POLICY_ID,
            service_type="GENERIC_RX",
            is_covered=True,
            coinsurance_rate=Decimal("0.90"),
            annual_limit=Decimal("0"),  # unlimited
            per_visit_limit=Decimal("50.00"),
        ),
        CoverageRuleModel(
            policy_id=POLICY_ID,
            service_type="SPECIALIST",
            is_covered=True,
            coinsurance_rate=Decimal("0.60"),
            annual_limit=Decimal("3000.00"),
            per_visit_limit=None,
        ),
        CoverageRuleModel(
            policy_id=POLICY_ID,
            service_type="EMERGENCY",
            is_covered=True,
            coinsurance_rate=Decimal("0.80"),
            annual_limit=Decimal("10000.00"),
            per_visit_limit=None,
        ),
    ]
    db.add_all(rules)

    db.commit()

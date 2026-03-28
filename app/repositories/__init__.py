# Data access layer.
# Abstracts database queries behind a clean interface so the service layer
# doesn't depend on SQLAlchemy directly.

from app.repositories.repository import (  # noqa: F401
    get_accumulators,
    get_all_claims,
    get_claim,
    get_claims_for_member,
    get_coverage_rules,
    get_member,
    get_policy,
    get_policy_for_member,
    save_accumulators,
    save_claim,
)

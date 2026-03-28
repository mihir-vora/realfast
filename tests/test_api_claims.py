"""
Integration tests for claim submission and adjudication APIs.

Uses an in-memory SQLite database so tests are isolated and fast.
Each test gets a fresh database with seed data.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db
from app.db.seed import seed_if_empty, MEMBER_ID
from app.main import app as fastapi_app


@pytest.fixture()
def client():
    """Provide a TestClient backed by a fresh in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    import app.db.models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    db = TestSession()
    seed_if_empty(db)
    db.close()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


VALID_CLAIM = {
    "member_id": MEMBER_ID,
    "provider": "City Medical Center",
    "diagnosis_code": "J06.9",
    "line_items": [
        {
            "service_type": "LAB_WORK",
            "service_date": "2026-03-15",
            "amount_charged": "250.00",
        },
    ],
}


# ===================================================================
# Happy path
# ===================================================================


class TestClaimSubmission:
    def test_submit_claim_returns_201(self, client):
        resp = client.post("/claims", json=VALID_CLAIM)
        assert resp.status_code == 201

    def test_submitted_claim_has_correct_fields(self, client):
        resp = client.post("/claims", json=VALID_CLAIM)
        data = resp.json()
        assert data["member_id"] == MEMBER_ID
        assert data["provider"] == "City Medical Center"
        assert data["diagnosis_code"] == "J06.9"
        assert data["status"] == "SUBMITTED"
        assert "id" in data
        assert "submitted_at" in data

    def test_line_items_are_in_pending_state(self, client):
        resp = client.post("/claims", json=VALID_CLAIM)
        items = resp.json()["line_items"]
        assert len(items) == 1
        assert items[0]["service_type"] == "LAB_WORK"
        assert items[0]["amount_charged"] == "250.00"
        assert items[0]["status"] == "PENDING"
        assert float(items[0]["amount_allowed"]) == 0

    def test_multiple_line_items(self, client):
        payload = {
            "member_id": MEMBER_ID,
            "provider": "Dr. Johnson",
            "diagnosis_code": "M54.5",
            "line_items": [
                {"service_type": "OFFICE_VISIT", "service_date": "2026-03-10", "amount_charged": "150.00"},
                {"service_type": "LAB_WORK", "service_date": "2026-03-10", "amount_charged": "300.00"},
                {"service_type": "IMAGING", "service_date": "2026-03-11", "amount_charged": "800.00"},
            ],
        }
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 201
        items = resp.json()["line_items"]
        assert len(items) == 3
        types = {i["service_type"] for i in items}
        assert types == {"OFFICE_VISIT", "LAB_WORK", "IMAGING"}

    def test_policy_id_is_populated(self, client):
        resp = client.post("/claims", json=VALID_CLAIM)
        data = resp.json()
        assert data["policy_id"] != ""
        assert data["policy_id"] is not None


# ===================================================================
# Error handling
# ===================================================================


class TestClaimValidation:
    def test_invalid_member_returns_404(self, client):
        payload = {**VALID_CLAIM, "member_id": "nonexistent"}
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_empty_line_items_returns_422(self, client):
        payload = {**VALID_CLAIM, "line_items": []}
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 422

    def test_missing_provider_returns_422(self, client):
        payload = {**VALID_CLAIM}
        del payload["provider"]
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 422

    def test_zero_amount_returns_422(self, client):
        payload = {
            **VALID_CLAIM,
            "line_items": [
                {"service_type": "LAB_WORK", "service_date": "2026-03-15", "amount_charged": "0"},
            ],
        }
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 422

    def test_negative_amount_returns_422(self, client):
        payload = {
            **VALID_CLAIM,
            "line_items": [
                {"service_type": "LAB_WORK", "service_date": "2026-03-15", "amount_charged": "-50.00"},
            ],
        }
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 422

    def test_invalid_service_type_returns_422(self, client):
        payload = {
            **VALID_CLAIM,
            "line_items": [
                {"service_type": "ACUPUNCTURE", "service_date": "2026-03-15", "amount_charged": "100.00"},
            ],
        }
        resp = client.post("/claims", json=payload)
        assert resp.status_code == 422


# ===================================================================
# Adjudication endpoint
# ===================================================================


def _submit(client, payload=None):
    """Helper: submit a claim and return its id."""
    resp = client.post("/claims", json=payload or VALID_CLAIM)
    assert resp.status_code == 201
    return resp.json()["id"]


class TestAdjudicationHappyPath:
    def test_adjudicate_returns_200(self, client):
        claim_id = _submit(client)
        resp = client.post(f"/claims/{claim_id}/adjudicate")
        assert resp.status_code == 200

    def test_fully_approved_claim(self, client):
        """A covered line item that exceeds the deductible -> APPROVED with payment."""
        payload = {
            "member_id": MEMBER_ID,
            "provider": "Dr. Patel",
            "diagnosis_code": "J06.9",
            "line_items": [
                {"service_type": "LAB_WORK", "service_date": "2026-03-15", "amount_charged": "800.00"},
            ],
        }
        claim_id = _submit(client, payload)
        resp = client.post(f"/claims/{claim_id}/adjudicate")
        data = resp.json()

        assert data["status"] == "APPROVED"
        assert data["claim_id"] == claim_id
        assert float(data["total_charged"]) == 800.0
        # $800 - $500 deductible = $300 * 80% coinsurance = $240
        assert float(data["total_approved"]) == 240.0
        assert len(data["line_items"]) == 1
        assert data["line_items"][0]["status"] == "APPROVED"

        exp = data["line_items"][0]["explanation"]
        assert exp["reason_code"] == "APPROVED"
        assert "approved" in exp["member_explanation"].lower()
        assert len(exp["rule_trace"]) > 0
        assert float(exp["deductible_applied"]) == 500.0

    def test_fully_denied_claim(self, client):
        """A service type with no coverage rule -> all items denied."""
        from app.db.models import CoverageRuleModel
        from app.db.seed import POLICY_ID

        payload = {
            "member_id": MEMBER_ID,
            "provider": "Unknown Clinic",
            "diagnosis_code": "Z99.9",
            "line_items": [
                {"service_type": "OFFICE_VISIT", "service_date": "2026-03-15", "amount_charged": "200.00"},
            ],
        }
        claim_id = _submit(client, payload)

        db = next(fastapi_app.dependency_overrides[get_db]())
        db.query(CoverageRuleModel).filter(
            CoverageRuleModel.policy_id == POLICY_ID,
            CoverageRuleModel.service_type == "OFFICE_VISIT",
        ).delete()
        db.commit()
        db.close()

        resp = client.post(f"/claims/{claim_id}/adjudicate")
        data = resp.json()

        assert data["status"] == "DENIED"
        assert float(data["total_approved"]) == 0
        assert float(data["total_denied"]) == 200.0
        assert data["line_items"][0]["status"] == "DENIED"

        exp = data["line_items"][0]["explanation"]
        assert exp["reason_code"] == "NOT_COVERED"
        assert "not covered" in exp["member_explanation"].lower()

    def test_partial_approval(self, client):
        """Mix of covered and uncovered service types -> PARTIAL status."""
        from app.db.models import CoverageRuleModel
        from app.db.seed import POLICY_ID

        payload = {
            "member_id": MEMBER_ID,
            "provider": "Metro Hospital",
            "diagnosis_code": "M54.5",
            "line_items": [
                {"service_type": "LAB_WORK", "service_date": "2026-03-15", "amount_charged": "800.00"},
                {"service_type": "IMAGING", "service_date": "2026-03-15", "amount_charged": "400.00"},
            ],
        }
        claim_id = _submit(client, payload)

        db = next(fastapi_app.dependency_overrides[get_db]())
        db.query(CoverageRuleModel).filter(
            CoverageRuleModel.policy_id == POLICY_ID,
            CoverageRuleModel.service_type == "IMAGING",
        ).delete()
        db.commit()
        db.close()

        resp = client.post(f"/claims/{claim_id}/adjudicate")
        data = resp.json()

        assert data["status"] == "PARTIAL"
        # LAB_WORK: $800 - $500 ded = $300 * 80% = $240
        assert float(data["total_approved"]) == 240.0
        assert float(data["total_denied"]) == 800.0 + 400.0 - 240.0

        statuses = {li["status"] for li in data["line_items"]}
        assert statuses == {"APPROVED", "DENIED"}

        approved_li = [li for li in data["line_items"] if li["status"] == "APPROVED"][0]
        assert approved_li["explanation"]["reason_code"] == "APPROVED"
        assert float(approved_li["explanation"]["deductible_applied"]) == 500.0

        denied_li = [li for li in data["line_items"] if li["status"] == "DENIED"][0]
        assert denied_li["explanation"]["reason_code"] == "NOT_COVERED"

    def test_response_has_totals_and_structured_explanations(self, client):
        claim_id = _submit(client)
        resp = client.post(f"/claims/{claim_id}/adjudicate")
        data = resp.json()

        assert "total_charged" in data
        assert "total_approved" in data
        assert "total_denied" in data
        assert "provider" in data
        assert "diagnosis_code" in data

        for li in data["line_items"]:
            exp = li["explanation"]
            assert "reason_code" in exp
            assert "member_explanation" in exp
            assert "rule_trace" in exp
            assert isinstance(exp["rule_trace"], list)
            assert "deductible_applied" in exp


class TestAdjudicationErrors:
    def test_claim_not_found_returns_404(self, client):
        resp = client.post("/claims/nonexistent/adjudicate")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_already_adjudicated_returns_409(self, client):
        claim_id = _submit(client)
        first = client.post(f"/claims/{claim_id}/adjudicate")
        assert first.status_code == 200

        second = client.post(f"/claims/{claim_id}/adjudicate")
        assert second.status_code == 409
        assert "cannot be adjudicated" in second.json()["detail"].lower()

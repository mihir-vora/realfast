"""
Integration tests for POST /claims.

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

# Decisions & Trade-offs

## Tech Stack

| Choice | Why |
|--------|-----|
| **Python** | Fast to prototype, widely readable. The interviewer can follow the code regardless of their primary language. |
| **FastAPI** | Modern async framework with automatic OpenAPI docs. Pydantic integration means request validation is declarative, not hand-written. |
| **SQLAlchemy** | The standard Python ORM. Gives us a real data model without the ceremony of raw SQL. The repository pattern wraps it so the domain layer stays clean. |
| **SQLite** | Zero setup. `pip install` and run — no Docker, no database server. Good enough for a single-process demo. |
| **pytest** | Simple, no boilerplate. `httpx` + FastAPI's `TestClient` gives us integration tests that hit real endpoints. |

### What I considered but didn't use

- **Alembic** (migrations): Overkill for a one-day project with a throwaway SQLite file. Tables are created on startup via `Base.metadata.create_all()`.
- **Docker**: Adds setup friction. SQLite means the whole app runs with `pip install -r requirements.txt && uvicorn app.main:app`.
- **Frontend**: The assignment says "there's some way to interact with the system." FastAPI's auto-generated Swagger UI at `/docs` serves as the interactive interface — no custom frontend needed.

---

## Architecture

Layered architecture, four layers deep:

```
HTTP (api/) → Services (services/) → Domain (domain/) → Data (repositories/ + db/)
```

- **api/** — Thin route handlers. Parse request, call service, return response. No business logic.
- **services/** — Orchestrate use cases. "Submit a claim" involves looking up the policy, running adjudication, persisting results, and updating accumulators. This is where the workflow lives.
- **domain/** — Pure business logic: enums, state machines, adjudication rules. No database imports, no framework imports. Testable in isolation.
- **repositories/** — Data access. Abstracts SQLAlchemy queries behind methods like `get_policy_for_member()`. The service layer calls repositories, never the ORM directly.
- **schemas/** — Pydantic models for API request/response shapes. Separate from domain models so the HTTP contract can evolve independently.

**Why this layering?** It's the simplest structure that separates concerns cleanly. In an interview I can point to any layer and explain what belongs there and what doesn't. It also makes the codebase easy to extend — adding an appeals endpoint means a new route, a new service method, and maybe a new domain entity, without touching adjudication logic.

---

## Scope: What I'm Building

A coherent vertical slice: **submit a claim and get an adjudicated result with explanations.**

Specifically:

1. **Seed data** — Pre-loaded members, policies, and coverage rules so the system is immediately usable
2. **Submit a claim** — POST endpoint that accepts line items, runs adjudication, returns results
3. **Adjudication engine** — Applies coverage rules, deductibles, annual limits, coinsurance
4. **Decision explanations** — Every denial and reduction has a human-readable reason
5. **Claim lifecycle** — State machine with SUBMITTED → PROCESSING → APPROVED/DENIED/PARTIAL → PAID
6. **Query endpoints** — GET claims, GET claim by ID, GET policy details
7. **Accumulator tracking** — Running totals for deductibles and annual limits that persist across claims

### Why this scope is coherent

These 7 features form a **complete loop**: you can submit a claim, see the adjudication result, understand why each line item was approved or denied, submit another claim, and watch the accumulators deplete. That's the core value proposition of a claims processing system.

Everything else (authentication, appeals, eligibility checks, EOBs) is additive. The system works without them.

---

## What I'm Intentionally Not Building

| Feature | Rationale |
|---------|-----------|
| **Authentication / authorization** | Adds code without demonstrating domain modeling skill. A real system would need it; this demo doesn't. |
| **Appeals workflow** | The assignment hints this may be a pairing-session extension. I've designed the model to support it (an Appeal entity linking to ClaimLineItem) but I'm not implementing it. |
| **Eligibility verification** | Same reasoning — noted as a future extension. The policy has `effective_date` and `end_date` fields ready for this check. |
| **Async processing / queues** | Adjudication happens synchronously on the request. A production system might queue claims, but synchronous processing makes the demo deterministic and debuggable. |
| **Provider networks (in-network / out-of-network)** | Would double the complexity of coverage rules for marginal domain-modeling signal. |
| **Pre-authorization** | Some services require approval before treatment. Interesting but out of scope — it's a separate workflow, not a claims processing concern. |
| **Claim editing / amendments** | Once submitted, a claim is immutable. Simplifies the state machine significantly. |
| **Real diagnosis code validation** | ICD-10 has ~70,000 codes. We store the code as a string but don't validate it. |
| **PDF/EOB generation** | Nice polish but doesn't demonstrate domain modeling. The raw API response contains all the same information. |

---

## Key Domain Decisions

### Coverage rules as data, not code

Rules are rows in a database table, not `if service == "lab": ...` branches. This means:
- Adding a new rule = inserting a row
- Testing rules = testing with different data fixtures, not mocking code paths
- The adjudication engine is generic — it doesn't know about specific service types

The trade-off: truly complex rules (e.g., "covered only if diagnosis is X and member is under 65 and it's within 30 days of a prior visit") can't be expressed as a single row. For this assignment, the row-per-rule model is sufficient and much easier to explain.

### Claim status derived from line items

The claim's top-level status (APPROVED, DENIED, PARTIAL) is **computed** from its line item outcomes, not set independently. This eliminates an entire class of consistency bugs where the claim says "approved" but a line item says "denied."

### Accumulators as a first-class entity

Rather than re-computing "how much has this member used?" by scanning all historical claims, we maintain running totals. This is how real claims systems work — it's faster and makes the limit-checking logic straightforward.

### Money as decimal, not integer cents

I'm using Python's `Decimal` / SQLAlchemy's `Numeric` with 2 decimal places rather than storing cents as integers. For a demo this is more readable. A production system might prefer integer cents to avoid floating-point surprises, but SQLAlchemy's `Numeric` type handles this correctly.

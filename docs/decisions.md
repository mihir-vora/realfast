# Decisions & Trade-offs

## Tech Stack

| Choice | Why |
|--------|-----|
| **Python 3.12+** | Fast to prototype, widely readable. The interviewer can follow the code regardless of their primary language. |
| **FastAPI** | Modern async framework with automatic OpenAPI docs. Pydantic integration means request validation is declarative. |
| **SQLAlchemy** | Standard Python ORM. Gives us a real relational model without raw SQL ceremony. The repository pattern wraps it so the domain layer stays clean. |
| **SQLite** | Zero setup. `pip install` and run — no Docker, no database server, no credentials. Good enough for a single-process demo. |
| **pytest** | Simple, no boilerplate. `httpx` + FastAPI's `TestClient` gives us integration tests that hit real endpoints. |
| **Vanilla HTML/CSS/JS** | No build step, no node_modules, no React/Vue complexity. Served directly from FastAPI. Easy to explain and modify in a pairing session. |

### What I considered but didn't use

- **Alembic** (migrations): Overkill for a one-day project. Tables are created on startup via `Base.metadata.create_all()`. Delete `claims.db` to reset.
- **Docker**: Adds setup friction. SQLite means the entire app runs with two commands.
- **asyncpg / raw SQL**: Initially considered (and briefly attempted) dropping the ORM in favor of raw async queries. Reverted because SQLAlchemy's mapping layer made the repository pattern cleaner and the domain layer stays ORM-free regardless.
- **React / Vue**: A SPA framework would add a build pipeline and npm dependency. The frontend is simple enough that vanilla JS keeps the project self-contained.

---

## Architecture

Four-layer architecture:

```
HTTP (api/) → Services (services/) → Domain (domain/) → Data (repositories/ + db/)
```

- **api/** — Thin route handlers. Parse request, call service, return response. No business logic.
- **services/** — Orchestrate use cases. "Adjudicate a claim" involves loading policy data, running the engine, persisting results, and computing totals. This is where the workflow lives.
- **domain/** — Pure business logic: entities as dataclasses, state machine transitions, adjudication pipeline. No database imports, no framework imports. Testable in isolation.
- **repositories/** — Data access. Converts between ORM models and domain entities. The service layer calls repository functions, never the ORM directly.
- **schemas/** — Pydantic models for API request/response shapes. Separate from domain entities so the HTTP contract can evolve independently.
- **frontend/** — Static HTML/CSS/JS served by FastAPI. Talks to the API via `fetch()`.

**Why this layering?** It's the simplest structure that separates concerns cleanly. In an interview I can point to any layer and explain what belongs there and what doesn't. It also makes the codebase easy to extend — adding an appeals endpoint means a new route, a new service method, and maybe a new domain entity, without touching adjudication logic.

---

## What I Built

A coherent vertical slice: **submit a claim, adjudicate it, see the result with explanations, and watch benefit balances deplete over time.**

1. **Seed data** — Pre-loaded member (Jane Smith), policy ($500 deductible), and 6 coverage rules so the system is immediately usable
2. **Claim submission** — POST endpoint accepting line items with validation (positive amounts, valid service types)
3. **Adjudication engine** — 5-step pipeline: coverage check → deductible → coinsurance → per-visit cap → annual limit. Pure functions, no side effects
4. **Decision explanations** — Every decision produces a `DecisionExplanation` with a member-friendly message and a step-by-step rule trace for internal reviewers
5. **State machines** — Claim (6 states) and LineItem (3 states) with enforced transitions and `InvalidTransitionError`
6. **Accumulator tracking** — Running totals for deductibles and per-service annual limits that persist across claims
7. **Benefit summary** — `GET /members/{id}` returns live remaining balances without running adjudication
8. **Frontend** — Submit claims, adjudicate, view results with explanations, see benefit bars deplete in real time
9. **Query endpoints** — List all claims, get a single claim, get member/policy info
10. **Test suite** — ~1140 lines across 4 test files covering domain logic, adjudication edge cases, and API integration

### Why this scope is coherent

These features form a **complete loop**: submit a claim → adjudicate → see why each line item was approved/denied → submit another → watch deductible and annual limits deplete. That's the core value proposition of a claims processing system. Everything else is additive.

---

## What I Intentionally Did Not Build

| Feature | Rationale |
|---------|-----------|
| **Authentication / authorization** | Adds code without demonstrating domain modeling skill. A real system needs it; this demo doesn't. |
| **Appeals workflow** | Noted as a likely pairing-session extension. The model supports it — `Appeal` entity linked to `ClaimLineItem` with its own state machine. `DecisionExplanation` already captures enough context for review. I didn't build it so there's room to extend together. |
| **Eligibility verification** | Also noted as a future extension. The `Policy` already has `effective_date` and `end_date` fields. Adding a guard clause before adjudication is a small change. |
| **Async processing / queues** | Adjudication happens synchronously on the request. Makes the demo deterministic and debuggable. A production system would queue claims. |
| **Provider networks** | In-network vs. out-of-network would double the complexity of coverage rules for marginal domain signal. |
| **Pre-authorization** | Separate workflow, not a claims processing concern. |
| **Claim editing / amendments** | Once submitted, a claim is immutable. Simplifies the state machine significantly. A real system would support amendments. |
| **Real ICD code validation** | ICD-10 has ~70,000 codes. We store the code as a string but don't validate it against a codebook. |
| **EOB / PDF generation** | Nice polish but doesn't demonstrate domain modeling. The API response already contains all the same information. |
| **Concurrent claim protection** | Real systems lock accumulators to prevent race conditions when two claims hit the same limit simultaneously. SQLite's write-lock gives us basic single-process protection for free. |
| **Multi-member support in UI** | The frontend is hardcoded to Jane Smith. The API supports any member — the frontend limitation is a scope decision, not a technical one. |

---

## Key Domain Decisions

### Coverage rules as data, not code

Rules are rows in a database table, not `if service == "lab": ...` branches. This means:
- Adding a new rule = inserting a row
- Testing rules = testing with different data fixtures, not mocking code paths
- The adjudication engine is generic — it doesn't know about specific service types

**Trade-off:** Truly complex rules (e.g., "covered only if diagnosis is X and member is under 65") can't be expressed as a single row. For this assignment, the row-per-rule model is sufficient.

### Claim status derived from line items

The claim's top-level status (APPROVED, DENIED, PARTIAL) is **computed** from its line item outcomes, not set independently. This eliminates an entire class of consistency bugs.

### Accumulators as a first-class entity

Rather than re-computing "how much has this member used?" by scanning historical claims, we maintain running totals. This is how real claims systems work — it's faster and makes limit-checking straightforward.

### Domain entities are plain dataclasses

`domain/entities.py` contains pure Python dataclasses with no ORM or framework imports. The adjudication engine (`domain/adjudication.py`) operates entirely on these. The repository layer handles conversion to/from SQLAlchemy models. This means the most important code in the system — the adjudication logic — is testable without a database.

### Submission and adjudication are separate API calls

The frontend submits a claim (which persists it in SUBMITTED state) and then adjudicates it as a second step. This makes the two-phase process visible to the user and is closer to how real claims systems work (claims may sit in a queue before processing). It also makes the API easier to reason about.

### Money as Decimal, not integer cents

Using Python's `Decimal` with `Numeric(10,2)` in the database. More readable than integer cents for a demo. All currency math uses `ROUND_HALF_UP` to 2 decimal places via the `_cents()` helper.

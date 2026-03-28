# Claims Processing System

Insurance claims adjudication system. Members submit claims for reimbursement; the system applies coverage rules, calculates payable amounts, explains decisions, and tracks each claim through its lifecycle.

## Quick Start

```bash
# 1. Clone and enter the project
cd realfast

# 2. Create a virtual environment
python -m venv venv

# 3. Activate it
# Windows (PowerShell)
venv\Scripts\activate
# Windows (CMD)
venv\Scripts\activate.bat
# macOS / Linux
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run the app
uvicorn app.main:app --reload
```

Open http://localhost:8000 in your browser. That's it.

No database setup needed — SQLite is embedded and the database file (`claims.db`) is created automatically on first run with seed data.

## What You Get

| URL | What |
|-----|------|
| http://localhost:8000 | Frontend — submit claims, adjudicate, view results |
| http://localhost:8000/docs | Interactive API docs (Swagger UI) |
| http://localhost:8000/health | Health check endpoint |

## Seed Data

On first run, the app seeds a sample member and policy:

- **Member**: Jane Smith (`m-jane-smith`)
- **Policy**: POL-2026-001 with $500 annual deductible
- **Coverage**: 6 service types (Office Visit, Lab Work, Imaging, Generic Rx, Specialist, Emergency) with varying coinsurance rates, per-visit limits, and annual limits

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/members/{member_id}` | Member info, policy, coverage rules, benefit balances |
| `POST` | `/claims` | Submit a new claim with line items |
| `GET` | `/claims` | List all claims |
| `GET` | `/claims/{claim_id}` | Get a single claim |
| `POST` | `/claims/{claim_id}/adjudicate` | Run adjudication on a submitted claim |

## Project Structure

```
app/
  main.py                  # FastAPI app, lifespan, static file serving
  api/
    claims.py              # Claim endpoints (submit, list, adjudicate)
    members.py             # Member/policy/benefits endpoint
  domain/
    entities.py            # Pure Python dataclasses (Claim, Policy, Member, etc.)
    enums.py               # ClaimStatus, LineItemStatus, ServiceType
    adjudication.py        # Adjudication engine — core business logic
  services/
    claims.py              # Use-case orchestration (submit, adjudicate flows)
  repositories/
    repository.py          # Data access — ORM-to-domain conversion
  db/
    base.py                # SQLAlchemy engine + session config
    models.py              # ORM table models
    seed.py                # Sample data for first run
  schemas/
    claims.py              # Pydantic request/response models
frontend/
  index.html               # Single-page app
  style.css                # Styles
  app.js                   # Frontend logic (vanilla JS)
tests/
  test_domain.py           # Domain entity tests
  test_adjudication.py     # Adjudication engine tests
  test_api_claims.py       # API integration tests
  test_health.py           # Health check test
docs/
  domain-model.md          # Entities, relationships, state machines
  decisions.md             # Trade-offs and assumptions
```

## Running Tests

```bash
pytest -v
```

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Framework | FastAPI | Async-native, auto-generated docs, type-safe |
| Database | SQLite | Zero setup, embedded, sufficient for demo |
| ORM | SQLAlchemy | Clean separation between domain entities and persistence |
| Validation | Pydantic | Comes with FastAPI, clean schema definitions |
| Frontend | Vanilla HTML/CSS/JS | No build step, no node_modules, serves from FastAPI |
| Tests | pytest | Industry standard, simple to run |

## How It Works

1. **Submit a claim** — POST to `/claims` with a member ID, provider, diagnosis code, and line items (service type + amount)
2. **Adjudicate** — POST to `/claims/{id}/adjudicate` to run the claim through the rules engine
3. The engine processes each line item through a pipeline:
   - Coverage check (is this service type covered?)
   - Deductible application (has the member met their annual deductible?)
   - Coinsurance calculation (plan pays its percentage)
   - Per-visit cap (cap per line item)
   - Annual limit check (has the yearly maximum been reached?)
4. Each decision comes with a **member-friendly explanation** and a **rule trace** for internal review
5. The claim-level status is derived from line item outcomes: all approved = APPROVED, all denied = DENIED, mixed = PARTIAL

## Requirements

- Python 3.12+
- No external database server
- No Node.js / npm

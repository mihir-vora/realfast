# Claims Processing System

A claims processing system for an insurance company. Members submit claims for reimbursement; the system determines coverage, calculates payable amounts, and tracks each claim through its lifecycle.

## Tech Stack

- **Python 3.11+**
- **FastAPI** — async web framework
- **SQLAlchemy** — ORM / database toolkit
- **SQLite** — embedded database (no setup required)
- **pytest** — testing

## Project Structure

```
app/
  main.py            # FastAPI application entry point
  api/               # Route handlers (thin HTTP layer)
  domain/            # Core business entities and rules
  services/          # Use-case orchestration
  repositories/      # Data access layer
  db/                # Database engine, session, migrations
  schemas/           # Pydantic request/response models
tests/               # Test suite
docs/                # Domain model, decisions, self-review
```

## Setup

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.
Interactive docs at `http://localhost:8000/docs`.

## Test

```bash
pytest
```

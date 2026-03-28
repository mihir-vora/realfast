# Self-Review

## What's Good

### The adjudication engine is the right thing to invest in
The pipeline in `domain/adjudication.py` is the heart of this system and I'm satisfied with it. It handles deductibles, coinsurance, per-visit caps, and annual limits correctly. Each step is clearly commented. Accumulators are mutated in-place so that line item N sees the effect of items 1..N-1 — this is a subtle correctness requirement that I got right.

### Domain entities are clean
`domain/entities.py` is pure Python dataclasses. No SQLAlchemy imports, no FastAPI imports. The state machine is enforced with `transition_to()` and tested thoroughly. You can read this file and understand the entire domain without knowing anything about the framework.

### Decision explanations are genuinely useful
Every adjudication decision has two audiences: a member-friendly explanation ("Your entire charge of $200.00 was applied to your annual deductible") and a rule trace for internal reviewers showing each step. This isn't decoration — it's a real requirement in claims processing. A member who gets a denial needs to understand why.

### The layer separation works
The adjudication engine doesn't know about databases. The API layer doesn't know about SQL. The service layer orchestrates. I can point to any file and explain what belongs there and what doesn't.

### Test coverage on the domain layer
`test_adjudication.py` is 652 lines covering the major scenarios: basic approval, deductible application, per-visit caps, annual limit exhaustion, limit depletion across multiple line items, and mixed approval/denial. These tests run without a database because the domain layer is pure.

---

## What's Rough

### The repository layer is verbose
`repository.py` at 243 lines is mostly mechanical conversion between ORM models and domain dataclasses. Every field is mapped explicitly. This is correct but tedious — a mapper library or code generation would reduce boilerplate. I chose explicitness over cleverness for an interview setting, but it's not code I'm proud of.

### The frontend is functional but basic
It works — you can submit claims, adjudicate them, see explanations, watch benefit bars deplete. But there's no loading states on initial page load (just a spinner), no error boundary, no responsive design testing on mobile. The member is hardcoded to Jane Smith. It's a demo UI, not a production UI, and it looks like one.

### `save_claim` uses `db.merge()` as a shortcut
The `save_claim` function in the repository creates a new ORM object and calls `db.merge()` to handle both insert and update. This works but it's a blunt instrument — it replaces all line items even when only the claim status changed. A more precise implementation would diff the existing state. For a demo with low write volume this is fine; for production it's wasteful.

### No eligibility date check
The adjudication engine doesn't verify that the service date falls within the policy's effective date range. The `Policy` entity has `effective_date` and `end_date` — the check would be a 3-line guard clause at the top of the pipeline. I just didn't add it. This is an oversight, not a design decision.

### The PAID state exists but nothing transitions to it
The state machine defines `APPROVED → PAID` and `PARTIAL → PAID`, but there's no endpoint or service method to trigger payment. It's a placeholder for a workflow that doesn't exist yet. I included it in the model because it completes the lifecycle diagram, but in the running system, claims stop at APPROVED/DENIED/PARTIAL.

### Error handling in the API is catch-and-rethrow
The claims API catches service-layer exceptions and converts them to HTTPExceptions. This works but it's mechanical. A middleware-based approach (exception handlers registered on the app) would be cleaner and avoid repetitive try/except blocks.

### No pagination on GET /claims
`get_all_claims()` returns every claim in the database. Fine for a demo with <100 claims. Would need `limit`/`offset` or cursor pagination for production.

---

## What I Would Improve With Another Day

### 1. Eligibility verification
Add a date-range check before adjudication: is the member's policy active on the service date? This is the most obvious missing guard clause. ~30 minutes including tests.

### 2. Appeals workflow
Add an `Appeal` entity linked to a `ClaimLineItem`. State machine: `FILED → UNDER_REVIEW → UPHELD / OVERTURNED`. An overturned appeal would re-adjudicate the line item with the original `DecisionExplanation` available for context. This is the most natural extension and the one I'd expect in a pairing session. ~2-3 hours.

### 3. Better frontend error handling and UX
Add proper loading skeletons, form validation feedback before submission, and a confirmation step before adjudication. Show coverage rules on the member card so the user understands the plan before submitting. ~1-2 hours.

### 4. Pagination and filtering
Add `limit`/`offset` to the claims list endpoint. Add filtering by status (show me only SUBMITTED claims) and by member. ~1 hour.

### 5. Configuration via environment variables
The database URL is hardcoded. The seed data member ID is hardcoded. These should come from environment variables or a config file. Small lift but important for deployment flexibility. ~30 minutes.

### 6. Integration test for the full submit→adjudicate loop
The existing tests cover domain logic and individual API endpoints well, but there's no single test that submits a claim, adjudicates it, submits another, and verifies that accumulators carry over correctly. This is the most important end-to-end scenario. ~1 hour.

### 7. Proper database migrations
Replace `create_all()` with Alembic so schema changes don't require deleting the database file. Not needed for this assignment but essential for anything beyond a demo. ~1 hour.

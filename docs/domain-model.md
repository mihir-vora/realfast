# Domain Model

## Overview

An insurance company receives **claims** from **members**. Each member holds a **policy** that defines what services are covered, up to what limits, and with what cost-sharing. The system **adjudicates** each line item on a claim — deciding whether it's covered, how much the plan pays, and why — then tracks the claim through its lifecycle until payment.

---

## Entities and Relationships

```
Member ──1:N──► Policy
Policy ──1:N──► CoverageRule
Member ──1:N──► Claim
Claim  ──1:N──► ClaimLineItem
Policy ──1:N──► Accumulator  (one per service type per plan year)
```

### Member

The insured person.

| Field      | Type     | Notes       |
|------------|----------|-------------|
| id         | str/UUID | primary key |
| name       | string   |             |
| created_at | datetime |             |

A member can hold multiple policies (e.g. switched plans mid-year), but in this implementation a member has **one active policy**. The system assumes the first policy found is the active one.

### Policy

The insurance plan a member is enrolled in.

| Field             | Type    | Notes                              |
|-------------------|---------|------------------------------------|
| id                | str/UUID| primary key                        |
| member_id         | FK      | belongs to one member              |
| policy_number     | string  | human-readable identifier (unique) |
| effective_date    | date    | coverage start                     |
| end_date          | date    | coverage end                       |
| annual_deductible | decimal | member pays this before plan kicks in |
| created_at        | datetime|                                    |

### CoverageRule

A single rule within a policy that defines coverage for one service type.

| Field            | Type    | Notes                                       |
|------------------|---------|---------------------------------------------|
| id               | str/UUID| primary key                                 |
| policy_id        | FK      | belongs to one policy                       |
| service_type     | enum    | which service this rule covers              |
| is_covered       | bool    | false = explicitly excluded                 |
| coinsurance_rate | decimal | plan pays this fraction (e.g. 0.80 = 80%)  |
| annual_limit     | decimal | max plan payout per year (0 = unlimited)    |
| per_visit_limit  | decimal | max plan payout per visit (nullable)        |

**Why rules-as-data?** Each rule is a row. The adjudication engine iterates rules and applies them uniformly. Adding a new service type means adding a row, not changing code. Easy to test, easy to explain.

### Claim

A reimbursement request submitted by a member.

| Field          | Type     | Notes                               |
|----------------|----------|---------------------------------------|
| id             | str/UUID | primary key                          |
| member_id      | FK       | who submitted it                     |
| policy_id      | FK       | which policy to adjudicate against   |
| status         | enum     | lifecycle state (see state machine)  |
| provider       | string   | doctor / facility name               |
| diagnosis_code | string   | ICD-style code (stored, not validated)|
| submitted_at   | datetime |                                       |
| updated_at     | datetime |                                       |

### ClaimLineItem

One billable service within a claim. Each line item is adjudicated independently.

| Field          | Type    | Notes                                    |
|----------------|---------|------------------------------------------|
| id             | str/UUID| primary key                              |
| claim_id       | FK      | belongs to one claim                     |
| service_type   | enum    | maps to a CoverageRule                   |
| service_date   | date    | when service was rendered                |
| amount_charged | decimal | what the provider billed                 |
| amount_allowed | decimal | what the plan pays (set by adjudication) |
| status         | enum    | PENDING / APPROVED / DENIED              |
| denial_reason  | string  | human-readable (nullable)                |

### Accumulator

Tracks how much of a member's limits and deductibles have been consumed in a plan year.

| Field        | Type    | Notes                                            |
|--------------|---------|--------------------------------------------------|
| id           | str/UUID| primary key                                      |
| policy_id    | FK      | which policy                                     |
| service_type | enum    | which service (NULL = deductible tracker)        |
| year         | int     | plan year                                        |
| amount_used  | decimal | running total                                    |

One accumulator row per (policy, service_type, year). A separate row with `service_type = NULL` tracks the overall deductible.

### DecisionExplanation (Value Object)

Immutable explanation attached to every adjudication result.

| Field                    | Type          | Notes                              |
|--------------------------|---------------|--------------------------------------|
| reason_code              | string        | NOT_COVERED, EXCLUDED, APPROVED, etc.|
| member_explanation       | string        | plain-English for the insured person |
| rule_trace               | tuple[str]    | step-by-step processing log          |
| deductible_applied       | decimal       | how much deductible was consumed     |
| remaining_annual_benefit | decimal/None  | remaining limit after this decision  |

### AdjudicationResult (Value Object)

Immutable outcome for one line item.

| Field          | Type           | Notes                        |
|----------------|----------------|------------------------------|
| line_item_id   | str            | which line item              |
| status         | LineItemStatus | APPROVED or DENIED           |
| amount_allowed | decimal        | plan payout                  |
| denial_reason  | string/None    | if denied                    |
| explanation    | DecisionExplanation | full breakdown          |

---

## Service Types (Enum)

Six types, kept intentionally small:

| Value        | Seed Coverage                                |
|--------------|----------------------------------------------|
| OFFICE_VISIT | 80% coinsurance, $2000/yr limit, $150/visit  |
| LAB_WORK     | 80%, $1000/yr, no per-visit cap              |
| IMAGING      | 70%, $1500/yr, $500/visit                    |
| GENERIC_RX   | 90%, unlimited annual, $50/visit             |
| SPECIALIST   | 60%, $3000/yr, no per-visit cap              |
| EMERGENCY    | 80%, $10000/yr, no per-visit cap             |

---

## State Machines

### Claim Status

```
SUBMITTED ──► PROCESSING ──┬──► APPROVED ──► PAID
                            ├──► DENIED      (terminal)
                            └──► PARTIAL  ──► PAID
```

| State      | Meaning                                              |
|------------|------------------------------------------------------|
| SUBMITTED  | Received, not yet adjudicated                        |
| PROCESSING | Adjudication engine is evaluating line items          |
| APPROVED   | Every line item approved                             |
| DENIED     | Every line item denied                               |
| PARTIAL    | Mixed — some approved, some denied                   |
| PAID       | Payment issued (from APPROVED or PARTIAL)            |

The claim-level status is **derived from line item outcomes**, not set independently. This eliminates consistency bugs where the claim says "approved" but a line item says "denied."

Transitions are enforced by `Claim.transition_to()`, which raises `InvalidTransitionError` for illegal moves.

### Line Item Status

```
PENDING ──┬──► APPROVED
           └──► DENIED
```

No intermediate states. The adjudication engine resolves each line item in a single pass.

---

## Adjudication Pipeline

When a claim is adjudicated, each line item passes through this pipeline:

```
1. COVERAGE CHECK     → Is there a CoverageRule for this service_type?
                         No rule or is_covered=false → DENY with reason
2. DEDUCTIBLE         → Has the member met their annual deductible?
                         If not → member pays toward deductible first
                         If entire amount consumed by deductible → APPROVE at $0
3. COINSURANCE        → Plan pays its percentage of the remaining amount
4. PER-VISIT CAP      → Cap the plan's payout at per_visit_limit (if set)
5. ANNUAL LIMIT CHECK → Would this push past the annual limit?
                         Limit exhausted → DENY
                         Would exceed → cap at remaining limit
6. UPDATE ACCUMULATORS → Record deductible + plan payout in running totals
```

After all line items: derive claim-level status from outcomes.

**Accumulator ordering matters.** Line item N sees the effect of items 1..N-1 within the same claim. If two lab items share a $1000 annual limit, the second one sees the first one's payout already deducted.

---

## Assumptions

1. **One active policy per member.** No coordination of benefits across multiple plans.
2. **Adjudication is synchronous.** Submit a claim, get a result. No async queues or manual review.
3. **No provider networks.** No in-network vs. out-of-network distinction.
4. **No pre-authorization.** Some services require pre-approval in reality. Skipped.
5. **Diagnosis codes are pass-through.** Stored but not validated against ICD-10.
6. **No authentication.** The API is open.
7. **Currency is USD, stored as Decimal.** No multi-currency.
8. **Plan year = calendar year.** No fiscal year complexity.
9. **No retroactive policy changes.** Rules are static once created.
10. **Submission and adjudication are separate steps.** The frontend submits first, then adjudicates. This makes the two-step process visible.

---

## Extension Points

The model is designed to accommodate these without restructuring:

### Appeals Workflow (likely pairing session extension)
Add an `Appeal` entity with FK to `ClaimLineItem`. Own state machine: `FILED → UNDER_REVIEW → UPHELD / OVERTURNED`. An overturned appeal re-runs adjudication on that line item. The `DecisionExplanation` already captures enough context for an appeals reviewer to understand the original decision.

### Eligibility Verification (likely pairing session extension)
Add a check in the adjudication pipeline before step 1: verify `policy.effective_date <= service_date <= policy.end_date` and that the member's enrollment is active. The `Policy` entity already has the date fields — this is a guard clause, not a schema change.

### New Service Types
Add an enum value and a CoverageRule row. Zero code changes to the adjudication engine.

### Tiered Coinsurance
The CoverageRule could gain a `tier` field or be split into a separate table for plans where coinsurance changes after a spending threshold.

### Claim Amendments / Resubmission
Currently claims are immutable after submission. An amendment workflow would create a new claim linked to the original, with a `supersedes` FK.

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

| Field      | Type   | Notes                    |
|------------|--------|--------------------------|
| id         | UUID   | primary key              |
| name       | string |                          |
| created_at | datetime |                        |

A member can hold multiple policies (e.g. switched plans mid-year), but for this assignment a member has **one active policy**.

### Policy

The insurance plan a member is enrolled in.

| Field          | Type     | Notes                              |
|----------------|----------|------------------------------------|
| id             | UUID     | primary key                        |
| member_id      | FK       | belongs to one member              |
| policy_number  | string   | human-readable identifier          |
| effective_date | date     | coverage start                     |
| end_date       | date     | coverage end                       |
| annual_deductible | decimal | total deductible before plan pays |
| created_at     | datetime |                                    |

### CoverageRule

A single rule within a policy that defines coverage for one service type. This is the **rules-as-data** approach: rules are rows in the database, not if-else branches in code.

| Field               | Type    | Notes                                         |
|---------------------|---------|-----------------------------------------------|
| id                  | UUID    | primary key                                   |
| policy_id           | FK      | belongs to one policy                         |
| service_type        | enum    | which service this rule covers                |
| is_covered          | bool    | false = explicitly excluded                   |
| coinsurance_rate    | decimal | plan pays this fraction (e.g. 0.80 = 80%)    |
| annual_limit        | decimal | max plan payout per year for this service     |
| per_visit_limit     | decimal | max plan payout per single visit (nullable)   |

**Why rules-as-data?** Each rule is a row. The adjudication engine iterates rules and applies them uniformly. Adding a new service type means adding a row, not changing code. Easy to test, easy to explain.

### Claim

A reimbursement request submitted by a member.

| Field        | Type     | Notes                                  |
|--------------|----------|----------------------------------------|
| id           | UUID     | primary key                            |
| member_id    | FK       | who submitted it                       |
| policy_id    | FK       | which policy to adjudicate against     |
| status       | enum     | lifecycle state (see state machine)    |
| provider     | string   | doctor / facility name                 |
| diagnosis_code | string | ICD-style code (simplified)            |
| submitted_at | datetime |                                        |
| updated_at   | datetime |                                        |

### ClaimLineItem

One billable service within a claim. Each line item is adjudicated independently.

| Field              | Type    | Notes                                      |
|--------------------|---------|--------------------------------------------|
| id                 | UUID    | primary key                                |
| claim_id           | FK      | belongs to one claim                       |
| service_type       | enum    | maps to a CoverageRule                     |
| service_date       | date    | when service was rendered                  |
| amount_charged     | decimal | what the provider billed                   |
| amount_allowed     | decimal | system-computed: what the plan pays        |
| status             | enum    | line-item lifecycle state                  |
| denial_reason      | string  | human-readable explanation (nullable)      |

### Accumulator

Tracks how much of a member's limits and deductibles have been consumed in a plan year. Without this, the system can't answer "how much of the $500 lab limit have you already used?"

| Field           | Type    | Notes                                         |
|-----------------|---------|-----------------------------------------------|
| id              | UUID    | primary key                                   |
| policy_id       | FK      | which policy                                  |
| service_type    | enum    | which service (or NULL for deductible)        |
| year            | int     | plan year                                     |
| amount_used     | decimal | running total of plan payouts / deductible applied |

One accumulator row per (policy, service_type, year). A separate row with `service_type = NULL` tracks the overall deductible.

---

## Service Types (Enum)

Kept intentionally small to avoid scope creep:

```
OFFICE_VISIT
LAB_WORK
IMAGING
GENERIC_RX
SPECIALIST
EMERGENCY
```

---

## State Machines

### Claim Status

```
SUBMITTED ──► PROCESSING ──┬──► APPROVED
                           ├──► DENIED
                           └──► PARTIAL
APPROVED ──► PAID
PARTIAL  ──► PAID
DENIED   ──  (terminal)
```

| State      | Meaning                                                |
|------------|--------------------------------------------------------|
| SUBMITTED  | Received, not yet adjudicated                          |
| PROCESSING | Adjudication engine is evaluating line items            |
| APPROVED   | Every line item approved                               |
| DENIED     | Every line item denied                                 |
| PARTIAL    | At least one line item approved, at least one denied   |
| PAID       | Payment issued (from APPROVED or PARTIAL)              |

**The claim-level status is derived from line item outcomes.** The service layer sets it after adjudicating all line items — it never needs to be set manually.

### Line Item Status

```
PENDING ──┬──► APPROVED
          └──► DENIED
```

Simple and intentional. A line item is either waiting, approved (with an `amount_allowed`), or denied (with a `denial_reason`). No intermediate states — the adjudication engine processes each line item in a single pass.

---

## Adjudication Logic (How a Claim Gets Processed)

When a claim is submitted, the adjudication engine processes each line item through these steps:

```
For each line item:
  1. Find the CoverageRule for this service_type on the member's policy
  2. If no rule exists or is_covered = false → DENY ("not covered under this policy")
  3. Check the policy's annual deductible via the Accumulator
     - If deductible not yet met → member pays toward deductible first
  4. Apply coinsurance_rate to the remaining amount
  5. Apply per_visit_limit (cap the plan's payout per line item)
  6. Check annual_limit via the Accumulator
     - If limit would be exceeded → cap payout at remaining limit
     - If limit already exhausted → DENY ("annual limit reached")
  7. Update Accumulators
  8. Set amount_allowed and status = APPROVED (or DENIED if payout is zero)
```

After all line items are processed, derive the claim-level status:
- All APPROVED → claim is APPROVED
- All DENIED → claim is DENIED
- Mixed → claim is PARTIAL

### Decision Explanations

Every adjudication decision is explainable. The `denial_reason` field on each line item stores a human-readable string like:

- `"Service type IMAGING is not covered under this policy"`
- `"Annual limit of $500.00 for LAB_WORK exhausted ($500.00 of $500.00 used)"`
- `"Amount reduced from $200.00 to $150.00: per-visit limit applied"`

For approved items, the difference between `amount_charged` and `amount_allowed` is itself the explanation (coinsurance, deductible, caps). We don't need a separate explanation field for approvals — the numbers tell the story.

---

## How Annual Limits and Deductibles Work

### Deductible

The member pays out-of-pocket until the deductible is met, then the plan starts paying its share.

- Tracked in the Accumulator as a row with `service_type = NULL`
- During adjudication, the engine checks `accumulator.amount_used < policy.annual_deductible`
- Any remaining deductible is subtracted from the billable amount before coinsurance applies

### Annual Limits

Per-service-type caps on how much the plan will pay in a year.

- Tracked in the Accumulator as a row with the specific `service_type`
- If a payout would push `amount_used` past the `annual_limit`, the payout is capped
- If the limit is already exhausted, the line item is denied

Both are updated atomically when a claim is adjudicated — not after payment. This prevents over-commitment if two claims are submitted close together.

---

## Assumptions

1. **One active policy per member.** Real systems have coordination of benefits across multiple plans. Out of scope.
2. **Adjudication is synchronous.** Submit a claim, get a result. No async queues or manual review steps.
3. **No provider networks.** We don't distinguish in-network vs. out-of-network pricing.
4. **No pre-authorization.** Some services require pre-approval. Skipped for simplicity.
5. **Diagnosis codes are pass-through.** We store them but don't validate against a real ICD codebook.
6. **No authentication/authorization.** The API is open. A real system would have role-based access.
7. **Currency is USD, stored as decimal.** No multi-currency support.
8. **Plan year = calendar year.** No fiscal year or enrollment-period complexity.
9. **No retroactive policy changes.** Once a policy is created, its rules don't change.

---

## Intentionally Skipped Complexity

| Feature | Why Skipped |
|---------|-------------|
| Appeals / disputes | Noted as future extension in the assignment. The model supports it — add an `Appeal` entity linked to a ClaimLineItem. |
| Eligibility verification | Also noted as future extension. Would add a check before adjudication: "is this member active on this date?" |
| Explanation of Benefits (EOB) | A formatted document sent to the member. Nice-to-have, but the raw data is already on the line items. |
| Concurrent claim protection | Real systems lock accumulators to prevent race conditions. SQLite's write-lock gives us basic protection for free. |
| Claim amendments | Once submitted, a claim can't be edited. Members would submit a new claim. |

---

## Extension Points

The model is designed to accommodate these without restructuring:

- **Appeals:** Add an `Appeal` entity with FK to `ClaimLineItem`, its own state machine (FILED → UNDER_REVIEW → UPHELD / OVERTURNED), and the ability to re-adjudicate.
- **Eligibility:** Add a check in the adjudication pipeline: verify `policy.effective_date <= service_date <= policy.end_date` and member enrollment status.
- **New service types:** Add an enum value and a CoverageRule row. No code changes to the adjudication engine.
- **Tiered coinsurance:** The CoverageRule could gain a `tier` field or be split into a separate table for complex cost-sharing schedules.

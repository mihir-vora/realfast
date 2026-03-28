# Forward Deployed Engineer - Take-Home Assignment (Level 1)

## The Problem

Build a **Claims Processing System** for an insurance company.

Members submit claims for reimbursement. The system must determine what's covered, how much to pay, and track the claim through its lifecycle.

---

## Context

An insurance company processes claims like this:

- A **member** has a **policy** with coverage rules (what's covered, limits, deductibles)
- The member incurs an expense and submits a **claim** with line items
- Claims contain member information, diagnosis codes, provider details, and amounts
- The system must **adjudicate** each line item: Is it covered? How much do we pay?
- Claims move through states: submitted → under review → approved/denied → paid
- Members can dispute decisions

The interesting problems:

- How do you model coverage rules? (service type X is covered up to $Y per year)
- How do you track what's already been used against limits?
- What happens when a claim has 5 line items and 3 are covered, 1 is denied, 1 needs review?
- How do you explain to a member why something was denied?
- What's the state machine of a claim vs. a line item?

---

## Your Assignment

Build a working system that processes insurance claims.

**What "working" means:**
- A claim can be submitted with line items
- The system applies coverage rules to determine payable amounts
- Claims have lifecycle states
- Decisions have explanations
- There's some way to interact with the system

**What you decide:**
- The domain model (policies, claims, line items, coverage rules...)
- How coverage rules are represented and applied
- What states exist and how transitions work
- How to handle partial approvals
- How deep to go

---

## Deliverables

### 1. Working System
Runs locally. Processes claims against coverage rules.

### 2. Domain Model Documentation
Your entities, relationships, state machines. How did you model coverage rules?

### 3. Decisions & Trade-offs
What you built, what you didn't, what assumptions you made about the domain.

### 4. AI Collaboration Artifacts
Chat exports, prompts, what AI got wrong.

### 5. Self-Review
What's good, what's rough, what you'd flag.

---

## Time

1 day.

---

## What We're Looking For

| Signal | What It Tells Us |
|--------|------------------|
| **Domain decomposition** | Can you model policies, claims, coverage rules cleanly? |
| **Rule representation** | How do you structure coverage logic? |
| **State management** | Claims and line items have lifecycles - did you model them? |
| **Edge case thinking** | Partial approvals, limit exhaustion, retroactive changes? |
| **Explanation capability** | Can the system say WHY something was denied? |

---

## What We're NOT Specifying

- How to represent coverage rules (code, config, DSL?)
- Which specific rules to implement
- Database schema
- API design
- UI requirements

**That's on you.**

---

## Submission

Make sure your submission contains the following:

| Required | Description |
|----------|-------------|
| `app/` | Your application code |
| `docs/domain-model.md` | Entities, relationships, state machines |
| `docs/decisions.md` | What you built, what you didn't, assumptions |
| `docs/self-review.md` | Honest assessment of your own code |
| `ai-artifacts/` | Chat exports, prompts, AI corrections |
| `README.md` | Setup and run instructions |
| `.git/` | Your commit history (zip must include this folder) |

Submit as a zip/tarball. We review your commit history to understand how you approached the problem.

---

## Note

If you proceed to the next round, we'll extend this system together. Likely: adding an **appeals workflow** or **eligibility verification**. Write code you can explain and modify.

---

**Show us how you model a domain.**

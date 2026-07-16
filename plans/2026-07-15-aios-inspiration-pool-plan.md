# AIOS Inspiration Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn validated cognitive inspiration artifacts into pending candidates, require an explicit user decision, and store accepted ideas in a project-isolated Inspiration Pool.

**Architecture:** `CognitiveAssessment` remains immutable and authoritative for what the engine proposed. An idempotent `InspirationProjector` creates pending candidates from validated `kind=inspiration` artifacts; an API decision transaction creates an `Inspiration` only when the user accepts. Pool lifecycle changes are separate from candidate decisions and cannot create tasks or call Agents.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic v2, PostgreSQL 16, Alembic, pytest, React Native + Expo 52.

---

## Non-Negotiable Boundaries

- A pending candidate is not long-term memory and is not an accepted inspiration.
- Only a user actor can accept or reject a candidate in this plan.
- Acceptance creates exactly one `Inspiration`; retries return the same records.
- Candidate projection never changes the Assistant reply, Turn status, or execution state.
- `converted_to_task` and `evolved` are reserved for later Execution and Evolution services.
- Every candidate and Inspiration is either global (`project_id=NULL`) or belongs to one resolved project; no implicit reassignment is allowed.

## File Map

- Create `backend/app/inspiration/base.py`: enums, transition policy and projection protocol.
- Create `backend/app/inspiration/service.py`: idempotent candidate projection and decision transaction.
- Create `backend/app/models/inspiration.py`: candidate and accepted Inspiration ORM models.
- Create `backend/alembic/versions/0005_create_inspiration_pool.py`: tables, indexes and constraints.
- Create `backend/app/schemas/inspiration.py`: API request and response contracts.
- Create `backend/app/api/inspiration.py`: candidate decision and pool endpoints.
- Modify `backend/app/api/router.py`: register inspiration routes.
- Modify `backend/app/conversation/service.py`: invoke the optional projector after a successful Assessment.
- Modify `backend/app/conversation/dependencies.py`: assemble the projector behind a feature flag.
- Modify `backend/app/config.py` and `backend/.env.example`: candidate feature configuration.
- Modify `mobile/src/api/types.ts` and `mobile/src/api/client.ts`: mobile contracts and API methods.
- Create `mobile/src/components/InspirationCandidateBar.tsx`: explicit accept/reject control.
- Create `mobile/src/components/InspirationPool.tsx`: accepted idea list and lifecycle controls.
- Modify `mobile/App.tsx`: load and render pending candidates and the pool.

## Task 1: Domain Contracts And Transition Policy

**Files:**

- Create: `backend/app/inspiration/__init__.py`
- Create: `backend/app/inspiration/base.py`
- Test: `backend/tests/inspiration/test_base.py`

- [x] **Write failing contract tests**

Test strict enum values, project scope and lifecycle transitions:

```python
assert can_transition(InspirationLifecycle.ACTIVE, InspirationLifecycle.INCUBATING)
assert can_transition(InspirationLifecycle.ARCHIVED, InspirationLifecycle.ACTIVE)
assert not can_transition(
    InspirationLifecycle.ACTIVE,
    InspirationLifecycle.CONVERTED_TO_TASK,
)
```

Also prove Pydantic rejects blank titles, out-of-range confidence, extra fields and a resolved project without `project_id`.

- [x] **Run tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\inspiration\test_base.py -q
```

Expected: import failure because `app.inspiration.base` does not exist.

- [x] **Implement strict contracts**

Define:

```python
class InspirationCandidateStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class InspirationLifecycle(str, Enum):
    ACTIVE = "active"
    INCUBATING = "incubating"
    EVOLVED = "evolved"
    CONVERTED_TO_TASK = "converted_to_task"
    ARCHIVED = "archived"


class InspirationProjector(Protocol):
    async def project(self, assessment: CognitiveAssessment) -> list[InspirationCandidate]:
        ...
```

The user lifecycle endpoint may perform only `active <-> incubating`, `active|incubating -> archived`, and `archived -> active`. Derived states are not accepted from this endpoint.

- [x] **Run tests and verify GREEN**

- [x] **Commit Task 1**

```powershell
git add backend/app/inspiration backend/tests/inspiration
git commit -m "feat: define inspiration pool contracts"
```

## Task 2: PostgreSQL Candidate And Pool Models

**Files:**

- Create: `backend/app/models/inspiration.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0005_create_inspiration_pool.py`
- Test: `backend/tests/models/test_inspiration_models.py`

- [x] **Write failing model tests**

Cover:

- unique `(assessment_id, artifact_index)` projection identity;
- one Inspiration per accepted candidate;
- pending/accepted/rejected exact states;
- confidence and nonblank title/content constraints;
- candidate project ID equals its accepted Inspiration project ID;
- invalid lifecycle values fail at the database boundary.

- [x] **Run tests and verify RED**

Expected: model import failure.

- [x] **Implement ORM models**

`InspirationCandidate` fields:

```text
id, session_id, turn_id, source_message_id, assessment_id, artifact_index,
project_id?, title, content, confidence, status, decision_reason?,
created_at, decided_at
```

`Inspiration` fields:

```text
id, project_id?, origin_candidate_id UNIQUE, title, content,
lifecycle_status, version, created_at, updated_at
```

Use `RESTRICT` foreign keys and database checks. Candidate rows are immutable except `status`, `decision_reason` and `decided_at`; Inspiration content is not editable in this MVP.

- [x] **Create migration `0005_create_inspiration_pool`**

Create both tables and indexes for `(session_id, status)`, `(project_id, lifecycle_status)` and `origin_candidate_id`. Keep `origin_candidate_id` non-null in this migration; the Evolution migration may add a second, mutually exclusive proposal origin.

- [x] **Run model tests, migration upgrade/downgrade/upgrade and `alembic check`**

Use only the protected test database for downgrade testing.

- [x] **Commit Task 2**

```powershell
git add backend/app/models backend/alembic/versions backend/tests/models
git commit -m "feat: persist inspiration candidates and pool"
```

## Task 3: Idempotent Assessment Projection

**Files:**

- Create: `backend/app/inspiration/service.py`
- Test: `backend/tests/inspiration/test_service.py`

- [x] **Write failing projection tests**

Prove that the projector:

- reads only validated `kind=inspiration` artifacts;
- creates one pending candidate per artifact index;
- copies `session_id`, `turn_id`, source user message and resolved `project_id`;
- returns the existing candidate on retry;
- creates no candidate for project clarification, invalid JSON or other artifact kinds;
- never commits or rolls back the caller transaction.

```python
first = await projector.project(assessment)
retry = await projector.project(assessment)
assert [item.id for item in first] == [item.id for item in retry]
```

- [x] **Run tests and verify RED**

- [x] **Implement `AssessmentInspirationProjector`**

Revalidate `assessment.proposed_artifacts` as `list[ProposedArtifact]`, query the source user Message, and map only Inspiration artifacts. Use the unique projection key to make retries safe. A malformed persisted artifact produces a sanitized `inspiration.projection.failed` audit event and no candidate.

- [x] **Run tests and verify GREEN**

- [x] **Commit Task 3**

```powershell
git add backend/app/inspiration/service.py backend/tests/inspiration/test_service.py
git commit -m "feat: project pending inspiration candidates"
```

## Task 4: Conversation Integration Behind A Feature Flag

**Files:**

- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/app/conversation/dependencies.py`
- Modify: `backend/app/conversation/service.py`
- Modify: `backend/tests/conversation/test_service.py`
- Modify: `backend/tests/api/test_conversations.py`

- [x] **Write failing integration tests**

Add coverage for text, transcript, ambiguous project, duplicate client message, LLM retry and projector failure. Assert that candidate creation does not change Assistant content, metadata, Turn status or Provider calls.

- [x] **Add configuration**

```python
inspiration_candidates_enabled: bool = True
```

When disabled, dependency assembly passes `None` and does not invoke the projector.

- [x] **Integrate after successful Assessment persistence**

Store the result of `CognitiveOrchestrator.assess_turn`. If it is non-null and the projector is configured, project pending candidates in the same caller transaction. Do not project from a failed assessment or from raw Engine output.

- [x] **Run conversation and API regressions**

- [x] **Commit Task 4**

```powershell
git add backend/app/config.py backend/.env.example backend/app/conversation backend/tests/conversation backend/tests/api
git commit -m "feat: create inspiration candidates from assessments"
```

## Task 5: Candidate Decision And Pool APIs

**Files:**

- Create: `backend/app/schemas/inspiration.py`
- Create: `backend/app/api/inspiration.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/api/test_inspiration.py`

- [x] **Write failing API tests**

Endpoints:

```text
GET  /api/v1/inspiration-candidates?session_id={id}&status=pending
POST /api/v1/inspiration-candidates/{id}/decision
GET  /api/v1/inspirations?project_id={id?}&lifecycle_status={status?}
GET  /api/v1/inspirations/{id}
POST /api/v1/inspirations/{id}/lifecycle
```

Test accepted/rejected decisions, same-decision idempotency, conflicting decision `409`, project isolation, global pool filtering, missing records, lifecycle rules and audit events.

- [x] **Implement decision transaction**

Lock the candidate. For `accepted`, update the candidate and create its `active` Inspiration atomically. For `rejected`, update only the candidate. Store actor type `user`, stable event types and no raw Cognitive Provider data.

- [x] **Implement read and lifecycle endpoints**

Return strict Pydantic responses. Reject `evolved` and `converted_to_task` lifecycle requests with `INSPIRATION_LIFECYCLE_RESERVED`; those states belong to later domain services.

- [x] **Run API tests and verify GREEN**

- [x] **Commit Task 5**

```powershell
git add backend/app/api backend/app/schemas backend/tests/api/test_inspiration.py
git commit -m "feat: review and browse inspirations"
```

## Task 6: Expo Candidate And Pool Experience

**Files:**

- Modify: `mobile/src/api/types.ts`
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/api/client.test.ts`
- Create: `mobile/src/components/InspirationCandidateBar.tsx`
- Create: `mobile/src/components/InspirationPool.tsx`
- Modify: `mobile/src/components/components.test.tsx`
- Modify: `mobile/App.tsx`

- [x] **Write failing client and component tests**

Cover list/decision/lifecycle URLs, pending-state controls, disabled buttons during a request, accepted candidate removal, rejected candidate removal, pool loading, active/incubating/archive controls and API error recovery.

- [x] **Implement mobile API contracts and methods**

Use discriminated string unions matching backend enums. Do not reuse `MemoryCandidate` because memory and inspiration have different lifecycle semantics.

- [x] **Implement candidate bar and pool view**

Use icon buttons with accessible labels for accept, reject, incubate, reactivate and archive. Keep the chat as the default screen; expose the pool from the existing drawer rather than adding a marketing or tutorial screen.

- [x] **Run Jest, TypeScript and Expo dependency checks**

```powershell
cd mobile
npm test
npx tsc --noEmit
npx expo install --check
```

- [x] **Commit Task 6**

```powershell
git add mobile
git commit -m "feat: review inspirations on mobile"
```

## Task 7: Final Verification And Memory

**Files:**

- Modify: `docs/architecture/exec-architecture.html`
- Modify: `docs/PROJECT_MEMORY.md`
- Modify: this plan

- [x] **Run full backend and mobile verification**

- [x] **Run protected `0005 -> 0004 -> 0005` migration verification and `alembic check`**

- [x] **Upgrade the development database only after all checks pass**

- [x] **Update architecture and project memory**

Record exact test counts, feature flag behavior, migration head, API paths and the rule that only accepted candidates enter the pool.

- [x] **Commit the Inspiration Pool milestone**

```powershell
git add docs
git commit -m "docs: record inspiration pool milestone"
```

## Exit Criteria

- Cognitive inspiration artifacts create pending candidates exactly once.
- A user can accept or reject each candidate; acceptance alone creates a pool item.
- Pool data is project isolated, auditable and available on mobile.
- No candidate or lifecycle action invokes an Agent or authorizes execution.
- The Idea Evolution plan can consume only accepted `Inspiration` rows without changing Conversation or Voice contracts.

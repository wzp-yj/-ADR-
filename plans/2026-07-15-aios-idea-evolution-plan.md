# AIOS Idea Evolution Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover explainable relationships and new long-term directions across accepted inspirations, persist pending proposals, and create or version an `IdeaDirection` only after user approval.

**Architecture:** The engine is a pure analysis interface over accepted, project-scoped Inspiration and existing IdeaDirection snapshots. A replaceable Retriever supplies a bounded corpus, a replaceable Evolution Engine emits strict drafts, and an Orchestrator validates, deduplicates and persists pending proposals. Review transactions alone may create relations or append versioned IdeaDirections; original Inspirations remain immutable evidence and no proposal can create an execution task or call an Agent.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic v2, PostgreSQL 16, Alembic, pytest, React Native + Expo 52. PostgreSQL retrieval is the first implementation; pgvector, Milvus and graph storage remain behind protocols.

---

## Preconditions

- Complete `docs/plans/2026-07-15-aios-inspiration-pool-plan.md` first.
- Consume only `Inspiration` rows created from accepted candidates.
- Keep `relate`, `create_direction` and `update_direction` as the only MVP proposal types.
- Preserve every source Inspiration. Direction acceptance creates links and versions; it never replaces, deletes or silently changes source lifecycle.
- Converting a direction to a task remains outside this plan and must enter the future `ExecutionTaskDraft` confirmation flow.

## File Map

- Create `backend/app/evolution/base.py`: requests, drafts, enums, Retriever and Engine protocols.
- Create `backend/app/evolution/retriever.py`: bounded PostgreSQL corpus retriever for Inspirations and existing directions.
- Create `backend/app/evolution/rules.py`: deterministic relation and theme signals.
- Create `backend/app/evolution/hybrid.py`: optional semantic Provider composition.
- Create `backend/app/evolution/service.py`: scan, validation, deduplication and review transactions.
- Create `backend/app/models/evolution.py`: proposals, members, relations, versioned directions and scan attempts.
- Create `backend/alembic/versions/0006_create_idea_evolution.py`: evolution proposal, relation and IdeaDirection persistence.
- Create `backend/app/schemas/evolution.py` and `backend/app/api/evolution.py`: manual scan, listing and review APIs.
- Create `backend/app/evolution/worker.py`: one-shot scheduled scan runner with PostgreSQL advisory locking.
- Create `backend/scripts/run_evolution_scan.py`: scheduler-safe command entry point.
- Modify mobile API types/client and add proposal review components.

## Task 1: Strict Evolution Contracts

**Files:**

- Create: `backend/app/evolution/__init__.py`
- Create: `backend/app/evolution/base.py`
- Test: `backend/tests/evolution/test_base.py`

- [x] **Write failing contract tests**

Cover exact enum values, member cardinality, project scope, confidence, nonblank evidence and forbidden execution fields.

```python
class RelationType(str, Enum):
    DUPLICATES = "duplicates"
    EXTENDS = "extends"
    SUPPORTS = "supports"
    CONFLICTS = "conflicts"
    DEPENDS_ON = "depends_on"
    PART_OF = "part_of"


class EvolutionProposalType(str, Enum):
    RELATE = "relate"
    CREATE_DIRECTION = "create_direction"
    UPDATE_DIRECTION = "update_direction"
```

Add strict `DirectionKind`, `DirectionMaturity` and `DirectionEvidenceRole` enums. `EvolutionProposalDraft` requires at least two distinct member IDs for `relate`, at least three for `create_direction`, a target direction plus new evidence for `update_direction`, a deterministic `evidence_fingerprint`, a human-readable explanation, uncertainty text and an explicit impact preview. Direction drafts also require a thesis, synthesis, maturity, opportunity, tensions and open questions.

- [x] **Run tests and verify RED**

- [x] **Implement contracts and protocols**

```python
class EvolutionRetriever(Protocol):
    async def retrieve(self, request: EvolutionScanRequest) -> EvolutionCorpus:
        ...


class IdeaEvolutionEngine(Protocol):
    name: str
    version: str

    async def analyze(
        self,
        request: EvolutionRequest,
    ) -> list[EvolutionProposalDraft]:
        ...
```

All Pydantic models use `extra="forbid"`. Neither request nor draft contains execution authorization.

- [x] **Run tests and verify GREEN**

- [x] **Commit Task 1**

```powershell
git add backend/app/evolution backend/tests/evolution
git commit -m "feat: define idea evolution contracts"
```

## Task 2: Evolution Persistence And Migration

**Files:**

- Create: `backend/app/models/evolution.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0006_create_idea_evolution.py`
- Test: `backend/tests/models/test_evolution_models.py`

- [x] **Write failing database tests**

Test proposal/member uniqueness, relation uniqueness, direction/version/member uniqueness, immutable version numbering, exact state checks, project scope, confidence, nonblank text, deduplication key and scan-attempt idempotency. Prove no relation or direction exists before proposal acceptance.

- [x] **Implement models**

`EvolutionProposal`:

```text
id, project_id?, proposal_type, relation_type?, target_direction_id?, title, summary,
explanation, uncertainty, impact_preview, evidence JSONB,
evidence_fingerprint, confidence, engine_name, engine_version,
provider_name?, provider_model?, status, deduplication_key,
created_at, decided_at, snoozed_until?
```

`EvolutionProposalMember` stores `(proposal_id, inspiration_id, member_order, role)` with a unique pair. `InspirationRelation` stores canonical source/target IDs, relation type, accepted origin proposal, confidence and active/superseded status. `IdeaDirection` owns project scope and lifecycle; `IdeaDirectionVersion` stores immutable versioned thesis/synthesis/maturity fields and the accepted origin proposal; `IdeaDirectionMember` links original Inspirations with core/supporting/contradicting/branch roles and first-linked version. `EvolutionScanAttempt` stores scope, scan kind, cursor, status, sanitized error code and timestamps.

- [x] **Preserve source Inspirations and version directions**

Migration `0006` leaves `inspirations.origin_candidate_id` unchanged and creates `idea_directions`, `idea_direction_versions` and `idea_direction_members`. Add database constraints for direction version uniqueness, one origin proposal per version, valid evidence roles and a non-empty thesis; the review service later verifies that the origin proposal is accepted and in the same project scope. Original Inspirations are never rewritten into synthetic theme rows.

- [x] **Create migration and verify on the protected test database**

Run `0006 -> 0005 -> 0006` and `alembic check`. Never downgrade the development database.

- [x] **Commit Task 2**

```powershell
git add backend/app/models backend/alembic/versions backend/tests/models
git commit -m "feat: persist evolution proposals and relations"
```

## Task 3: Replaceable PostgreSQL Evolution Retriever

**Files:**

- Create: `backend/app/evolution/retriever.py`
- Test: `backend/tests/evolution/test_retriever.py`

- [x] **Write failing retrieval tests**

Prove strict project filtering, global-scope filtering, accepted Inspiration-only input, direction project filtering, lifecycle filtering, recent-window bounds, maximum row count, stable ordering and no cross-project text leakage.

- [x] **Implement `PostgresEvolutionRetriever`**

First query a bounded Inspiration set by `project_id`, lifecycle and time window, then load bounded active/incubating IdeaDirection snapshots for the same scope. Rank Inspiration text with normalized title/content token overlap and Unicode character trigrams in application code; this supports Chinese without requiring a privileged database extension. Return a strict `EvolutionCorpus` without ORM objects.

Configuration:

```python
evolution_retrieval_limit: int = Field(default=300, ge=2, le=2000)
evolution_recent_days: int = Field(default=3650, ge=1)
```

- [x] **Prove storage replacement does not affect the Engine contract**

Add a fake Retriever test. No code outside dependency assembly imports PostgreSQL-specific classes.

- [x] **Run tests and verify GREEN**

- [x] **Commit Task 3**

```powershell
git add backend/app/evolution/retriever.py backend/tests/evolution/test_retriever.py backend/app/config.py backend/.env.example
git commit -m "feat: retrieve bounded inspiration candidates"
```

## Task 4: Deterministic And Hybrid Evolution Engines

**Files:**

- Create: `backend/app/evolution/rules.py`
- Create: `backend/app/evolution/hybrid.py`
- Create: `backend/app/evolution/dependencies.py`
- Test: `backend/tests/evolution/test_rules.py`
- Test: `backend/tests/evolution/test_hybrid.py`

- [x] **Write failing deterministic examples**

Cover exact duplicates, one idea extending another, explicit conflict language, shared-theme clusters, unrelated ideas and project isolation. Every draft must cite member IDs and timestamps.

- [x] **Implement conservative deterministic analysis**

Generate `relate` only for high-confidence lexical or explicit relation signals. Generate `create_direction` only when at least three Inspirations from at least two Turns share a stable theme signal. Generate `update_direction` only when new evidence materially supports, contradicts, extends or branches an existing direction. Low-confidence input produces no draft rather than inventing a relationship.

- [x] **Implement `HybridIdeaEvolutionEngine`**

The semantic engine is optional. It may synthesize a direction thesis, opportunity, tensions and open questions, but cannot change project scope, member IDs, direction IDs or accepted state. Revalidate every cited member against the retrieved corpus, reject uncited claims and sanitize Provider failures. Retain deterministic relation drafts when the Provider is unavailable.

- [x] **Add dependency override points**

Expose `get_evolution_retriever` and `get_idea_evolution_engine`. Default to PostgreSQL Retriever + deterministic engine with `semantic=None`; OpenAI-compatible, Alibaba or local-vLLM semantic providers remain replaceable adapters.

- [x] **Run tests and verify GREEN**

- [x] **Commit Task 4**

```powershell
git add backend/app/evolution backend/tests/evolution
git commit -m "feat: analyze inspiration evolution"
```

## Task 5: Scan Orchestration, Deduplication And Recovery

**Files:**

- Create: `backend/app/evolution/service.py`
- Modify: `backend/app/models/evolution.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/alembic/versions/0006_create_idea_evolution.py`
- Test: `backend/tests/evolution/test_service.py`
- Test: `backend/tests/models/test_evolution_models.py`

- [x] **Write failing orchestration tests**

Cover manual, event and scheduled scan kinds; same-cursor idempotency; pending proposal deduplication; rejected proposal suppression; new-evidence reopening; Provider failure; malformed drafts; and transaction ownership.

- [x] **Implement stable deduplication**

Compute:

```text
deduplication_key = sha256(
  project_scope + proposal_type + relation_type + target_direction_id + sorted_member_ids
)
```

Store a separate evidence fingerprint. A rejected key remains suppressed until member IDs or evidence roles change; Provider wording changes do not reopen it. A retry with the same scan cursor returns the existing attempt and proposals. `evolution_scan_proposals` records the many-to-many scan/proposal trace, while `(deduplication_key, evidence_fingerprint)` is jointly unique so materially changed evidence can reopen a rejected shape.

- [x] **Persist pending proposals only**

The Orchestrator validates drafts, writes members, strict `direction_payload`, scan links and audit events, and never creates relations, directions or direction versions. Failures record stable error codes without Provider raw output or hidden reasoning.

- [x] **Run tests and verify GREEN**

- [x] **Commit Task 5**

```powershell
git add backend/app/evolution/service.py backend/tests/evolution/test_service.py
git commit -m "feat: orchestrate evolution proposal scans"
```

## Task 6: Proposal Review Transactions And APIs

**Files:**

- Create: `backend/app/schemas/evolution.py`
- Create: `backend/app/api/evolution.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/tests/api/test_evolution.py`

- [x] **Write failing API tests**

Endpoints:

```text
POST /api/v1/evolution/scans
GET  /api/v1/evolution/proposals?project_id={id?}&status=pending
GET  /api/v1/evolution/proposals/{id}
POST /api/v1/evolution/proposals/{id}/decision
GET  /api/v1/idea-directions?project_id={id?}
GET  /api/v1/idea-directions/{id}
```

Decision values are `accepted`, `rejected` and `snoozed`; snooze requires a future timestamp. Test cross-project hiding, same-decision idempotency, conflicting decision, invalid member lifecycle and sanitized output.

- [x] **Implement accepted `relate` transaction**

Lock proposal and members, verify all Inspirations remain in scope, create one active relation, mark proposal accepted and append audit events in one caller transaction.

- [x] **Implement accepted `create_direction` transaction**

Lock the proposal and source Inspirations, verify at least three accepted same-scope members from at least two Turns, create one IdeaDirection, version 1 and evidence-role members, mark the proposal accepted and append audits atomically. Do not alter source Inspiration content or lifecycle.

- [x] **Implement accepted `update_direction` transaction**

Lock the proposal, target direction and current version; verify at least one new same-scope Inspiration; append version `N + 1`, update or add evidence-role members, advance `current_version`, mark the proposal accepted and append audits atomically. Rejection and snooze create no relations, directions, versions or source lifecycle changes.

- [x] **Run API tests and verify GREEN**

- [x] **Commit Task 6**

```powershell
git add backend/app/api backend/app/schemas backend/tests/api/test_evolution.py
git commit -m "feat: review idea evolution proposals"
```

## Task 7: Event And Scheduled Scan Runner

**Files:**

- Create: `backend/app/evolution/worker.py`
- Create: `backend/scripts/run_evolution_scan.py`
- Modify: `backend/app/inspiration/service.py`
- Test: `backend/tests/evolution/test_worker.py`

- [x] **Write failing worker tests**

Prove an accepted Inspiration enqueues an event scan marker, scheduled scans claim one project at a time, a PostgreSQL advisory lock prevents duplicate workers, cursor advancement happens only after success, and failures are retryable.

- [x] **Implement one-shot worker entry point**

The command reads enabled scopes, acquires an advisory lock, invokes the Orchestrator and exits with a nonzero code only for infrastructure failure. It does not run an unbounded loop inside FastAPI.

Configuration:

```python
evolution_scans_enabled: bool = False
evolution_daily_scan_hour: int = Field(default=3, ge=0, le=23)
evolution_weekly_scan_day: int = Field(default=0, ge=0, le=6)
```

Deployment may schedule the one-shot command with Windows Task Scheduler, cron or a container scheduler. The database attempt/cursor contract keeps those schedulers replaceable.

Accepted Inspiration writes an immutable `evolution.scan.requested` audit marker in the same caller transaction. Each worker invocation handles at most one unit in this order: pending event marker, due global daily scan, then one due active-project weekly scan. Completed event cursors are excluded in SQL so old immutable markers cannot starve later work. Session-level advisory locks are released before commit or rollback.

- [x] **Run worker tests and verify GREEN**

- [x] **Commit Task 7**

```powershell
git add backend/app/evolution backend/scripts backend/app/inspiration/service.py backend/tests/evolution
git commit -m "feat: schedule idempotent evolution scans"
```

## Task 8: Expo Proposal Review

**Files:**

- Modify: `mobile/src/api/types.ts`
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/api/client.test.ts`
- Create: `mobile/src/components/EvolutionProposalList.tsx`
- Create: `mobile/src/components/EvolutionProposalDetail.tsx`
- Modify: `mobile/src/components/components.test.tsx`
- Modify: `mobile/App.tsx`

- [x] **Write failing API and component tests**

Test project filtering, proposal type labels, evidence timeline and roles, direction thesis, maturity, changed-from-previous summary, uncertainty, impact preview, accept/reject/snooze actions, request-disabled controls and refresh recovery.

- [x] **Implement proposal list and detail views**

The user must see involved Inspirations and timestamps, why they may be related, confidence, uncertainty, and the exact effect of acceptance. Direction proposals show thesis, synthesis, maturity, opportunity, tensions, open questions and the previous version when applicable. Add a read-only direction list/detail timeline. Do not expose engine raw output and do not offer task execution actions.

- [x] **Run mobile verification**

```powershell
cd mobile
npm test
npx tsc --noEmit
npx expo install --check
```

- [x] **Commit Task 8**

```powershell
git add mobile
git commit -m "feat: review idea evolution on mobile"
```

## Task 9: Final Verification, Architecture And Project Memory

**Files:**

- Modify: `docs/architecture/exec-architecture.html`
- Modify: `docs/PROJECT_MEMORY.md`
- Modify: this plan

- [x] **Run full backend and mobile verification**

- [x] **Run protected migration round trip and `alembic check`**

- [x] **Upgrade the development database only after all checks pass**

- [x] **Verify manual scan and review with real PostgreSQL data**

Use accepted test Inspirations across different dates, verify one pending proposal, reject it and prove no relation or direction appears; create and accept a new direction proposal, then accept an update proposal and prove the original Inspirations remain unchanged while direction versions and evidence roles are complete.

- [x] **Update architecture and project memory with exact evidence**

- [x] **Commit the Idea Evolution milestone**

```powershell
git add docs
git commit -m "docs: record idea evolution milestone"
```

## Exit Criteria

- Only accepted, correctly scoped Inspirations enter analysis.
- The system can explain a relationship or emerging direction with member timestamps, evidence roles and uncertainty.
- Rejected or snoozed proposals do not alter Inspirations, relations or directions.
- Accepted proposals update proposal, members, relations or direction versions atomically.
- Every IdeaDirection is traceable through immutable versions to unchanged source Inspirations and source Turns.
- Scheduled scans are idempotent and disabled by default until deployment scheduling is configured.
- Retriever, Engine, semantic Provider and scheduler can be replaced independently.
- No Evolution path creates an execution task, invokes an Agent or bypasses either confirmation gate.

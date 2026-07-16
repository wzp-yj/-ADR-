# AIOS P1 Conversation Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a persistent, idempotent and auditable text-conversation backend that resolves project context, proposes confirmable memory candidates and keeps all model providers replaceable.

**Architecture:** FastAPI endpoints call a focused `ConversationService`. The service persists input before external calls, delegates project resolution and context assembly through typed interfaces, routes model requests through `LLMRouter`, and writes append-only audit events. PostgreSQL owns state and concurrency; no queue, vector retrieval or voice transport is required for this plan.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL 16, Alembic, pytest, httpx.

**Design:** `docs/specs/2026-07-15-aios-p1-conversation-core-design.md`

**Status:** P1-A backend completed and verified on 2026-07-15. P1-B mobile text UI is tracked as the next independent plan.

---

## File Map

Create:

- `backend/app/models/conversation.py`: session, turn and message persistence.
- `backend/app/models/context.py`: project context item persistence.
- `backend/app/models/memory.py`: confirmable memory candidate persistence.
- `backend/app/models/audit.py`: append-only audit events.
- `backend/app/schemas/conversation.py`: API request and response contracts.
- `backend/app/schemas/memory.py`: memory decision contracts.
- `backend/app/conversation/domain.py`: typed context and memory interfaces.
- `backend/app/conversation/context.py`: deterministic resolver and bounded context assembler.
- `backend/app/conversation/memory.py`: explicit-memory candidate extractor.
- `backend/app/conversation/service.py`: Turn state machine and transaction orchestration.
- `backend/app/conversation/dependencies.py`: replaceable service dependencies.
- `backend/app/llm/router.py`: Provider selection and unavailable behavior.
- `backend/app/api/conversations.py`: conversation and Turn endpoints.
- `backend/app/api/memory.py`: candidate decision endpoint.
- `backend/alembic/versions/0002_create_conversation_core.py`: P1 tables and constraints.
- `backend/tests/api/test_health_contract.py`: live/ready and error contract tests.
- `backend/tests/models/test_conversation_models.py`: persistence constraints and state tests.
- `backend/tests/conversation/test_context.py`: project resolution and context budget tests.
- `backend/tests/conversation/test_memory.py`: explicit candidate extraction tests.
- `backend/tests/conversation/test_service.py`: orchestration, idempotency and failure tests.
- `backend/tests/api/test_conversations.py`: public API integration tests.
- `backend/tests/api/test_memory_candidates.py`: decision endpoint tests.

Modify:

- `backend/app/errors.py`: stable application error shape.
- `backend/app/main.py`: exception handlers and request ID middleware.
- `backend/app/api/health.py`: compatibility health endpoint plus live/ready.
- `backend/app/api/router.py`: register conversation and memory routers.
- `backend/app/models/__init__.py`: register every new model.
- `backend/alembic/env.py`: import model metadata.
- `backend/app/llm/base.py`: replace raw dictionaries with typed requests and responses.
- `backend/app/llm/openai_provider.py`: adapt the OpenAI SDK behind the typed contract.
- `backend/app/config.py`: conversation provider and context budget settings.
- `backend/tests/llm/test_openai_provider.py`: typed Provider contract tests.
- `docs/PROJECT_MEMORY.md`: milestone state and verification evidence.

## Task 1: Stable Errors And Health Semantics

- [ ] **Step 1: Write failing contract tests**

Add tests proving:

```python
assert (await client.get("/api/v1/health/live")).json() == {"status": "ok"}
assert (await db_client.get("/api/v1/health/ready")).status_code in {200, 503}

response = await db_client.get(
    "/api/v1/projects/00000000-0000-0000-0000-000000000000"
)
assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
assert response.json()["error"]["request_id"]
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/api/test_health_contract.py -q
```

Expected: new routes or unified `error` body are missing.

- [ ] **Step 3: Implement error and health contracts**

Use this application error boundary:

```python
class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)
```

Install middleware that accepts or generates `X-Request-ID`, returns it as a response header, and makes it available to the exception handler. Keep `/api/v1/health` for P0 compatibility, add `/health/live`, and make `/health/ready` report database and configured conversation Provider readiness.

- [ ] **Step 4: Run focused and regression tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/api/test_health_contract.py backend/tests/api/test_health.py backend/tests/api/test_projects.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/errors.py backend/app/main.py backend/app/api/health.py backend/tests/api/test_health_contract.py backend/tests/api/test_health.py
git commit -m "feat: standardize health and API errors"
```

## Task 2: Conversation Persistence And Migration

- [ ] **Step 1: Write failing model tests**

Cover these database invariants:

```python
assert session.project_id is None
assert turn.status == "accepted"
assert user_message.sequence_no == 1
assert candidate.status == "pending"
assert event.event_type == "message.accepted"
```

Also assert duplicate `(session_id, client_message_id)`, duplicate `(session_id, sequence_no)`, project-scoped memory without a project, and global memory with a project fail with `IntegrityError`.

- [ ] **Step 2: Run the model tests and verify import failure**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/models/test_conversation_models.py -q
```

Expected: new model modules do not exist.

- [ ] **Step 3: Implement models and migration**

Use PostgreSQL UUID, JSONB and timezone-aware timestamps. Every foreign key declares `ondelete="RESTRICT"`. Store enum values in bounded strings with `CheckConstraint`, avoiding PostgreSQL enum types so future adapters can extend values through normal migrations.

The migration creates tables in this order:

```text
conversation_sessions
conversation_turns
messages
project_context_items
memory_candidates
audit_events
```

Create these key indexes and constraints:

```text
UNIQUE (session_id, client_message_id) on conversation_turns
UNIQUE (session_id, sequence_no) on messages
UNIQUE (turn_id) WHERE role = 'user' on messages
UNIQUE (turn_id) WHERE role = 'assistant' on messages
CHECK ((scope = 'project' AND project_id IS NOT NULL)
    OR (scope = 'global' AND project_id IS NULL)) on memory_candidates
```

Import all models from `app.models.__init__` and import that package in Alembic `env.py`.

- [ ] **Step 4: Run model and migration verification**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/models/test_conversation_models.py backend/tests/test_migration_config.py -q
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic downgrade 0001_create_projects
..\.venv\Scripts\python.exe -m alembic upgrade head
Set-Location ..
```

Expected: tests pass and all three migration commands exit 0 against the dedicated test database configuration used for migration verification.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/models backend/alembic backend/tests/models backend/tests/test_migration_config.py
git commit -m "feat: persist auditable conversation state"
```

## Task 3: Typed LLM Provider And Router

- [ ] **Step 1: Replace Provider tests with typed request tests**

Construct requests with:

```python
request = LLMRequest(
    request_id=uuid.uuid4(),
    task=LLMTask.CONVERSATION,
    messages=[LLMMessage(role=LLMRole.USER, content="你好")],
    timeout_seconds=30,
)
```

Assert response `request_id`, `provider`, `model`, `content`, `usage` and `latency_ms`. Assert `LLMRouter` chooses an available default and raises `LLMConfigurationError` when none is available.

- [ ] **Step 2: Run tests and verify the old dictionary contract fails**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/llm -q
```

Expected: typed request classes and router are missing.

- [ ] **Step 3: Implement typed contracts and router**

Define:

```python
class LLMTask(str, Enum):
    CONVERSATION = "conversation"
    CONTEXT_RESOLUTION = "context_resolution"
    MEMORY_EXTRACTION = "memory_extraction"

class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
```

`LLMRouter` owns `dict[str, BaseLLMProvider]`, an availability map and a configured default. `OpenAIProvider` converts `LLMMessage` objects to SDK dictionaries internally. The public Provider interface never exposes `AsyncOpenAI` types.

- [ ] **Step 4: Run Provider tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/llm -q
```

Expected: all Provider and router tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/llm backend/app/config.py backend/tests/llm
git commit -m "feat: add typed replaceable LLM routing"
```

## Task 4: Context Resolution And Bounded Assembly

- [ ] **Step 1: Write resolver and budget tests**

Prove this priority order:

```text
explicit active project
session-bound active project
single project name contained in user text
multiple matching project names -> needs_clarification
no match -> no_project
```

Assert the resolver never changes `ConversationSession.project_id`. Seed accepted/rejected and cross-project memory candidates; assert only accepted global and resolved-project records enter context. Assert output length remains within `context_char_budget`.

- [ ] **Step 2: Run tests and verify missing implementation**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/conversation/test_context.py -q
```

- [ ] **Step 3: Implement domain types, resolver and assembler**

The deterministic resolver returns:

```python
ResolvedContext(
    decision=ContextDecision.NEEDS_CLARIFICATION,
    project_id=None,
    confidence=0.0,
    candidates=matches,
    clarification_question="你指的是哪个项目？",
    evidence=["multiple_project_name_matches"],
    resolver_name="deterministic",
    resolver_version="1",
)
```

The assembler queries recent complete messages in descending sequence order, then reverses them for chronological prompts. It adds active project context and accepted memories while respecting separate recent-message and total character budgets from settings. Every assembled item retains its source type and source UUID.

- [ ] **Step 4: Run context tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/conversation/test_context.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/conversation/domain.py backend/app/conversation/context.py backend/app/config.py backend/tests/conversation/test_context.py
git commit -m "feat: resolve projects and bound model context"
```

## Task 5: Confirmable Memory Candidates

- [ ] **Step 1: Write extractor tests**

Use explicit phrases as the deterministic P1 behavior:

```python
assert extractor.extract("请记住：我偏好先看修改原因", resolved_project=None)[0].scope == "global"
assert extractor.extract("记住这个项目使用 PostgreSQL", resolved_project=project_id)[0].project_id == project_id
assert extractor.extract("今天天气不错", resolved_project=None) == []
```

Assert created candidates remain `pending` and reference the source message.

- [ ] **Step 2: Run tests and verify missing extractor**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/conversation/test_memory.py -q
```

- [ ] **Step 3: Implement replaceable extractor**

Define a `MemoryExtractor` protocol and `ExplicitMemoryExtractor`. It recognizes `请记住：`, `请记住`, `记住：`, `remember:` and `remember ` at the start of trimmed user input, removes the marker, rejects empty content, assigns project scope when a project is resolved and global scope otherwise, and emits `kind="fact"` with confidence `1.0`. It never accepts a candidate.

- [ ] **Step 4: Run memory tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/conversation/test_memory.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/conversation/memory.py backend/tests/conversation/test_memory.py
git commit -m "feat: extract confirmable explicit memories"
```

## Task 6: Conversation Service State Machine

- [ ] **Step 1: Write orchestration tests with a fake Provider**

Cover:

```text
input persists before Provider call
duplicate client_message_id returns existing Turn without a second call
explicit project resolves without changing session binding
ambiguous project produces a clarification Assistant message
Provider unavailable preserves the user message and Turn
successful reply creates one Assistant message and audit timeline
retry reuses the original user message
memory extraction failure does not fail a completed reply
```

The fake Provider records call count and receives `LLMRequest`; a failing fake queries the database in its `chat` method to prove the user message is already committed.

- [ ] **Step 2: Run tests and verify missing service**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/conversation/test_service.py -q
```

- [ ] **Step 3: Implement service and dependencies**

`create_turn` performs two transaction phases:

```text
Phase 1: lock session -> idempotency lookup -> insert Turn -> allocate sequence ->
         insert user message -> insert message.accepted event -> commit
Phase 2: resolve -> persist snapshot -> clarify or call Provider -> persist reply ->
         extract pending memories -> append events -> commit
```

Duplicate requests return the existing Turn immediately. Each state transition validates the current state and increments `version`. Provider errors are mapped to `provider_unavailable` or `failed` without deleting Phase 1 data.

- [ ] **Step 4: Run service tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/conversation/test_service.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/conversation/service.py backend/app/conversation/dependencies.py backend/tests/conversation/test_service.py
git commit -m "feat: orchestrate durable conversation turns"
```

## Task 7: Conversation And Memory APIs

- [ ] **Step 1: Write API integration tests**

Cover creation, list, detail, cursor message pagination, Turn submission, Turn lookup, retry, event timeline and memory decisions. Assert a repeated `client_message_id` returns status 200 with the same Turn ID. Assert accepting twice is idempotent and accepting after rejection returns 409.

- [ ] **Step 2: Run API tests and verify missing routes**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/api/test_conversations.py backend/tests/api/test_memory_candidates.py -q
```

- [ ] **Step 3: Implement schemas and routes**

Request contracts:

```python
class TurnCreate(BaseModel):
    client_message_id: UUID
    input: TurnInput
    project_id: UUID | None = None

class MemoryDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
```

Return one `TurnResponse` containing the Turn, user message, optional Assistant message, context snapshot and pending memory candidates. Use `response.status_code = 200` for an idempotent duplicate and 201 for a newly persisted Turn.

- [ ] **Step 4: Run API and full backend tests**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/api/test_conversations.py backend/tests/api/test_memory_candidates.py -q
.venv\Scripts\python.exe -m pytest backend/tests -q
```

Expected: all backend tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/api backend/app/schemas backend/tests/api backend/app/api/router.py
git commit -m "feat: expose conversation and memory APIs"
```

## Task 8: Verification, Architecture And Project Memory

- [ ] **Step 1: Run migration round trip against the test database**

Set `DATABASE_URL` to the dedicated `aios_test` URL for these commands, then run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic downgrade 0001_create_projects
..\.venv\Scripts\python.exe -m alembic upgrade head
Set-Location ..
```

- [ ] **Step 2: Run repository-wide verification**

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
npm test -- --run --dir frontend
npm run build --prefix frontend
npx tsc --noEmit --project mobile/tsconfig.json
```

Expected: every command exits 0.

- [ ] **Step 3: Update architecture and memory**

Update `docs/architecture/exec-architecture.html` so its visible flow is conversation -> task draft -> first confirmation -> isolated Agent -> Diff/test review -> second confirmation -> apply. Update `docs/PROJECT_MEMORY.md` with implemented scope, excluded scope, migration revision, exact test counts and the next mobile-text milestone.

- [ ] **Step 4: Check docs and working tree**

```powershell
git diff --check
git status --short
```

Expected: only intended documentation changes remain before commit.

- [ ] **Step 5: Commit**

```powershell
git add docs/architecture/exec-architecture.html docs/PROJECT_MEMORY.md
git commit -m "docs: record P1 conversation milestone"
```

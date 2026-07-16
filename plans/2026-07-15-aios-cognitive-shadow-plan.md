# AIOS Cognitive Engine Shadow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, replaceable Cognitive Engine that classifies every persisted Turn in shadow mode without changing replies, creating candidates, or invoking Agents.

**Architecture:** `ConversationService` keeps ownership of Turn persistence and existing reply behavior. After deterministic project resolution, it passes bounded context to a side-effect-free `CognitiveEngine`; `CognitiveOrchestrator` validates and persists an immutable `CognitiveAssessment` plus audit events. The first production engine is deterministic with an optional semantic Provider interface, so OpenAI-compatible, Alibaba, Anthropic or local vLLM classification can be added without changing Conversation or persistence code.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy async, Pydantic v2, Alembic, pytest.

**Design:** `docs/specs/2026-07-15-aios-cognitive-idea-evolution-design.md`

**Scope Boundary:** This plan does not create Inspiration Candidates, merge ideas, create Execution Tasks, alter Assistant replies, add vector search, or call real semantic classification Providers. Those are separate follow-up plans after shadow assessments are observable and stable.

---

## Task 1: Strongly Typed Cognitive Contracts

**Files:**

- Create: `backend/app/cognitive/__init__.py`
- Create: `backend/app/cognitive/base.py`
- Create: `backend/tests/cognitive/__init__.py`
- Create: `backend/tests/cognitive/test_contracts.py`

- [x] **Write failing contract tests**

Cover enum values, confidence bounds, nonblank evidence, project resolution, proposed artifacts and request validation:

```python
def test_cognitive_decision_is_strongly_typed():
    decision = CognitiveDecision(
        request_id=uuid.uuid4(),
        primary_mode=InteractionMode.INSPIRATION,
        secondary_signals=["cross_project_idea"],
        thread_phase=ThreadPhase.EXPLORING,
        project_resolution=ProjectResolution(
            decision="resolved",
            project_id=uuid.uuid4(),
            confidence=0.94,
        ),
        confidence=0.91,
        needs_clarification=False,
        proposed_artifacts=[
            ProposedArtifact(
                kind=ArtifactKind.INSPIRATION,
                title="AI 操作系统",
                content="把多个 AI 能力组织成个人操作系统",
                confidence=0.91,
            )
        ],
        recommended_action=RecommendedAction.PROPOSE_INSPIRATION,
        evidence_summary="用户明确表示这是一个想法",
        engine_name="deterministic",
        engine_version="1",
    )
    assert decision.primary_mode == InteractionMode.INSPIRATION
    assert decision.proposed_artifacts[0].kind == ArtifactKind.INSPIRATION


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_cognitive_confidence_must_be_bounded(confidence: float):
    with pytest.raises(ValidationError):
        CognitiveDecision(
            request_id=uuid.uuid4(),
            primary_mode=InteractionMode.CASUAL_CHAT,
            secondary_signals=[],
            thread_phase=ThreadPhase.OPEN,
            project_resolution=ProjectResolution(
                decision="no_project",
                project_id=None,
                confidence=1.0,
            ),
            confidence=confidence,
            needs_clarification=False,
            proposed_artifacts=[],
            recommended_action=RecommendedAction.REPLY,
            evidence_summary="未检测到明确的任务或灵感表达",
            engine_name="deterministic",
            engine_version="1",
        )
```

- [x] **Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\cognitive\test_contracts.py -q
```

Expected: collection fails because `app.cognitive.base` does not exist.

- [x] **Implement the contracts**

Define these exact enums in `base.py`:

```python
class InteractionMode(str, Enum):
    CASUAL_CHAT = "casual_chat"
    DISCUSSION = "discussion"
    INSPIRATION = "inspiration"
    DECISION = "decision"
    TASK_INTENT = "task_intent"
    EXECUTION_INTENT = "execution_intent"
    VENTING = "venting"
    QUESTION = "question"


class ThreadPhase(str, Enum):
    OPEN = "open"
    EXPLORING = "exploring"
    CONVERGING = "converging"
    DECIDED = "decided"
    ACTION_READY = "action_ready"


class RecommendedAction(str, Enum):
    REPLY = "reply"
    CLARIFY = "clarify"
    PROPOSE_MEMORY = "propose_memory"
    PROPOSE_INSPIRATION = "propose_inspiration"
    PROPOSE_DECISION = "propose_decision"
    PROPOSE_TASK_DRAFT = "propose_task_draft"
    REQUEST_EXECUTION_CONFIRMATION = "request_execution_confirmation"


class ArtifactKind(str, Enum):
    MEMORY = "memory"
    INSPIRATION = "inspiration"
    DECISION = "decision"
    TASK_DRAFT = "task_draft"


class ProjectDecision(str, Enum):
    RESOLVED = "resolved"
    NEEDS_CLARIFICATION = "needs_clarification"
    NO_PROJECT = "no_project"
```

Define `ProjectResolution`, `ProposedArtifact`, `CognitiveMessage`, `CognitiveRequest` and `CognitiveDecision` as Pydantic models. `ProjectResolution.decision` uses `ProjectDecision`. All user-visible text uses `Field(min_length=1)` plus whitespace validators; all confidence fields use `Field(ge=0, le=1)`. `CognitiveRequest` contains `request_id`, `turn_id`, `session_id`, `user_text`, `recent_messages`, `session_project_id`, `resolved_project`, `accepted_memory_summaries`, `active_inspiration_summaries`, `previous_thread_phase` and `locale`. The two summary lists are empty in shadow mode but remain part of the stable contract for later adapters.

Define the replaceable interface and stable error:

```python
class CognitiveEngine(Protocol):
    name: str
    version: str

    async def assess(self, request: CognitiveRequest) -> CognitiveDecision:
        raise NotImplementedError


class CognitiveProviderError(Exception):
    def __init__(self, message: str, *, code: str, retryable: bool):
        self.code = code
        self.retryable = retryable
        super().__init__(message)
```

- [x] **Run contract tests and verify GREEN**

Expected: all contract tests pass.

- [x] **Commit Task 1**

```powershell
git add backend/app/cognitive backend/tests/cognitive
git commit -m "feat: define cognitive engine contracts"
```

## Task 2: Deterministic Classification And Replaceable Semantic Boundary

**Files:**

- Create: `backend/app/cognitive/rules.py`
- Create: `backend/app/cognitive/hybrid.py`
- Test: `backend/tests/cognitive/test_rules.py`
- Test: `backend/tests/cognitive/test_hybrid.py`

- [x] **Write failing deterministic behavior tests**

Use parameterized tests for explicit Chinese and English phrases:

```python
@pytest.mark.parametrize(
    ("text", "mode", "action"),
    [
        ("我有个想法，做一个 AI 操作系统", "inspiration", "propose_inspiration"),
        ("我决定先完成语音闭环", "decision", "propose_decision"),
        ("这个以后需要做成手机 App", "task_intent", "propose_task_draft"),
        ("确认后开始执行这些修改", "execution_intent", "request_execution_confirmation"),
        ("我只是吐槽一下，今天太烦了", "venting", "reply"),
        ("为什么这个接口会失败？", "question", "reply"),
        ("我们比较一下两种架构", "discussion", "reply"),
        ("今天天气不错", "casual_chat", "reply"),
    ],
)
async def test_explicit_modes(text, mode, action):
    result = await DeterministicCognitiveEngine().assess(request_for(text))
    assert result.primary_mode.value == mode
    assert result.recommended_action.value == action
```

Add explicit regressions proving `venting` does not propose a task and `execution_intent` never represents permission to execute.

- [x] **Run deterministic tests and verify RED**

Expected: import failure for `DeterministicCognitiveEngine`.

- [x] **Implement deterministic engine**

Use normalized text and ordered rule groups. High-risk order is fixed:

```python
RULE_ORDER = (
    InteractionMode.VENTING,
    InteractionMode.EXECUTION_INTENT,
    InteractionMode.DECISION,
    InteractionMode.INSPIRATION,
    InteractionMode.TASK_INTENT,
    InteractionMode.QUESTION,
    InteractionMode.DISCUSSION,
)
```

Each matched rule returns evidence labels, not hidden reasoning. Explicit matches use confidence `0.9`; question/discussion heuristics use `0.75`; default casual chat uses `0.6`. If `request.resolved_project.decision == "needs_clarification"`, return `needs_clarification=True` and `RecommendedAction.CLARIFY` without proposing an artifact.

Map modes to thread phases without making phase irreversible:

```python
MODE_PHASE = {
    InteractionMode.INSPIRATION: ThreadPhase.EXPLORING,
    InteractionMode.DISCUSSION: ThreadPhase.EXPLORING,
    InteractionMode.DECISION: ThreadPhase.DECIDED,
    InteractionMode.TASK_INTENT: ThreadPhase.CONVERGING,
    InteractionMode.EXECUTION_INTENT: ThreadPhase.ACTION_READY,
}
```

- [x] **Write failing hybrid boundary tests**

Create a fake semantic engine. Prove high-confidence deterministic results skip it, ambiguous results use it, and `CognitiveProviderError` safely returns the deterministic baseline:

```python
async def test_semantic_failure_falls_back_without_execution():
    semantic = FailingSemanticEngine()
    result = await HybridCognitiveEngine(
        deterministic=DeterministicCognitiveEngine(),
        semantic=semantic,
        semantic_threshold=0.8,
    ).assess(request_for("也许以后可以换个方向"))
    assert result.engine_name == "deterministic"
    assert result.recommended_action != RecommendedAction.REQUEST_EXECUTION_CONFIRMATION
```

- [x] **Implement `HybridCognitiveEngine`**

It always computes the deterministic baseline first. It calls the optional semantic engine only when baseline confidence is below `semantic_threshold`; it catches only `CognitiveProviderError`, appends a non-sensitive `semantic_provider_unavailable` signal and returns the baseline. Unknown exceptions propagate to the orchestrator for audit.

- [x] **Run all cognitive unit tests and verify GREEN**

Expected: contract, rules and hybrid tests pass.

- [x] **Commit Task 2**

```powershell
git add backend/app/cognitive backend/tests/cognitive
git commit -m "feat: classify cognitive interaction modes"
```

## Task 3: Immutable Cognitive Assessment Persistence

**Files:**

- Create: `backend/app/models/cognitive.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0004_create_cognitive_assessments.py`
- Test: `backend/tests/models/test_cognitive_models.py`

- [x] **Write failing model contract and constraint tests**

Test exact columns, timezone-aware timestamps, `(turn_id, revision)` uniqueness, confidence bounds, valid modes/phases/actions, nonblank evidence and self-revision linkage.

```python
async def test_assessment_revision_is_unique_per_turn(db_session):
    turn = await create_turn_record(db_session)
    db_session.add_all([
        assessment_values(turn.id, revision=1),
        assessment_values(turn.id, revision=1),
    ])
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [x] **Run model tests and verify RED**

Expected: `CognitiveAssessment` is missing.

- [x] **Implement model and migration**

Create `cognitive_assessments` with:

```text
id UUID PK
turn_id UUID NOT NULL FK conversation_turns RESTRICT
revision INTEGER NOT NULL DEFAULT 1
primary_mode VARCHAR(32) NOT NULL
secondary_signals JSONB NOT NULL DEFAULT []
thread_phase VARCHAR(32) NOT NULL
project_resolution JSONB NOT NULL DEFAULT {}
confidence NUMERIC(5,4) NOT NULL
needs_clarification BOOLEAN NOT NULL DEFAULT false
clarification_question TEXT NULL
proposed_artifacts JSONB NOT NULL DEFAULT []
recommended_action VARCHAR(64) NOT NULL
evidence_summary TEXT NOT NULL
engine_name VARCHAR(100) NOT NULL
engine_version VARCHAR(50) NOT NULL
provider_name VARCHAR(100) NULL
provider_model VARCHAR(255) NULL
supersedes_id UUID NULL FK cognitive_assessments RESTRICT
created_at TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(turn_id, revision)
```

Add database checks matching all contract enums, `revision > 0`, confidence range, nonblank engine/evidence, and `needs_clarification = false OR clarification_question IS NOT NULL`.

- [x] **Run model tests and protected migration roundtrip**

Run model tests, then against `aios_test`:

```powershell
$env:DATABASE_URL='postgresql+asyncpg://aios_test:aios_test@localhost:5433/aios_test'
cd backend
..\.venv\Scripts\python.exe -m alembic downgrade 0003_create_voice_transcriptions
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic check
```

Expected: downgrade/upgrade succeed and check reports no new operations.

- [x] **Commit Task 3**

```powershell
git add backend/app/models backend/alembic/versions backend/tests/models
git commit -m "feat: persist cognitive assessments"
```

## Task 4: Bounded Context And Idempotent Cognitive Orchestrator

**Files:**

- Create: `backend/app/cognitive/context.py`
- Create: `backend/app/cognitive/service.py`
- Test: `backend/tests/cognitive/test_context.py`
- Test: `backend/tests/cognitive/test_service.py`

- [x] **Write failing bounded context tests**

Prove the assembler keeps the current input complete in `user_text`, includes only historical messages in sequence order, copies the resolved project snapshot and previous latest assessment phase, respects a configurable history character budget and excludes other sessions. The database query also caps history at the latest 100 messages so a long session cannot be loaded fully before character trimming.

```python
assembled = await CognitiveContextAssembler(
    db_session, recent_char_budget=8000
).assemble(turn_id=turn.id, resolved_context=resolved)
assert assembled.user_text == "我有个新想法"
assert sum(len(item.content) for item in assembled.recent_messages) <= 8000
assert all(item.content != assembled.user_text for item in assembled.recent_messages)
```

- [x] **Implement `CognitiveContextAssembler`**

Query the latest 100 historical messages by `turn.session_id` with sequence numbers lower than the current user message, order descending to fill the budget, then restore ascending order for the request. Keep the complete current message only in `user_text`; never duplicate or truncate it inside the history budget. Never read raw audio or pending/rejected memory. In this shadow plan, accepted memory and inspiration summaries remain empty lists; their adapters are added by later plans.

- [x] **Write failing orchestrator tests**

Cover first assessment, duplicate retry, explicit revision, audit payload sanitization and unexpected engine failure:

```python
first = await orchestrator.assess_turn(turn.id, resolved_context=resolved)
duplicate = await orchestrator.assess_turn(turn.id, resolved_context=resolved)
assert first.id == duplicate.id
assert engine.calls == 1

result = await failing_orchestrator.assess_turn(turn.id, resolved_context=resolved)
assert result is None
assert await audit_exists("cognitive.assessment.failed", turn.id)
```

- [x] **Implement `CognitiveOrchestrator`**

Behavior is exact:

1. Query existing `(turn_id, revision=1)` and return it.
2. Assemble bounded context.
3. Call the engine.
4. Validate `decision.request_id == turn.id` and no proposed artifact has `accepted` state or execution authorization.
5. Persist `CognitiveAssessment` and `cognitive.assessment.completed` in the caller transaction.
6. Catch unknown engine exceptions, append `cognitive.assessment.failed` with only engine name and stable error code, return `None`, and do not commit or roll back the caller transaction.

Do not store exception text, raw Provider output or hidden reasoning.

- [x] **Run cognitive context/service tests and verify GREEN**

- [x] **Commit Task 4**

```powershell
git add backend/app/cognitive backend/tests/cognitive
git commit -m "feat: orchestrate shadow cognitive assessments"
```

## Task 5: Conversation Shadow Integration Without Behavior Changes

**Files:**

- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Create: `backend/app/cognitive/dependencies.py`
- Modify: `backend/app/conversation/dependencies.py`
- Modify: `backend/app/conversation/service.py`
- Modify: `backend/tests/conversation/test_service.py`
- Modify: `backend/tests/api/test_conversations.py`

- [x] **Write failing integration tests**

Add tests proving:

- completed text and transcript Turns each create one assessment;
- ambiguous project Turns create an assessment with `needs_clarification=true` before returning the existing clarification response;
- LLM retry reuses revision 1 and does not reassess;
- cognitive engine failure leaves the same Assistant response and Turn status;
- no `InspirationCandidate`, `ExecutionTask`, Agent call or changed response metadata is produced in shadow mode.

```python
result = await service_with(
    db_session,
    llm_provider=FakeProvider(),
    cognitive_engine=FakeCognitiveEngine(mode="inspiration"),
).create_turn(
    session_id=session.id,
    client_message_id=uuid.uuid4(),
    user_text="我有个新想法",
    explicit_project_id=None,
)
assert result.turn.status == "completed"
assert result.assistant_message.content == "Assistant reply"
assert await assessment_count(result.turn.id) == 1
assert await event_exists(result.turn.id, "cognitive.assessment.completed")
```

- [x] **Add settings and dependencies**

Add:

```python
cognitive_shadow_enabled: bool = True
cognitive_recent_message_char_budget: int = Field(default=8000, gt=0)
cognitive_semantic_threshold: float = Field(default=0.8, ge=0, le=1)
```

`build_cognitive_engine()` returns `HybridCognitiveEngine` with `DeterministicCognitiveEngine` and `semantic=None`. Keep a dependency override point named `get_cognitive_engine` for tests and future Providers.

- [x] **Integrate after project resolution**

Inject optional `CognitiveOrchestrator` into `ConversationService`. Immediately after writing `turn.context_snapshot`, call `assess_turn` before the `NEEDS_CLARIFICATION` branch. The returned assessment is intentionally ignored by response generation in shadow mode.

When `cognitive_shadow_enabled` is false, dependencies pass `None` and current behavior is byte-for-byte unchanged outside timestamps/audit ordering.

- [x] **Run conversation and API regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\conversation backend\tests\api\test_conversations.py -q
```

Expected: all old tests plus new shadow tests pass.

- [x] **Commit Task 5**

```powershell
git add backend/app/config.py backend/.env.example backend/app/cognitive backend/app/conversation backend/tests/conversation backend/tests/api/test_conversations.py
git commit -m "feat: assess conversation turns in shadow mode"
```

## Task 6: Read-Only Cognitive Assessment API

**Files:**

- Create: `backend/app/schemas/cognitive.py`
- Create: `backend/app/api/cognitive.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/api/test_cognitive.py`

- [x] **Write failing API tests**

Test latest assessment retrieval, revision ordering, cross-conversation hiding and missing Turn behavior:

```python
response = await db_client.get(
    f"/api/v1/conversations/{conversation_id}/turns/{turn_id}/cognitive-assessments"
)
assert response.status_code == 200
assert response.json()["latest"]["primary_mode"] == "inspiration"
assert response.json()["assessments"][0]["revision"] == 1
```

The same Turn queried through another conversation ID returns `404 RESOURCE_NOT_FOUND`.

- [x] **Implement response schemas and endpoint**

Expose only validated assessment fields. Do not expose Provider raw responses or internal exception details. Endpoint:

```text
GET /api/v1/conversations/{conversation_id}/turns/{turn_id}/cognitive-assessments
```

Return revisions ordered ascending and `latest` as the highest revision. Validate the Turn belongs to the conversation before querying assessments.

- [x] **Run API tests and verify GREEN**

- [x] **Commit Task 6**

```powershell
git add backend/app/api backend/app/schemas backend/tests/api/test_cognitive.py
git commit -m "feat: expose cognitive assessment history"
```

## Task 7: Verification, Architecture And Project Memory

**Files:**

- Modify: `docs/architecture/exec-architecture.html`
- Modify: `docs/PROJECT_MEMORY.md`
- Modify: `docs/plans/2026-07-15-aios-cognitive-shadow-plan.md`
- Create: `docs/plans/2026-07-15-aios-inspiration-pool-plan.md`
- Create: `docs/plans/2026-07-15-aios-idea-evolution-plan.md`

- [x] **Run complete backend verification**

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Record the exact pass count.

- [x] **Run protected migration verification**

Against `aios_test`, run `0004 -> 0003 -> 0004`, then `alembic check`. Upgrade the development database from `0003` to `0004` only after all tests and checks pass.

- [x] **Update the execution architecture**

Insert a real/stub-aware cognitive layer between persisted Turn and task draft:

```text
Conversation Turn
-> ContextResolver
-> Cognitive Engine (shadow: real)
-> CognitiveAssessment
-> Candidate Policy (future)
-> ExecutionTaskDraft (future)
```

Show Inspiration Pool and Idea Evolution Engine as designed/future modules. Keep Voice as an input adapter into the same Turn.

- [x] **Update project memory**

Record contracts, migration head, shadow behavior, exact tests, disabled/enabled configuration, no real semantic Provider, no candidate side effects, commit IDs and the next Inspiration Pool plan. Keep implementation details in this plan and the design spec.

- [x] **Run final diff checks and commit**

```powershell
git diff --check
git status --short
git add docs/architecture/exec-architecture.html docs/PROJECT_MEMORY.md docs/plans/2026-07-15-aios-cognitive-shadow-plan.md
git commit -m "docs: record cognitive shadow milestone"
```

## Follow-Up Plans

After this plan is complete and reviewed:

1. [`Inspiration Pool`](2026-07-15-aios-inspiration-pool-plan.md): pending candidate confirmation, accepted Inspiration lifecycle and mobile UI.
2. [`Idea Evolution Engine`](2026-07-15-aios-idea-evolution-plan.md): PostgreSQL candidate retrieval, relation/merge proposals, deduplication and scheduled scans.
3. `Execution Safety`: consume only confirmed task drafts, isolate Agent runs and preserve two confirmation gates.

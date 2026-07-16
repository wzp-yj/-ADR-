# AIOS ExecutionTaskDraft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a persisted, editable ExecutionTaskDraft and first-confirmation flow that creates a confirmed ExecutionTask without invoking any Agent.

**Architecture:** A validated projector consumes only persisted CognitiveAssessment task artifacts and creates idempotent pending drafts. Users edit scope under optimistic version control; an atomic decision transaction freezes an accepted draft into a confirmed task. Mobile reviews the same resource, while Agent dispatch, isolation and Change review remain absent.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy async, Pydantic v2, Alembic, Expo 52, React Native, TypeScript, Jest.

**Design:** `docs/specs/2026-07-15-aios-execution-task-draft-design.md`

---

## File Map

Backend domain:

- `backend/app/execution/base.py`: strict enums, source-adapter and policy protocols, projection contract, path and scope validation.
- `backend/app/execution/policy.py`: deterministic structure/risk/capability policy.
- `backend/app/execution/projector.py`: persisted CognitiveAssessment to pending Draft.
- `backend/app/execution/service.py`: edit, decision and read transactions.
- `backend/app/models/execution.py`: Draft and confirmed Task ORM models.
- `backend/app/schemas/execution.py`: REST request/response contracts.
- `backend/app/api/execution.py`: list/detail/edit/decision endpoints.
- `backend/alembic/versions/0007_create_execution_tasks.py`: two-table migration.

Mobile:

- `mobile/src/components/ExecutionTaskDraftBar.tsx`: compact conversation candidate.
- `mobile/src/components/ExecutionTaskReview.tsx`: full-screen scope editor and decision view.
- `mobile/src/execution/form.ts`: pure newline-list form conversion and validation.
- Existing `mobile/src/api/types.ts`, `mobile/src/api/client.ts` and `mobile/App.tsx`: typed transport and active-conversation integration.

---

## Task 1: Strict Execution Contracts And Policy

**Files:**

- Create: `backend/app/execution/__init__.py`
- Create: `backend/app/execution/base.py`
- Create: `backend/app/execution/policy.py`
- Create: `backend/tests/execution/__init__.py`
- Create: `backend/tests/execution/test_base.py`
- Create: `backend/tests/execution/test_policy.py`

- [x] **Write failing contract tests**

Cover:

```python
def test_project_development_projection_requires_valid_scope():
    projection = TaskDraftProjection(
        assessment_id=uuid.uuid4(),
        artifact_index=0,
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        source_message_id=uuid.uuid4(),
        project_id=None,
        title="更新语音交互",
        objective="修复按住说话并补充测试",
        confidence=0.9,
    )
    assert projection.domain is ExecutionDomain.PROJECT_DEVELOPMENT
    assert projection.project_id is None


@pytest.mark.parametrize("path", ["C:/repo", "/etc/passwd", "../secret", "src/../x", " "])
def test_allowed_path_rejects_non_relative_or_traversal(path: str):
    with pytest.raises(ValueError):
        normalize_allowed_paths([path])


def test_allowed_paths_are_normalized_and_deduplicated():
    assert normalize_allowed_paths(["src\\app", "src/app", "README.md"]) == [
        "src/app",
        "README.md",
    ]
```

Also test strict enum values:

```text
DraftStatus: pending | accepted | rejected | superseded
TaskStatus: confirmed | queued | running_in_isolation | awaiting_change_review |
            change_approved | change_rejected | applying | applied | failed |
            rolled_back | cancelled
RiskLevel: low | medium | high
ExecutionDomain: project_development
```

- [x] **Run RED**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\execution\test_base.py backend\tests\execution\test_policy.py -q
```

Expected: collection fails because `app.execution` does not exist.

- [x] **Implement strict contracts**

`TaskDraftProjection` must use `ConfigDict(extra="forbid")`, nonblank constrained strings and `confidence` in `[0, 1]`. Define immutable system policy constants:

```python
SYSTEM_GUARDRAILS = (
    "isolation_required",
    "no_direct_real_project_write",
    "no_automatic_commit",
    "no_automatic_push",
    "no_automatic_deploy",
)
POLICY_VERSION = "execution-safety-v1"
```

`normalize_allowed_paths()` converts backslashes to `/`, rejects absolute paths, drive prefixes, empty segments and `.` / `..`, preserves stable input order and removes duplicates.

Define replacement boundaries in the domain contract rather than importing a concrete Cognitive or database implementation:

```python
class TaskDraftPolicy(Protocol):
    def structure(self, projection: TaskDraftProjection) -> StructuredTaskScope:
        ...


class TaskDraftSourceAdapter(Protocol[SourceT]):
    async def project(self, source: SourceT) -> list[ExecutionTaskDraft]:
        ...
```

Use `TYPE_CHECKING` for the ORM return type so `base.py` does not depend on model initialization. `AssessmentTaskDraftProjector` is the first adapter implementation; future IdeaDirection, Inspiration or external-system adapters must satisfy the same pending-Draft-only boundary.

- [x] **Implement DeterministicTaskDraftPolicy**

Return:

```python
StructuredTaskScope(
    acceptance_criteria=[
        "生成可审核的 Diff，并说明每项变更。",
        "运行与改动相关的测试并报告结果。",
    ],
    user_constraints=[],
    allowed_paths=[],
    suggested_capabilities=["code_gen", "refactor", "code_review"],
    risk_level=RiskLevel.HIGH if high_risk_signal else RiskLevel.MEDIUM,
    policy_snapshot={
        "version": POLICY_VERSION,
        "guardrails": list(SYSTEM_GUARDRAILS),
    },
)
```

High-risk signals include delete, migration, commit, push, deploy, production, database write and their Chinese equivalents. Policy output remains a proposal and never selects or calls an Agent.

- [x] **Run GREEN and commit**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\execution\test_base.py backend\tests\execution\test_policy.py -q
git add backend/app/execution backend/tests/execution
git commit -m "feat: define execution draft contracts"
```

---

## Task 2: Persistence And Migration 0007

**Files:**

- Create: `backend/app/models/execution.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0007_create_execution_tasks.py`
- Create: `backend/tests/models/test_execution_models.py`

- [x] **Write failing model tests**

Assert table names, foreign keys and database constraints for:

```text
execution_task_drafts
  unique (assessment_id, artifact_index)
  JSON arrays: acceptance_criteria, user_constraints, allowed_paths,
               suggested_capabilities
  policy_snapshot JSON object
  pending decision fields are null
  terminal decision requires decided_at
  version > 0 and confidence in [0, 1]

execution_tasks
  unique origin_draft_id
  project_id not null
  status constrained to TaskStatus
  version > 0
  confirmed_at not null
```

Use PostgreSQL tests to prove blank objective, invalid JSON shape, invalid status and duplicate source are rejected.

- [x] **Run RED**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\models\test_execution_models.py -q
```

Expected: model import fails.

- [x] **Implement ORM models and migration**

Draft `project_id` is nullable; Task `project_id` is not. Use `ON DELETE RESTRICT` for project, session, Turn, Message, Assessment and origin Draft. Use PostgreSQL JSONB defaults (`'[]'::jsonb`, `'{}'::jsonb`) and explicit check constraints rather than Python-only validation.

Migration chain:

```python
revision = "0007_create_execution_tasks"
down_revision = "0006_create_idea_evolution"
```

- [x] **Verify model and migration lifecycle**

On the protected test database only:

```powershell
$env:DATABASE_URL='postgresql+asyncpg://aios_test:aios_test@localhost:5433/aios_test'
F:\AIOS\.venv\Scripts\python.exe -m alembic upgrade head
F:\AIOS\.venv\Scripts\python.exe -m alembic downgrade 0006_create_idea_evolution
F:\AIOS\.venv\Scripts\python.exe -m alembic upgrade head
F:\AIOS\.venv\Scripts\python.exe -m alembic check
```

Expected head: `0007_create_execution_tasks`; check: `No new upgrade operations detected`.

- [x] **Commit**

```powershell
git add backend/app/models backend/alembic/versions/0007_create_execution_tasks.py backend/tests/models/test_execution_models.py
git commit -m "feat: persist execution task drafts"
```

---

## Task 3: Idempotent Assessment Projector

**Files:**

- Create: `backend/app/execution/projector.py`
- Create: `backend/tests/execution/test_projector.py`

- [x] **Write failing projector tests**

Test these cases with real PostgreSQL sessions:

1. Latest `task_draft` artifact creates one pending Draft with source IDs and policy scope.
2. Replaying the same Assessment returns the same Draft.
3. Multiple task artifacts preserve `artifact_index` order.
4. Memory, inspiration and decision artifacts are ignored.
5. `needs_clarification=true`, invalid project snapshot or stale Assessment creates no Draft.
6. `project_id=None` creates a pending but incomplete Draft.
7. A resolved project ID must exist and match the Assessment snapshot.
8. Invalid persisted artifacts produce only a redacted `execution.draft.projection_failed` event.
9. No Agent registry or `BaseAgent.execute()` path is imported or invoked.

- [x] **Run RED**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\execution\test_projector.py -q
```

- [x] **Implement AssessmentTaskDraftProjector**

Follow the existing `AssessmentInspirationProjector` transaction ownership pattern:

```python
class AssessmentTaskDraftProjector:
    def __init__(self, db: AsyncSession, *, policy: TaskDraftPolicy | None = None):
        self._db = db
        self._policy = policy or DeterministicTaskDraftPolicy()

    async def project(
        self, assessment: CognitiveAssessment
    ) -> list[ExecutionTaskDraft]:
        ...
```

Lock the persisted Assessment, query the latest revision for its Turn, validate `ProjectResolution` and `list[ProposedArtifact]`, fetch the user Message, construct all projections before writing any row, then reuse existing rows by artifact index.

Do not commit in the projector. ConversationService owns commit/rollback.

- [x] **Run GREEN and commit**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\execution\test_projector.py -q
git add backend/app/execution/projector.py backend/tests/execution/test_projector.py
git commit -m "feat: project execution task drafts"
```

---

## Task 4: Conversation Integration Without Execution

**Files:**

- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/app/conversation/dependencies.py`
- Modify: `backend/app/conversation/service.py`
- Modify: `backend/tests/conversation/test_service.py`
- Modify: `backend/tests/api/test_conversations.py`

- [x] **Write failing integration tests**

Prove:

- text Turn classified as task/execution creates a pending Draft after CognitiveAssessment persistence;
- transcript Turn uses the same projection path;
- Provider unavailable still leaves the pending Draft queryable;
- project clarification creates no Draft;
- retry does not duplicate a Draft;
- projector failure writes a redacted audit event and does not change Assistant reply or Turn status;
- `BaseAgent.execute` call count remains zero.

- [x] **Run RED**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\conversation\test_service.py backend\tests\api\test_conversations.py -q
```

- [x] **Wire the projector**

Add:

```text
EXECUTION_TASK_DRAFTS_ENABLED=true
```

`ConversationService` receives `task_draft_projector: TaskDraftProjector | None`. Invoke it after CognitiveAssessment and Inspiration projection, before the LLM call. Catch exceptions as `execution.draft.projection_failed` with only a stable error code.

Do not add any Agent dependency to ConversationService.

- [x] **Run full conversation/cognitive suites and commit**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\conversation backend\tests\cognitive backend\tests\api\test_conversations.py -q
git add backend/app/config.py backend/.env.example backend/app/conversation backend/tests/conversation backend/tests/api/test_conversations.py
git commit -m "feat: integrate execution draft projection"
```

---

## Task 5: Edit, Decision And Read APIs

**Files:**

- Create: `backend/app/execution/service.py`
- Create: `backend/app/schemas/execution.py`
- Create: `backend/app/api/execution.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/execution/test_service.py`
- Create: `backend/tests/api/test_execution.py`

- [x] **Write failing service tests**

Cover:

```python
updated = await service.update_draft(
    draft.id,
    expected_version=1,
    project_id=project.id,
    title="限制语音修改范围",
    objective="只修改 mobile/src/voice",
    acceptance_criteria=["49 个移动测试继续通过"],
    user_constraints=["保持 Provider 可替换"],
    allowed_paths=["mobile/src/voice", "mobile/App.tsx"],
)
assert updated.version == 2
```

Also assert:

- stale `expected_version` returns `EXECUTION_DRAFT_VERSION_CONFLICT`;
- accepted/rejected Draft cannot be edited;
- invalid/archived project is rejected;
- invalid paths return `EXECUTION_DRAFT_PATH_INVALID`;
- accept without project returns `EXECUTION_PROJECT_REQUIRED`;
- accept without objective or acceptance criteria returns `EXECUTION_DRAFT_INCOMPLETE`;
- accept atomically creates one confirmed Task snapshot;
- duplicate accept with the frozen Draft version is idempotent and returns the same Task;
- duplicate accept with a stale `expected_version` returns `EXECUTION_DRAFT_VERSION_CONFLICT` rather than hiding an intervening edit;
- reject creates no Task; conflicting decision returns 409;
- stale source blocks accept but still permits reject;
- service imports and Agent call count are zero.

- [x] **Write failing API tests**

Endpoints must enforce session/project ownership and hide cross-scope resources as 404. Validate exact response types for list, detail, PATCH, decision and confirmed Task list/detail.

Decision body:

```json
{
  "decision": "accepted",
  "expected_version": 2,
  "reason": null
}
```

PATCH body:

```json
{
  "expected_version": 1,
  "project_id": "uuid",
  "title": "限制语音修改范围",
  "objective": "只修改移动端语音适配器",
  "acceptance_criteria": ["移动端测试通过"],
  "user_constraints": ["保留阿里和本地 Provider 接口"],
  "allowed_paths": ["mobile/src/voice", "mobile/App.tsx"]
}
```

- [x] **Run RED**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\execution\test_service.py backend\tests\api\test_execution.py -q
```

- [x] **Implement service and schemas**

Use `SELECT ... FOR UPDATE` and one caller-owned transaction. Response detail includes source user message excerpt, project metadata, editable scope, risk, suggested capabilities and immutable policy guardrails. Never return hidden model reasoning or Provider raw output.

- [x] **Implement routes and commit**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests\execution backend\tests\api\test_execution.py backend\tests\models\test_execution_models.py -q
git add backend/app/execution backend/app/schemas/execution.py backend/app/api backend/tests/execution backend/tests/api/test_execution.py
git commit -m "feat: confirm execution task scope"
```

---

## Task 6: Mobile Transport And Pure Form State

**Files:**

- Modify: `mobile/src/api/types.ts`
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/api/client.test.ts`
- Create: `mobile/src/execution/form.ts`
- Create: `mobile/src/execution/form.test.ts`

- [x] **Write failing API client tests**

Cover pending list by `session_id`, detail, versioned PATCH, accepted/rejected decision, confirmed Task list and detail. Assert URLs and exact JSON bodies.

- [x] **Write failing pure form tests**

```typescript
expect(parseLines("src/voice\nmobile/App.tsx\nsrc/voice")).toEqual([
  "src/voice",
  "mobile/App.tsx",
]);
expect(validateDraftForm({ projectId: null, objective: "x", criteria: ["y"] }))
  .toEqual(["project_id"]);
```

Test trimming, blank line removal, stable deduplication and missing project/objective/criteria.

- [x] **Run RED**

```powershell
cd mobile
npm test -- --runInBand src/api/client.test.ts src/execution/form.test.ts
```

- [x] **Implement typed transport and form helpers**

Do not add execution fields to `MessageMetadata`; Draft/Task remain separate API resources. Preserve existing voice multipart and binary TTS behavior.

- [x] **Run GREEN and commit**

```powershell
npm test -- --runInBand src/api/client.test.ts src/execution/form.test.ts
npx tsc --noEmit
git add mobile/src/api mobile/src/execution
git commit -m "feat: add execution confirmation transport"
```

---

## Task 7: Mobile First-Confirmation Experience

**Files:**

- Create: `mobile/src/components/ExecutionTaskDraftBar.tsx`
- Create: `mobile/src/components/ExecutionTaskReview.tsx`
- Modify: `mobile/src/components/components.test.tsx`
- Modify: `mobile/App.tsx`
- Modify: `mobile/src/theme.ts` only if an existing semantic color cannot represent risk

- [x] **Write failing component tests**

Assert:

- compact candidate shows title, project/missing-project state and risk;
- opening review shows source, objective, criteria, constraints, paths, capabilities and guardrails;
- project uses a selectable project list, not free-form UUID input;
- edit saves with `expected_version`;
- accepted/rejected buttons are disabled while requests run;
- incomplete scope disables accept but still permits reject;
- long objective/path wraps without hiding actions;
- accepted response removes the Draft and exposes confirmed status without implying Agent execution.

- [x] **Run RED**

```powershell
cd mobile
npm test -- --runInBand src/components/components.test.tsx
```

- [x] **Implement components**

Use a full-screen unframed review workspace, not nested cards. Use multiline TextInputs for objective and newline-separated lists, a segmented/project selection control, icons for save/close, and explicit text buttons only for accept/reject commands. Keep card radius at or below 8px and stable action dimensions.

Visible acceptance impact must be factual and concise:

```text
确认后：创建任务，等待隔离调度
当前不会启动 Agent
```

- [x] **Integrate App state**

Load Drafts alongside Memory and Inspiration candidates. Every async result must pass `isCurrentConversation(draft.session_id, activeConversationIdRef.current)` before replacing UI state. On switch, close stale review detail. Refresh after update/version conflict and after accept/reject.

- [x] **Run mobile verification and commit**

```powershell
npm test -- --runInBand
npx tsc --noEmit
npx expo install --check
git add mobile/App.tsx mobile/src/components mobile/src/theme.ts
git commit -m "feat: review execution task scope on mobile"
```

---

## Task 8: Runtime Verification, Architecture And Memory

**Files:**

- Modify: `docs/architecture/exec-architecture.html`
- Modify: `docs/PROJECT_MEMORY.md`
- Modify: `docs/development-environment.md` only if migration/run commands changed
- Modify: `docs/plans/2026-07-15-aios-execution-task-draft-plan.md`

- [ ] **Run complete backend verification**

```powershell
F:\AIOS\.venv\Scripts\python.exe -m pytest backend\tests -q
$env:DATABASE_URL='postgresql+asyncpg://aios_test:aios_test@localhost:5433/aios_test'
F:\AIOS\.venv\Scripts\python.exe -m alembic current
F:\AIOS\.venv\Scripts\python.exe -m alembic check
```

- [ ] **Run complete Web and Mobile verification**

```powershell
cd frontend
npm test -- --run
npm run build

cd ..\mobile
npm test -- --runInBand
npx tsc --noEmit
npx expo install --check
npx expo config --type public
npx expo-doctor
npx expo export --platform web --output-dir dist
```

- [ ] **Run real PostgreSQL first-confirmation closure**

Using a uniquely named verification project:

1. Persist a task/execution Turn and Draft.
2. Edit project, objective, criteria and allowed paths.
3. Reject one Draft and prove zero Tasks.
4. Accept another and prove exactly one confirmed Task.
5. Replay acceptance and prove the same Task ID.
6. Prove Agent registry execute count is zero.
7. Delete only verification rows by exact project/session IDs.

- [ ] **Run visual checks**

At `390x844` and desktop width verify pending list, missing project, edit form, high risk, version conflict, accepted receipt and rejected removal. Check `document.body.scrollWidth === viewport width` and inspect screenshots for overlap.

- [ ] **Update architecture and memory**

Mark Layer 4 Draft projection, scope review and confirmed Task as Real. Keep Dispatcher, Worktree/container, Agent execution, Change persistence, second confirmation and real-project apply as Future. Record migration head, exact test counts, runtime URLs, unconfigured Provider state and next milestone.

- [ ] **Commit and merge**

```powershell
git add docs backend mobile
git commit -m "feat: complete first execution confirmation"
```

Verify the merged result on `main` before removing the worktree.

---

## Completion Invariants

- Every task/execution artifact creates at most one pending Draft.
- A pending Draft may exist without project; it cannot be accepted without one.
- Editing requires the current version and accepted/rejected Drafts are immutable.
- Accept creates exactly one confirmed Task snapshot; reject creates none.
- Conversation replies and existing Memory/Inspiration/Evolution behavior remain unchanged.
- No Agent, queue, Worktree, Change, Git, test runner, deploy or real project write is invoked by this milestone.
- Project memory and the real execution architecture distinguish implemented Gate 1 from future execution and Gate 2.

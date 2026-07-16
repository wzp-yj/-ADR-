# AIOS ExecutionTaskDraft 与第一次确认设计

> 日期：2026-07-15  
> 状态：已确认，采用“独立 Draft + confirmed Task”方案  
> 范围：任务草案、范围编辑、第一次确认；不运行 Agent

## 1. 目标

把 AIOS 当前的链路从“理解到执行意图”为止，推进到可审计的第一次确认：

```text
文字 / 语音 Turn
-> ContextResolver
-> CognitiveAssessment
-> task_draft artifact
-> ExecutionTaskDraft（pending）
-> 用户补全并确认范围
-> ExecutionTask（confirmed）
```

`confirmed` 只表示用户确认了任务目标和允许范围，不表示已经执行。当前里程碑不创建队列、不调用 Agent、不创建 Change，也不修改真实项目。

## 2. 推荐方案与原因

采用两个独立实体：

1. `ExecutionTaskDraft` 保存 AI 提议和用户尚未确认的可编辑范围。
2. `ExecutionTask` 保存用户第一次确认时形成的不可变任务快照。

不采用单表从 draft 直接流转到 running。原因是 AI 的建议不是用户授权，两个实体可以在数据库、API 和审计上明确区分“系统提出了什么”和“用户确认了什么”。

不采用仅在 Assistant Message 上放确认按钮。消息元数据不能可靠承担幂等决定、范围版本、跨端恢复和未来 Worker lease。

## 3. 安全边界

- 只有 `ExecutionTask` 可以成为未来 Dispatcher 的输入。
- Agent、Git、测试或外部系统不能消费原始 Turn、`CognitiveDecision` 或 pending Draft。
- 接受 Draft 只创建 `confirmed` Task；没有任何后台 Worker 监听该状态。
- 系统守卫不可由用户编辑或删除：只允许隔离工作区、禁止直接写真实项目、禁止自动 commit/push/deploy。
- 未来 Agent 在隔离环境生成 Change 后，仍必须进入第二次 Diff/Test 审核。
- 本阶段不把 Task、Message、Memory、Inspiration 或 Change 合并到通用表。

## 4. 来源与投影

第一版实现 `AssessmentTaskDraftProjector`，只读取已持久化的 `CognitiveAssessment`：

- artifact 必须是 `ArtifactKind.TASK_DRAFT`。
- Assessment 必须是该 Turn 的最新 revision，且未被更新 revision 取代。
- `primary_mode` 必须是 `task_intent | execution_intent`。
- `recommended_action` 必须是 `propose_task_draft | request_execution_confirmation`。
- `needs_clarification=true` 时不投影。
- 每个 `(assessment_id, artifact_index)` 最多创建一个 Draft。
- 必须重新验证 source Turn、user Message 和项目快照，不能直接信任内存对象。

当前来源适配器只有 Cognitive Assessment。接口保留 `TaskDraftSourceAdapter`，以后可增加：

- `IdeaDirection -> Draft`
- 用户在灵感池中选择“转为任务”
- 日程、企业系统或人工表单

这些适配器只能创建 pending Draft，不能创建 confirmed Task。

## 5. 草案结构

`ExecutionTaskDraft`：

```text
id
assessment_id + artifact_index
session_id / turn_id / source_message_id
project_id nullable
domain = project_development
title
objective
acceptance_criteria[]
user_constraints[]
allowed_paths[]
suggested_capabilities[]
risk_level = low | medium | high
confidence
policy_snapshot
status = pending | accepted | rejected | superseded
version
decision_reason
created_at / updated_at / decided_at
```

语义：

- `project_id` 在 pending 阶段允许为空，用户可在确认界面补选；`project_development` 接受时必须有未归档项目。
- `allowed_paths=[]` 表示允许 Agent 在该项目的整个隔离副本内分析和生成 Change，不表示允许写真实项目。
- `user_constraints` 是用户业务约束；不可编辑的系统限制保存在 `policy_snapshot`。
- `suggested_capabilities` 只是未来路由提示，不构成 Agent 选择或授权。
- pending Draft 可编辑，每次成功更新 `version += 1`；接受后内容冻结。

确定性默认结构：

- `objective = artifact.content`
- `acceptance_criteria`：生成可审核 Diff；运行相关测试并报告结果
- `user_constraints = []`
- `allowed_paths = []`
- `risk_level = medium`，出现删除、迁移、commit、push、deploy 或外部写入信号时为 high
- `policy_snapshot` 保存策略版本和不可移除守卫 ID

## 6. 已确认任务结构

接受 Draft 时原子创建 `ExecutionTask`，复制确认时的范围快照：

```text
id
origin_draft_id unique
project_id
domain
title / objective
acceptance_criteria[]
user_constraints[]
allowed_paths[]
requested_capabilities[]
risk_level
policy_snapshot
status = confirmed
version = 1
confirmed_at / created_at / updated_at
```

未来状态预留为：

```text
confirmed
-> queued
-> running_in_isolation
-> awaiting_change_review
-> change_approved | change_rejected
-> applying
-> applied | failed | rolled_back | cancelled
```

本阶段没有公开状态转换 API，除 `confirmed` 外的状态不会产生。

## 7. 编辑与决定事务

API：

```text
GET   /api/v1/execution-task-drafts?session_id=&status=pending
GET   /api/v1/execution-task-drafts/{draft_id}
PATCH /api/v1/execution-task-drafts/{draft_id}
POST  /api/v1/execution-task-drafts/{draft_id}/decision
GET   /api/v1/execution-tasks?project_id=&status=confirmed
GET   /api/v1/execution-tasks/{task_id}
```

PATCH 必须携带 `expected_version`，只允许修改：

- `project_id`
- `title`
- `objective`
- `acceptance_criteria`
- `user_constraints`
- `allowed_paths`

路径必须是项目内相对路径，不允许绝对路径、盘符、`..` 或空路径。

决定请求携带 `accepted | rejected`、`expected_version` 和可选原因。服务锁定 Draft 后重新验证：

- Draft 仍为 pending 且版本匹配。
- 来源 Assessment 仍有效。
- 接受时 project 必填且未归档。
- objective 非空且至少有一条验收标准。
- 所有 allowed path 通过安全校验。

接受事务同时完成：

1. Draft 状态改为 accepted。
2. 创建唯一 ExecutionTask 快照。
3. 写入 `execution.task.confirmed` 用户审计事件。

重复同一决定幂等返回原结果；不同决定返回 409。拒绝不创建 Task。任何决定路径都不调用 Agent。

## 8. 移动端审核

Conversation 候选区域增加“待确认任务”，与 Memory 和 Inspiration 分开显示。打开全屏任务确认视图后展示：

- 来源项目和来源对话
- 目标
- 验收标准
- 用户约束
- 允许路径
- 风险等级和建议能力
- 系统守卫
- 接受影响：创建 confirmed Task，不启动 Agent

项目、目标、验收标准、约束和允许路径可编辑。保存使用版本号防止旧页面覆盖新范围。接受或拒绝期间禁用重复操作，成功后从 pending 列表移除。App 刷新和切换会话必须按 active conversation 校验，避免旧候选串入新会话。

## 9. 错误、恢复与审计

稳定错误码：

```text
EXECUTION_DRAFT_VERSION_CONFLICT
EXECUTION_DRAFT_DECISION_CONFLICT
EXECUTION_DRAFT_INCOMPLETE
EXECUTION_DRAFT_SOURCE_STALE
EXECUTION_DRAFT_PATH_INVALID
EXECUTION_PROJECT_REQUIRED
```

审计事件：

```text
execution.draft.projected
execution.draft.projection_skipped
execution.draft.projection_failed
execution.draft.updated
execution.draft.accepted
execution.draft.rejected
execution.task.confirmed
```

审计只保存 ID、版本、状态、风险和守卫 ID，不保存隐藏推理、完整 Prompt 或 Agent 原始输出。

## 10. 持久化与迁移

迁移 `0007_create_execution_tasks` 新增：

- `execution_task_drafts`
- `execution_tasks`

PostgreSQL 约束覆盖枚举值、版本、置信度、必填文本、JSON 数组、决定状态和唯一来源。`origin_draft_id` 唯一保证接受重试只创建一个 Task。

项目、Conversation、Turn、Message 和 CognitiveAssessment 使用 `ON DELETE RESTRICT`，避免任务证据被静默删除。

## 11. 测试门槛

后端：

- 严格 Draft/Task 契约和路径校验。
- 迁移 upgrade/downgrade/upgrade 与 `alembic check`。
- 投影来源重验证、项目空值、最新 revision、幂等和失败降级。
- pending 编辑、乐观版本冲突、接受/拒绝幂等和冲突。
- 接受原子创建唯一 confirmed Task；所有路径 Agent 调用次数为零。
- Conversation 文字与 transcript Turn 均可产生相同 Draft。

移动端：

- 候选刷新按 active conversation 隔离。
- 范围编辑、版本冲突刷新、接受/拒绝和错误恢复。
- `390x844` 与桌面视口无溢出，长路径和长目标不遮挡操作。

## 12. 后续替换点

- `TaskDraftPolicy`：确定性默认实现以后可组合 LLM 结构化规划器，但输出必须重新验证。
- `TaskDraftSourceAdapter`：增加 IdeaDirection、灵感和企业系统来源。
- `ExecutionDispatcher`：只读取 confirmed Task，可从 PostgreSQL Worker 换成 Redis、Temporal 或其他调度器。
- `AgentSelector`：根据 requested capabilities 和运行策略选择 Codex、Claude、Git 或 Test Agent。
- `IsolationProvider`：Worktree、本地容器或远程沙箱不改变 Task/Draft 合同。

无论替换哪一层，都不能移除第一次任务确认和第二次 Change 审核。

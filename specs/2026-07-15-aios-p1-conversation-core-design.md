# AIOS P1：可审计对话核心设计

> 版本：v1.0  
> 日期：2026-07-15  
> 状态：P1-A 后端与 P1-B 移动端文字对话已实现

## 1. 目标

P1 建立 AIOS 的业务主干：用户通过文字或未来的语音持续对话，系统保存消息、判断当前项目上下文、在有歧义时主动澄清，并把可能的长期记忆保存为待确认候选。

P1 必须保证：

- 用户输入先持久化，再调用外部模型。
- 项目归属和长期记忆不能由 LLM 静默修改。
- 每次 Turn 的状态、上下文判断、Provider 调用结果和错误均可审计。
- 客户端重试不会重复创建用户消息或重复调用 LLM。
- 没有任何 LLM API key 时服务仍可启动，输入仍可保存并明确报告 Provider 不可用。
- 语音只是标准 Turn 的输入输出适配器，不形成第二套对话模型。
- 业务层不依赖 OpenAI、阿里云、Anthropic 或 vLLM 的 SDK 类型。

## 2. P1 边界

### 2.1 本阶段实现

- 会话、消息、Turn、项目上下文快照、项目上下文条目、记忆候选和审计事件持久化。
- 会话列表、消息分页、提交 Turn、失败重试和记忆候选确认 API。
- 可替换的 `ContextResolver`、`MemoryExtractor`、`LLMRouter` 和 `BaseLLMProvider` 契约。
- 首个非流式文字对话编排链路。
- 移动端文字会话界面与失败重试。
- 标准错误响应、存活检查和就绪检查。

### 2.2 只预留接口，不在本阶段实现

- 实时 STT/TTS、SSE/WebSocket 流式返回。
- pgvector、Embedding、语义召回和自动摘要。
- 真实 Codex、Claude Code、Git、Test Agent 执行。
- Agent 隔离工作区、任务确认、Diff 审核和应用。
- Redis、Celery、Temporal、LangGraph 等独立任务基础设施。
- PDF、Word、Excel 内容提取。
- 多用户账户、登录和跨设备身份同步。

这些能力后续通过输入适配器、Provider、Agent 插件和执行工作流增加，不改变 Conversation、Turn、Message 的核心语义。

P1 明确按本地单用户开发环境实现。服务暴露到局域网或公网、连接真实手机前，必须增加身份认证、用户数据边界、受限 CORS 和密钥管理；不能把当前开发环境的 `allow_origins=["*"]` 作为生产配置。

## 3. 总体架构

```text
Mobile / Web
    |
    | REST（P1） / SSE、WebSocket（后续）
    v
Conversation API
    |
    v
ConversationService
    |-- ConversationRepository
    |-- MessageRepository
    |-- TurnRepository
    |-- ContextResolver
    |-- ContextAssembler
    |-- LLMRouter --> BaseLLMProvider --> OpenAI-compatible / Aliyun / Anthropic
    |-- MemoryExtractor
    |-- MemoryCandidateRepository
    `-- AuditEventRepository

PostgreSQL
    |-- 结构化会话与项目数据（P1）
    `-- pgvector 向量列与索引（后续迁移）
```

对话主干与执行主干必须分离：

```text
对话 Turn --> 普通回复
          `-> ExecutionTaskDraft（后续）
                 -> 用户确认任务
                 -> Agent 在隔离工作区运行
                 -> Diff + 测试报告
                 -> 用户审核
                 -> 应用到真实项目
```

Agent 生成 Diff 时允许写入隔离工作区，但在用户最终审核前不得修改真实项目。任务确认和变更审核是两个不同的确认点。

## 4. 核心领域模型

### 4.1 ConversationSession

- 表名：`conversation_sessions`
- `id: UUID`
- `title: varchar(255) | null`
- `project_id: UUID | null`
- `status: active | archived`
- `created_at`、`updated_at`

`project_id` 表示用户显式设置的会话项目。Resolver 的临时判断不能静默更新该字段。日常聊天允许没有项目。

### 4.2 ConversationTurn

- 表名：`conversation_turns`
- `id: UUID`
- `session_id: UUID`
- `client_message_id: UUID`
- `status`
- `explicit_project_id: UUID | null`
- `resolved_project_id: UUID | null`
- `context_decision: resolved | needs_clarification | no_project | null`
- `context_confidence: numeric | null`
- `context_snapshot: JSONB`
- `provider_name`、`provider_model`
- `error_code`、`error_message`
- `version: integer`
- `created_at`、`updated_at`、`completed_at`

Turn 状态：

```text
accepted
  -> resolving_context
  -> needs_clarification
  -> extracting_memory
  -> generating
  -> completed

任一处理状态 -> provider_unavailable | failed
provider_unavailable | failed -> retry 后重新进入 resolving_context
```

状态更新使用版本号或带当前状态条件的 UPDATE，避免多个 Worker 同时完成同一个 Turn。

### 4.3 Message

- 表名：`messages`
- `id: UUID`
- `session_id: UUID`
- `turn_id: UUID`
- `sequence_no: bigint`
- `role: user | assistant | system | tool`
- `kind: text | transcript | tool_result`
- `content: text`
- `status: pending | complete | failed`
- `metadata: JSONB`
- `created_at`

消息不提供物理删除。用户消息创建后内容不可修改；Assistant 消息允许从 `pending` 写入最终内容并转为 `complete`，或转为 `failed`，进入终态后内容不可覆盖。未来如需修订，新增修订消息或审计事件而不是改写历史消息。

### 4.4 ProjectContextItem

- 表名：`project_context_items`
- `id: UUID`
- `project_id: UUID`
- `kind: fact | decision | constraint | summary`
- `content: text`
- `status: active | superseded`
- `source_message_id: UUID | null`
- `created_at`、`superseded_at`

项目上下文条目必须属于项目，不允许全局条目误入项目上下文。

### 4.5 MemoryCandidate

- 表名：`memory_candidates`
- `id: UUID`
- `session_id: UUID`
- `turn_id: UUID`
- `source_message_id: UUID`
- `scope: global | project`
- `project_id: UUID | null`
- `kind: preference | fact | decision | task`
- `content: text`
- `confidence: numeric`
- `status: pending | accepted | rejected`
- `decided_at`
- `created_at`

约束：

- `scope=project` 时必须有 `project_id`。
- `scope=global` 时 `project_id` 必须为空。
- 只允许 `pending -> accepted` 或 `pending -> rejected`。
- 只有 `accepted` 候选可以进入后续模型上下文。
- P1 直接把已接受候选作为有效记忆读取，不额外创建 `memories` 表；未来引入版本、过期和向量索引时再迁移为独立记忆实体。

### 4.6 AuditEvent

- 表名：`audit_events`
- `id: UUID`
- `sequence_no: bigint`（数据库生成，全局单调递增，用于稳定排序）
- `session_id: UUID | null`
- `turn_id: UUID | null`
- `event_type: varchar(100)`
- `actor_type: user | system | provider | agent`
- `actor_id: varchar(255) | null`
- `payload: JSONB`
- `created_at`

审计事件只追加，不更新，并按 `sequence_no` 排序，不能依赖同一事务内可能相同的时间戳。P1 至少记录：

```text
message.accepted
context.resolved
context.clarification_required
llm.attempt.started
llm.attempt.completed
llm.attempt.failed
memory.candidates.extracted
memory.candidate.accepted
memory.candidate.rejected
turn.completed
turn.failed
```

审计 payload 不保存 API key、Authorization header、完整内部 system prompt 或未脱敏的 Provider 原始响应。

## 5. 数据约束和删除策略

- 所有外键使用 `RESTRICT`，不使用级联物理删除。
- `UNIQUE(session_id, client_message_id)` 保证移动端重试幂等。
- `UNIQUE(session_id, sequence_no)` 保证消息顺序稳定。
- 同一 Turn 最多一个 user message 和一个最终 assistant message，由数据库部分唯一索引保证。
- 分配 `sequence_no` 时锁定会话行，同一事务内计算下一个序号并插入消息，不能依赖无锁 `MAX(sequence_no) + 1`。
- 消息、Turn 状态和对应审计事件在同一事务内提交，避免业务状态存在但审计记录缺失。
- 会话和项目使用归档，不物理删除。
- P1 迁移不要求 pgvector 扩展存在，开发环境仍保留 pgvector 镜像。

## 6. 上下文解析

`ContextResolver` 返回判断，不直接更新会话或项目：

```python
class ContextResolver(Protocol):
    async def resolve(self, request: ContextResolutionRequest) -> ResolvedContext: ...
```

`ResolvedContext` 包含：

- `decision`
- `project_id`
- `confidence`
- `candidates`
- `clarification_question`
- `evidence`
- `resolver_name` 和 `resolver_version`

解析优先级：

1. 用户显式传入且有效的 `project_id`。
2. 会话已由用户显式绑定的项目。
3. 项目名称的确定性精确匹配；项目别名在后续增加独立数据模型后参与匹配。
4. 可替换 Resolver 的候选排序。
5. 多个候选接近、置信度不足或证据冲突时必须澄清。
6. 没有候选时保持 `no_project`，不得擅自创建项目。

Resolver 的结果完整保存到 Turn 快照。自动解析只影响当前 Turn，不静默修改会话的 `project_id`。

## 7. 上下文预算

`ContextAssembler` 按固定预算构建 LLM 请求，禁止把完整历史无限拼接：

1. 当前用户消息。
2. 最近消息窗口，按 token 预算截断。
3. 当前项目的有效上下文条目。
4. 当前项目的已接受记忆。
5. 明确接受的全局记忆。
6. 后续可选的会话摘要和向量召回结果。

P1 默认采用字符估算器作为跨 Provider 的保守预算，Provider 可注入更准确的 tokenizer。每个组成部分都记录来源 ID，便于解释“这次回答使用了哪些上下文”。

## 8. LLM 契约和路由

业务层使用强类型模型：

```python
class LLMRequest(BaseModel):
    request_id: UUID
    task: LLMTask
    messages: list[LLMMessage]
    tools: list[LLMTool]
    requested_model: str | None
    timeout_seconds: float
    max_output_tokens: int | None

class LLMResponse(BaseModel):
    request_id: UUID
    content: str
    provider: str
    model: str
    finish_reason: str | None
    usage: LLMUsage
    latency_ms: int
```

`LLMRouter` 根据任务类型、配置和 Provider 可用性选择适配器。P1 默认注册 OpenAI Provider；vLLM 优先复用 OpenAI-compatible 适配器；阿里云和 Anthropic 使用独立适配器转换协议。ConversationService 不引用任何厂商 SDK。

缺少密钥时 Provider 注册为 unavailable，应用仍能启动。需要生成回复时，系统保存用户消息和 Turn，将 Turn 标记为 `provider_unavailable` 并返回稳定错误代码。

## 9. MemoryExtractor

`MemoryExtractor` 只返回候选：

```python
class MemoryExtractor(Protocol):
    async def extract(self, request: MemoryExtractionRequest) -> list[ExtractedMemory]: ...
```

- 候选必须引用来源消息。
- Extractor 失败不影响已经生成的 Assistant 回复。
- 无可用 Provider 时跳过提取并写审计事件，不伪造候选。
- 定时任务可以重新扫描未处理 Turn 或生成快照，但不能自动接受候选。
- 接受和拒绝均为幂等操作，已做决定后提交相同决定返回原结果，提交相反决定返回冲突。

## 10. API

```text
POST /api/v1/conversations
GET  /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}
GET  /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/turns
GET  /api/v1/conversations/{conversation_id}/turns/{turn_id}
POST /api/v1/conversations/{conversation_id}/turns/{turn_id}/retry
GET  /api/v1/conversations/{conversation_id}/turns/{turn_id}/events
POST /api/v1/memory-candidates/{candidate_id}/decision
```

提交 Turn：

```json
{
  "client_message_id": "95c025dd-854f-4ce8-b0a5-0ba83f764a7b",
  "input": {
    "kind": "text",
    "text": "继续完善 AIOS 的对话模块"
  },
  "project_id": null
}
```

语音接入后只增加 `input.kind=audio` 和音频引用，STT 生成 transcript 后进入同一个 Turn。

同步完成返回 `201`；重复幂等请求返回同一资源和 `200`；需要澄清返回正常业务响应；后续异步处理返回 `202` 和状态查询地址。

只要用户消息和 Turn 已成功持久化，提交接口就返回 Turn 资源，而不是把 Provider 失败伪装成整个 HTTP 请求失败。首次创建返回 `201`，其中 Turn 可以是 `completed`、`needs_clarification`、`provider_unavailable` 或 `failed`；重复的 `client_message_id` 返回原 Turn 和 `200`。只有请求校验失败、会话不存在或数据库无法保存输入时才返回 4xx/5xx 错误响应。

## 11. 错误和健康检查

统一错误响应：

```json
{
  "error": {
    "code": "LLM_PROVIDER_UNAVAILABLE",
    "message": "AI 服务暂时不可用",
    "retryable": false,
    "request_id": "request-uuid",
    "details": {}
  }
}
```

- `/health/live` 只判断进程存活，正常返回 200。
- `/health/ready` 检查数据库和至少一个对话 Provider；依赖不可用时返回 503 或 `degraded`。
- 429、超时和临时 5xx 可在 Provider 内有限重试。
- 认证错误、配置错误、模型不存在不自动重试。
- Provider 失败后保留用户消息、Turn 和审计事件，允许显式重试。
- ContextResolver 的可选模型调用失败时降级到确定性规则；仍无法唯一判断项目时要求澄清，不因此丢失整个 Turn。
- TTS 失败时降级为文字，不改变对话 Turn 的完成状态。

## 12. 移动端流程

- 首屏直接进入最近会话，没有营销页。
- 支持新建会话、会话列表、消息列表、文字输入、发送中、失败和重试状态。
- 客户端在发送前生成 `client_message_id`，本地保留待发送消息，服务端返回后按 ID 合并。
- 项目歧义以 Assistant 澄清消息和候选项目选择呈现。
- 记忆候选以待确认操作显示，接受或拒绝后立即更新状态。
- P1 不实现语音录制，但 UI 和 API 类型不得假设输入永远只有文本。

## 13. 后续执行工作流接口

P1 的对话编排只产生普通回复或未来的 `ExecutionTaskDraft`。执行工作流后续采用以下状态：

```text
draft
-> awaiting_task_confirmation
-> queued
-> running_in_isolation
-> awaiting_change_review
-> approved | rejected
-> applying
-> applied | failed | rolled_back
```

是否使用 PostgreSQL lease worker、Redis 队列或 Temporal 留在执行层内部，不进入对话领域对象。MVP 优先使用 PostgreSQL 持久任务和 Worker，规模或恢复需求增加后可替换为专业工作流引擎。

## 14. 测试策略

后端必须覆盖：

- 会话创建、列表、归档过滤和消息游标分页。
- 用户消息先持久化，Provider 失败后仍可查询。
- 重复和并发 `client_message_id` 不重复生成 Turn。
- 项目显式选择、精确匹配、无项目和歧义澄清。
- Resolver 不修改会话项目。
- 只有 accepted 记忆进入上下文，项目记忆不能跨项目读取。
- 记忆候选状态转换和幂等决定。
- Turn 合法与非法状态转换。
- Provider 缺少配置、超时、限流和非重试错误。
- 审计事件追加写入且不泄漏密钥。
- 数据库迁移 upgrade、downgrade、upgrade。

移动端必须覆盖：

- 新建会话和加载消息。
- 乐观发送、成功合并、失败和重试。
- 项目澄清选择。
- API 地址配置和网络错误。

## 15. 实施顺序

1. 统一错误契约并拆分 live/ready 健康检查。
2. 新增领域枚举、数据库模型和 Alembic 迁移。
3. 实现 Repository、状态转换和幂等约束。
4. 实现 ContextResolver、ContextAssembler、LLMRouter 和 MemoryExtractor 接口及确定性默认实现。
5. 实现 ConversationService 与 REST API。
6. 实现移动端文字对话流程。
7. 完成数据库迁移、后端、Web、Mobile 全量验证。
8. 更新项目记忆和真实执行架构图。

## 16. 明确不采用的做法

- 不把聊天消息、Agent 任务和文件 Change 放进同一张通用表。
- 不让 LLM 输出直接修改 `conversation.project_id`。
- 不把未确认候选直接写入长期记忆或向量索引。
- 不在 P1 引入 Milvus、Redis、Celery、Temporal 或 LangGraph。
- 不为语音复制一套 Conversation API。
- 不在日志和审计表中保存密钥或完整内部 prompt。
- 不在真实项目目录中生成待审核 Diff。

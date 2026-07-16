# AIOS Cognitive Engine 与 Idea Evolution Engine 设计

> 版本：v1.1
> 日期：2026-07-15  
> 状态：已确认
> 前置：P1-A 对话核心、P1-B 手机文字对话、P1-C 持久语音转写

## 1. 目标

AIOS 不采用“一句话直接交给 LLM 或 Agent”的工作方式。每个文字或语音 Turn 先经过认知层，系统理解当前交互的性质、所属项目、是否需要澄清以及是否应生成待确认候选，最后才决定如何回复或是否进入执行准备。

本设计新增三个边界清晰的领域：

1. `Cognitive Engine`：理解当前 Turn 和当前对话阶段。
2. `Inspiration Pool`：保存经用户确认的原子灵感及生命周期。
3. `Idea Evolution Engine`：跨时间发现灵感之间的关系，提出新的方向假设，并通过版本化 `IdeaDirection` 保存用户确认后的长期演化结果。

三个领域都遵守同一原则：自动理解和提出建议可以，替用户确认、合并、决策或执行不可以。

## 2. 核心数据流

```text
文字 / 语音转写
-> 持久 Conversation Turn
-> Cognitive Context Assembler
-> Cognitive Engine
-> CognitiveDecision
   |- 普通回复
   |- 主动澄清
   |- Memory Candidate
   |- Inspiration Candidate
   |- Decision Candidate
   `- ExecutionTaskDraft Candidate
-> 用户确认候选
-> 已确认灵感进入 Inspiration Pool
-> Idea Evolution Engine 事件扫描 / 定时扫描
-> EvolutionProposal
-> 用户接受 / 拒绝 / 延后
-> 接受后才建立关系，或创建/更新 IdeaDirection 版本
```

语音只负责产生可信 transcript，随后复用同一认知管道。Agent 只接收已经确认的 `ExecutionTask`，不能直接消费原始对话或 `CognitiveDecision`。

## 3. 模块边界

### 3.1 Cognitive Engine

纯判断接口，不直接读写数据库，不调用 Agent：

```python
class CognitiveEngine(Protocol):
    async def assess(self, request: CognitiveRequest) -> CognitiveDecision:
        ...
```

输入由上层组装：

```text
CognitiveRequest
  turn_id
  user_text
  recent_messages
  session_project
  project_candidates
  accepted_memory_summaries
  active_inspiration_summaries
  previous_thread_phase
  locale
```

输出必须结构化、可验证：

```text
CognitiveDecision
  primary_mode
  secondary_signals[]
  thread_phase
  project_resolution
  confidence
  needs_clarification
  clarification_question?
  proposed_artifacts[]
  recommended_response_mode
  evidence_summary
  engine_name / engine_version / provider / model
```

`evidence_summary` 只保存简短、可向用户解释的依据，不保存模型隐藏思维链。

### 3.2 Cognitive Orchestrator

负责副作用，但不负责自由判断：

- 组装有界认知上下文。
- 调用 `CognitiveEngine`。
- 校验输出枚举、置信度和候选约束。
- 持久化不可变 `CognitiveAssessment`。
- 根据策略创建 pending 候选。
- 失败时降级为普通对话，不丢失 Turn，不进入执行。

现有 `ContextResolver` 成为认知管道的项目解析子组件，不再由 `ConversationService` 单独承担未来所有理解职责。

### 3.3 Inspiration Pool

只保存用户已经接受的灵感。模型检测到灵感时先产生 `InspirationCandidate`：

```text
pending -> accepted | rejected
```

接受后创建 `Inspiration`，其生命周期为：

```text
active -> incubating -> evolved | converted_to_task | archived
```

- `active`：近期活跃、仍在讨论。
- `incubating`：暂未行动但继续保留。
- `evolved`：已被接受的演化提案吸收到新主题或方向，原记录只读保留。
- `converted_to_task`：用户确认生成任务草案，不代表已经执行。
- `archived`：用户主动归档。

状态转换必须记录用户或系统 actor、来源 Turn 和审计事件。AI 不能自动把 pending 变成 accepted，也不能自动把灵感变成任务。

### 3.4 Idea Evolution Engine

纯分析接口，不直接修改灵感：

```python
class IdeaEvolutionEngine(Protocol):
    async def analyze(
        self, request: EvolutionRequest
    ) -> list[EvolutionProposalDraft]:
        ...
```

它负责：

- 发现重复、延伸、支持、冲突、依赖、组成关系。
- 发现跨时间主题和灵感簇。
- 判断一个灵感簇是否正在形成产品方向、研究方向或能力方向。
- 综合多个并不完全相同、但互相补充的灵感，提出新的方向假设，而不只是做相似度聚类。
- 生成时间线、证据角色、方向论点、潜在价值、矛盾、未决问题、置信度和不确定性。
- 识别新灵感是在支持、反驳、扩展还是分叉一个已有方向，并提出新的方向版本。
- 避免重复提出用户已拒绝且没有新证据的建议。

它不负责：

- 自动合并灵感。
- 自动修改原始文本。
- 自动接受产品方向。
- 删除、覆盖或折叠原始灵感。
- 自动创建已确认任务。
- 调用 Agent 或外部系统。

`Idea Evolution Engine` 是二阶认知层：Memory 回答“过去记录了什么”，Cognitive Engine 回答“当前这句话是什么”，Idea Evolution Engine 回答“这些跨时间想法正在共同长成什么”。它输出的是待审核假设，不是真相或授权。

## 4. 认知分类

### 4.1 Turn 级交互模式

`primary_mode` 第一阶段固定为：

```text
casual_chat
discussion
inspiration
decision
task_intent
execution_intent
venting
question
```

说明：

- `task_intent` 表示用户认为某件事需要被完成。
- `execution_intent` 表示用户正在要求系统准备或开始执行，仍必须进入确认门。
- `venting` 默认只提供理解和回应，不能因为出现负面描述就擅自创建任务。
- 一句话可能有多个信号，但只能有一个 `primary_mode`，其他放入 `secondary_signals`。

### 4.2 会话级阶段

Turn 模式与长期讨论阶段分开保存：

```text
open
exploring
converging
decided
action_ready
```

例如当前一句话可以是 `question`，但整个线程已处于 `converging`。认知引擎不能把单句分类当成不可逆的会话状态。

### 4.3 建议动作

```text
reply
clarify
propose_memory
propose_inspiration
propose_decision
propose_task_draft
request_execution_confirmation
```

建议动作只驱动候选创建，不是执行命令。

## 5. 判断策略

第一阶段采用混合策略：

1. 确定性规则识别明确表达，例如“我有个想法”“我决定”“帮我执行”“只是吐槽”。
2. 项目解析继续复用确定性 `ContextResolver`。
3. 歧义输入通过可替换 `CognitiveProvider` 进行结构化分类。
4. `CognitivePolicy` 合并规则和模型结果，并决定是否需要澄清。

推荐该方案的原因：纯规则无法理解长期讨论，纯 LLM 又不够稳定且难以回归测试。混合策略让高风险动作由确定性策略收口，同时保留模型理解能力。

Provider 接口预留：

```text
deterministic
openai-compatible
aliyun
anthropic
local-vllm
```

业务层不引用厂商 SDK 类型。Provider 不可用时降级到确定性判断和普通对话，不生成执行确认。

## 6. 持久化模型

第一阶段继续使用 PostgreSQL，不引入图数据库或专用工作流引擎。

### 6.1 cognitive_assessments

```text
id
turn_id
revision
primary_mode
secondary_signals JSONB
thread_phase
project_resolution JSONB
confidence
needs_clarification
clarification_question
proposed_artifacts JSONB
recommended_response_mode
evidence_summary
engine_name / engine_version
provider_name / provider_model
created_at
supersedes_id?
```

Assessment 创建后不可覆盖。重新评估产生新 revision，并通过 `supersedes_id` 保留历史。

### 6.2 inspiration_candidates

```text
id
session_id / turn_id / source_message_id
project_id?
title
content
confidence
status: pending | accepted | rejected
decision_reason?
created_at / decided_at
```

### 6.3 inspirations

```text
id
project_id?
origin_candidate_id
title
content
lifecycle_status
version
created_at / updated_at
```

### 6.4 inspiration_relations

```text
id
source_inspiration_id
target_inspiration_id
relation_type: duplicates | extends | supports | conflicts | depends_on | part_of
origin_proposal_id
status: active | superseded
confidence
created_at
```

只有用户接受演化提案后才能创建 relation。

### 6.5 idea_directions

```text
id
project_id?
direction_kind: product | research | capability | open
lifecycle_status: active | incubating | archived
current_version
created_at / updated_at
```

`IdeaDirection` 是跨时间演化出的高层方向，不是普通 Inspiration。接受方向提案不会删除、覆盖或自动改变任何来源 Inspiration 的生命周期。

### 6.6 idea_direction_versions

```text
id
direction_id
version
title
thesis
synthesis
maturity: emerging | forming | coherent | actionable
opportunity
tensions JSONB
open_questions JSONB
evidence_summary
origin_proposal_id
created_at
```

方向更新始终创建新版本，旧版本不可覆盖。这样可以解释方向在数月或数年中如何形成、分叉和修正。

### 6.7 idea_direction_members

```text
direction_id
inspiration_id
role: core | supporting | contradicting | branch
first_linked_version
status: active | superseded
created_at
```

成员关系保存来源证据和角色。原始 Inspiration 继续独立存在，并可同时支持多个方向。

### 6.8 evolution_proposals

```text
id
project_id?
proposal_type: relate | create_direction | update_direction
target_direction_id?
title
summary
evidence JSONB
confidence
engine_name / engine_version
status: pending | accepted | rejected | snoozed | superseded
deduplication_key
created_at / decided_at
```

提案成员使用独立 `evolution_proposal_members` 保存，避免把可变 ID 列表仅放在 JSONB 中。

`create_direction` 至少需要三个已确认灵感，且证据来自至少两个不同 Turn。`update_direction` 必须引用已有方向和至少一个尚未纳入该方向的新证据。将方向转成任务属于未来 ExecutionTaskDraft 设计，不属于 Evolution Proposal。

## 7. 灵感演化流程

### 7.1 触发方式

- 事件触发：新灵感被用户接受或现有灵感被更新。
- 定时扫描：默认每日做轻量增量扫描，每周做项目级主题扫描；均可配置关闭。
- 手动触发：用户请求“整理这个项目最近的灵感”。

事件触发保证不丢进展，定时扫描负责发现跨时间关系。定时任务不能自动接受或合并任何内容。

### 7.2 候选检索

第一阶段使用可替换 `InspirationCandidateRetriever`：

```text
project scope
recent time window
PostgreSQL full-text / trigram
explicit tags and entities
```

后续可增加 pgvector 或其他向量库实现。检索接口不暴露数据库类型，因此无需重写演化引擎。

### 7.3 提案生成

```text
检索候选
-> 关系评分
-> 时间线与冲突检查
-> 去重已有/已拒绝提案
-> 生成 EvolutionProposalDraft
-> 策略校验
-> 持久化 pending 提案
-> 用户审核
```

提案必须显示：

- 涉及哪些灵感及其时间。
- 为什么认为它们有关。
- 是重复、延伸、冲突还是共同方向。
- 置信度和不确定性。
- 接受后会发生什么，不接受则不会发生什么。

## 8. 与现有模块的关系

### Conversation

`ConversationService` 继续负责 Turn 持久化和回复生命周期，逐步把项目解析、意图判断和候选生成委托给 `CognitiveOrchestrator`。迁移期间保留现有确定性行为，避免一次性重写对话核心。

### Memory

Memory 保存稳定事实、偏好和需要长期记住的上下文。Inspiration 保存可能变化、尚在成长的创造性想法。同一 Turn 可以同时产生两类 pending 候选，但必须分别确认。

### Execution

`execution_intent` 最多生成 `ExecutionTaskDraft Candidate`。用户第一次确认后才创建 Execution Task；隔离 Agent 生成 Diff 后仍需第二次审核。

### Project

所有 assessment、inspiration、relation 和 proposal 必须带可验证的项目范围。无项目的全局灵感允许存在，但不能在没有明确解析时静默移动到某个项目。

### Voice

VoiceTranscription 绑定成标准 transcript Message 后，与文字 Turn 完全相同。第一阶段不使用音调、情绪或其他声学信号；未来通过可选 `ParalinguisticSignalProvider` 接入，不改变认知合同。

## 9. 错误与恢复

- Cognitive Provider 失败：保留 Turn，记录脱敏审计，降级到规则和普通回复。
- Cognitive 输出非法：拒绝该输出，不创建候选，不进入执行。
- 候选持久化失败：不影响用户消息，允许幂等重试。
- Evolution 扫描失败：记录 attempt，按增量游标重试，不产生部分 relation。
- 用户拒绝提案：保留拒绝和证据指纹；只有出现新成员或新证据才允许再次提议。
- 用户接受合并时：提案状态、relation、目标主题和源灵感生命周期在同一事务中更新。

## 10. 安全与隐私

- 认知结果不是授权令牌。
- 任何外部写入继续经过两次确认策略。
- 原始模型响应、密钥和隐藏思维链不得进入日志或审计。
- 项目数据严格按 `project_id` 过滤；开放局域网或公网前增加用户身份边界。
- 演化扫描默认只处理 accepted 灵感，不能把 rejected candidate 重新带回模型上下文。
- 自动化策略以后可以降低低风险候选的提示频率，但必须复用同一 Policy 接口，不能绕过审计。

## 11. MVP 范围

### 第一阶段

- 强类型 Cognitive contracts。
- 确定性 + 可替换 Provider 的混合分类。
- Shadow mode：只记录 assessment，不改变现有回复行为。
- Inspiration Candidate 接受/拒绝。
- Inspiration Pool 列表、详情和生命周期操作。
- PostgreSQL 文本候选检索。
- `relate`、`create_direction` 与 `update_direction` 三类 Evolution Proposal。
- 版本化 IdeaDirection、证据角色和演化时间线。
- 用户接受/拒绝/延后提案。

### 延后

- 自动知识图谱。
- 图数据库。
- 大规模向量聚类。
- 自动产品命名、商业判断或把方向当作事实。
- 自动把灵感变成执行任务。
- 多用户协作编辑。
- 实时语音情绪识别。

## 12. 测试策略

后端必须覆盖：

- 每种 primary mode 的确定性样例和歧义样例。
- 同一句话的 secondary signals。
- Turn 模式与 thread phase 分离。
- 项目歧义时只澄清，不创建项目候选。
- venting 不自动生成任务。
- execution_intent 只能生成待确认草案。
- Cognitive Provider 失败降级。
- Assessment revision 不覆盖历史。
- Inspiration Candidate 只有 accepted 才进入 Pool。
- relation 只有提案 accepted 后创建。
- IdeaDirection 只有 `create_direction` 提案 accepted 后创建。
- `update_direction` 接受后只追加版本，不能覆盖历史版本或来源灵感。
- 同一灵感可支持多个方向，项目间灵感不能进入同一方向。
- 已拒绝提案去重与新证据重开。
- 项目隔离和无项目全局灵感。
- 事件触发与定时扫描幂等。
- 审计不泄漏原始 Provider 错误和隐藏推理。

## 13. 实施顺序

1. 建立 Cognitive contracts、状态枚举和 shadow assessment。
2. 将现有 ContextResolver 接入 Cognitive Orchestrator，但保持旧行为不变。
3. 实现 Inspiration Candidate 与用户确认 API。
4. 实现 Inspiration Pool 和移动端入口。
5. 实现 Retriever 接口与 PostgreSQL 文本检索。
6. 实现 Idea Evolution Engine、pending proposal 和审核 API。
7. 接入定时增量扫描与快照，不自动接受提案。
8. 稳定后再把 task/execution intent 接入 ExecutionTaskDraft。

## 14. 验收标准

- 任意 Turn 都能得到版本化、结构化、可审计的 CognitiveAssessment。
- Provider 缺失时文字/语音对话仍可用，且不会误触发执行。
- 灵感只有用户接受后才进入 Inspiration Pool。
- 系统能对跨时间灵感生成带证据的关系、方向创建或方向更新提案。
- 拒绝提案不会修改任何灵感关系。
- 接受提案以事务方式建立关系或追加 IdeaDirection 版本，并可从审计恢复过程。
- 任意方向都能追溯到未被覆盖的原始灵感、来源 Turn 和历史版本。
- Cognitive、Evolution、Retriever 和 Provider 都可替换，不要求重写 Conversation、Voice 或 Execution。

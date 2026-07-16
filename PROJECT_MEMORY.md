# AIOS 项目记忆

> 最后更新：2026-07-15（P2 Codex Agent real plugin 接入完成）
>
> 用途：记录架构决策、当前实现状态、验证结果和下一步。实现细节保存在 `docs/specs` 与 `docs/plans`，本文件只保留恢复项目所需的高价值上下文。

## 产品方向

AIOS 是面向个人的 AI 协作操作系统，最终形态是类似 ChatGPT 的手机 App，支持语音/文字日常对话。AI 帮助用户理解、记录、整理和执行，但不替用户做决定。涉及代码修改或外部系统写入时采用两次确认：先确认任务范围，再让 Agent 在隔离环境生成 Diff 和测试结果，最后审核是否应用到真实项目。

## 当前架构决策

- 后端：Python 3.12.10、FastAPI、SQLAlchemy async、Pydantic v2、Alembic。
- 数据库：PostgreSQL 16；开发库端口 `5432`，专用测试库端口 `5433`。pgvector 镜像保留，P1 不依赖向量检索。
- 客户端：React + Vite Web 管理后台；React Native + Expo 52 手机客户端。
- 对话与执行是两个状态机。Conversation Turn 负责聊天、项目解析和记忆候选；Execution Task 以后负责任务确认、隔离 Agent、Diff 审核和应用。
- `Cognitive Engine` 已作为 Conversation 与候选策略之间的独立层运行：判断聊天、讨论、灵感、决定、任务、执行意图或情绪表达并输出结构化 `CognitiveDecision`；它不直接写长期记忆、创建执行任务或调用 Agent。
- `ExecutionTaskDraft` 采用独立 Draft + confirmed Task：认知层只能生成 pending Draft，用户第一次确认后才创建不可变 `ExecutionTask(status=confirmed)`；confirmed 本身不排队、不调用 Agent、不写真实项目。
- 项目开发 Draft 在 pending 阶段允许补选项目，接受时必须绑定未归档项目；用户可编辑目标、验收标准、业务约束和允许路径，系统隔离/禁止 commit、push、deploy 等守卫不可编辑。
- `Idea Evolution Engine` 不是记忆检索器，而是二阶认知层：Memory 回答“过去记录了什么”，Cognitive Engine 回答“当前这句话是什么”，Evolution 回答“这些跨时间想法正在共同长成什么”。
- 演化结果使用独立、版本化的 `IdeaDirection`，不把多个灵感覆盖或折叠成一条普通灵感。方向保留 thesis、成熟度、机会、矛盾、未决问题、证据角色和历史版本；每个版本都可追溯到未修改的来源 Inspiration 与 Turn。
- Evolution 只生成 `relate | create_direction | update_direction` 待审核提案。接受后才建立关系或追加方向版本；转成任务必须进入未来 `ExecutionTaskDraft`，不能由 Evolution 调用 Agent。
- 用户消息必须在调用 LLM 前提交。`(session_id, client_message_id)` 保证重试幂等。
- Conversation 的项目可以为空。Resolver 结果只影响当前 Turn，不能静默修改会话项目；有多个候选时主动澄清。
- 记忆先进入 `pending` 候选，用户接受后才能进入模型上下文；项目记忆严格按 `project_id` 隔离。
- LLM 使用强类型 `LLMRequest` / `LLMResponse` 和 `LLMRouter`；当前 OpenAI 适配器已实现，vLLM 可复用 OpenAI-compatible 协议，阿里和 Anthropic 通过新适配器接入。
- 上下文采用固定字符预算、最近消息窗口、有效项目上下文和已确认记忆，禁止无限拼接历史。
- 审计事件只追加，使用数据库生成的全局 `BIGINT sequence_no` 稳定排序，不能依赖同一事务内相同的时间戳。
- 语音采用 `audio -> durable transcription -> 标准 Turn -> text -> optional audio`，不复制对话领域模型；原始录音默认不落库。
- P1-C 使用强类型 `VoiceRouter` 分别路由 STT/TTS。云端批量首选阿里百炼 `qwen3-asr-flash` / `qwen-audio-3.0-tts-flash`，本地通过 FunASR/CosyVoice HTTP 接入；阿里 `fun-asr-realtime` 留给后续流式阶段。
- Expo 52 使用 `expo-audio ~0.3.5`，所有录音/播放调用封装在 `mobile/src/voice`；原生与 Web 构造器、临时文件清理使用平台文件隔离，避免未来 Expo 升级影响业务层。
- 当前是本地单用户开发模式。暴露到局域网或公网前必须增加认证、用户数据边界、受限 CORS 和密钥管理。

## 已完成

### P0 基础

- 项目 CRUD、归档/恢复 API。
- `BaseAgent`、启动时插件发现、Codex stub 和 `Change` 契约。
- LLM、STT、TTS 抽象接口。
- PostgreSQL 开发/测试环境、迁移、测试数据库身份保护。
- Web 项目管理壳和 Expo 移动端壳。
- Python 3.12 `.venv` 与完整 `requirements.lock`。

### P1-A 可审计对话核心

- 迁移 `0002_create_conversation_core`：
  - `conversation_sessions`
  - `conversation_turns`
  - `messages`
  - `project_context_items`
  - `memory_candidates`
  - `audit_events`
- 统一 API 错误体、`X-Request-ID`、`/health/live` 和 `/health/ready`。
- 强类型 LLM Provider、OpenAI 适配器、可替换 `LLMRouter` 和流式路由接口。
- 确定性 `ContextResolver`：显式项目、会话项目、唯一名称匹配、歧义澄清和无项目日常聊天。
- `BoundedContextAssembler`：只读取 accepted 全局记忆和 resolved project 的 accepted 项目记忆。
- `ExplicitMemoryExtractor`：识别“请记住/记住/remember”并生成 pending 候选，不自动接受。
- `ConversationService` 两阶段事务：先提交输入和审计，再解析上下文、生成记忆候选并调用 Provider；Provider 失败仍保留消息与 pending 记忆候选并支持重试。
- AIOS 系统约束：涉及执行动作只能生成待确认任务草案，不得由对话 Provider 直接执行。
- REST API：
  - `POST/GET /api/v1/conversations`
  - `GET /api/v1/conversations/{id}`
  - `GET /api/v1/conversations/{id}/messages`
  - `POST /api/v1/conversations/{id}/turns`
  - `GET /api/v1/conversations/{id}/turns/{turn_id}`
  - `POST /api/v1/conversations/{id}/turns/{turn_id}/retry`
  - `GET /api/v1/conversations/{id}/turns/{turn_id}/events`
  - `GET /api/v1/memory-candidates?session_id={id}&status=pending`
  - `POST /api/v1/memory-candidates/{id}/decision`
- 真实执行架构图已更新为两次确认和隔离 Agent 流程：`docs/architecture/exec-architecture.html`。

### P1-B 手机文字对话

- Expo App 已实现会话列表、新建/切换会话、消息加载和下拉刷新。
- 发送前生成客户端 UUID 并乐观显示；服务端响应按消息 ID 合并，重复响应不会产生重复消息。
- 网络失败与 `provider_unavailable` 均保留用户消息；失败 Turn 摘要写入消息元数据，App 重启后仍能恢复重试入口。
- 项目歧义候选持久化在 Assistant 消息元数据中，刷新后仍可选择项目并显式提交新 Turn。
- pending 记忆候选可接受或拒绝；决定后从界面移除，刷新后状态保持。
- API 地址保存到 AsyncStorage；连接设置支持真机填写电脑局域网地址。
- 语音输入已在 P1-C 接入同一聊天界面；文字发送、项目澄清、记忆决定和失败恢复仍沿用原路径。
- 使用强类型 `AIOSApiClient`、统一 `APIError` 和纯 `chatReducer`；浏览器原生 fetch 调用上下文问题已有回归测试。
- Expo Web 预览和生产导出已接通，手机视口 `390x844` 完成空状态、Provider 失败、记忆确认和刷新恢复检查。
- 同一失败 Turn 重试时不再重复生成记忆候选；已有候选时写入 `memory.extraction.skipped` 审计事件。

### P1-C 手机语音闭环（已完成）

- 已完成阿里云百炼、FunASR/SenseVoice、CosyVoice/Kokoro 与 Expo SDK 52 调研。
- 已确定持久化 `VoiceTranscription`，通过 `transcription_id` 进入现有 Turn；同一转写只能绑定一个 Turn。
- 已确定批量按住说话为首个闭环，全双工、打断、回声消除和流式 WebSocket 延后。
- 已确定 TTS 为非权威输出适配器，失败只降级为文字，不改变 Turn 状态。
- 已实现强类型 `STTRequest/Response/Chunk`、`STTStreamRequest`、`TTSRequest/Response/Chunk`、Provider 错误和独立 `VoiceRouter`；批量 Provider 不会伪装流式能力。
- Voice Router 拒绝重复 Provider 名称、禁止静默回退；`DASHSCOPE_API_KEY` 使用 `SecretStr`，Provider catalog 不暴露密钥或内部 URL。
- 已实现阿里 Qwen-ASR Data URL、阿里 SpeechSynthesizer、FunASR OpenAI multipart 和 CosyVoice SFT HTTP 适配器；Provider 可通过配置组合装配。
- 阿里 TTS 支持 inline Base64 或签名 URL 下载；CosyVoice 将官方裸 PCM 明确描述为 24kHz mono，并可封装 WAV。Provider 不支持的格式、采样率和语速会明确报错。
- FastAPI 复用进程级 `VoiceRouter`，不会为每个请求重复创建 OpenAI/httpx 连接池。
- 迁移 `0003_create_voice_transcriptions` 已建立持久转写资源；原始音频不落库，只保存会话、客户端音频 ID、SHA-256、格式、大小、转写、Provider、状态和错误元数据。
- 转写状态、终态必需字段、同会话上传幂等、单 Turn 绑定和小写 SHA-256 均有数据库约束。
- 已实现 Provider catalog、受限 multipart 上传、持久转写创建/查询和二进制 TTS API；上传读取最多为配置上限加 1 字节。
- Turn 输入已扩展为 `text | transcript` 判别联合。服务端锁定 completed 转写，在同一事务中创建 Turn、可信 `kind=transcript` Message、绑定 `turn_id` 并追加审计事件。
- 同一转写不能跨会话使用或绑定第二个 Turn；重复 `client_message_id` 返回原 Turn，LLM 重试复用已保存转写且不重新调用 STT。
- 同一 `client_audio_id` 携带不同音频、MIME 或语言时返回 `VOICE_IDEMPOTENCY_CONFLICT`；Provider 和未知 TTS 错误均使用稳定、脱敏错误契约。
- Expo 已安装 SDK 52 兼容的 `expo-audio ~0.3.5` 与 `expo-file-system ~18.0.12`，只申请前台麦克风权限，不启用后台录音。
- 手机端已实现按住开始、松开结束、300ms 以下丢弃、60 秒自动截止、multipart 上传、可信 transcript Turn 和语音状态条。
- 上传失败保留同一临时录音和 `client_audio_id`；Turn 失败保留同一 `transcription_id` 与 `client_message_id`。重试不会退化成新的文字 Turn，也不会重复调用 STT。
- 只有语音来源 Turn 的 Assistant 回复会尝试 TTS；播放前会停止旧音频，完成后释放播放器和缓存，TTS 失败始终保留文字回复。
- 新录音和切换会话会停止当前播放；取消、切换会话和组件卸载会停止录音并清理临时文件。
- 停止与取消共享单一 recorder 所有权，竞态不会重复调用原生 `stop()`；UI 在 59.5 秒主动收尾，底层 60 秒截止作为硬保险。
- Expo Web 通过 `expoRecorderFactory.web.ts` 使用 `AudioRecorderWeb`，通过 `recordingFile.web.ts` 释放 `blob:` URL；原生继续使用 `AudioRecorder` 和 FileSystem。
- `mobile/tsconfig.json` 排除 `dist` / `web-build`，防止 Expo 的 2.22MB Web bundle 因 `allowJs` 被 TypeScript 再次分析。
- 设计：`docs/specs/2026-07-15-aios-p1-voice-design.md`。
- 实施计划：`docs/plans/2026-07-15-aios-p1-voice-plan.md`。

### Agent Execution Pipeline + Mobile Diff Review（已完成）

- 迁移 `0008_create_execution_runs` 已应用：`execution_runs` + `execution_changes` 表。
- 执行管线完整代码层：isolation、dispatch（PULL模式）、runner（BackgroundTasks自动触发）、review、apply。
- Shell Agent 支持通过 `git add -A` + `git diff --cached` 捕获新建文件变更，保护隔离 workspace 不被 task context 覆盖。
- E2E 测试通过：Shell Agent + Test Agent 隔离执行 + 全量 674 passed。
- 移动端 `ExecutionRunReview` 组件：polling等待、inline diff 查看、按文件 accept/reject、批量决定、提交审核、应用到真实项目。
- App.tsx 链路：accept task → dispatch + auto-run → ExecutionRunReview → apply → notice。
- API client 已完成 dispatch/review/decide/apply 方法，types 已完成 ExecutionRun/ExecutionChange 强类型。
- 第二次确认流完整闭环：User 查看 Agent 生成的 Diff → accept/reject 每个变更 → submit decisions → apply。
- 隔离已实现 GitWorktreeProvider（git worktree remove --force），TempDirProvider 作为非 git 项目后备。Shell/Test/Git/LLM Coder Agent 共存于注册表。

### Cognitive Shadow（已完成）

- 已定义强类型 `CognitiveRequest` / `CognitiveDecision`、可替换 `CognitiveEngine`、确定性规则引擎和可选语义引擎。
- 已建立迁移 `0004_create_cognitive_assessment`，Assessment 采用不可变 revision，并受数据库约束保护。
- 已实现有界认知上下文和 `CognitiveOrchestrator`：当前输入完整保留且不重复进入历史；历史最多查询 100 条并受字符预算限制；Engine 输出重新验证后才可持久化。
- Cognitive Shadow 已在项目解析后、澄清分支前接入标准 Turn；文字和语音转写共用入口，LLM 重试复用 revision 1。
- Shadow 默认开启，可用 `COGNITIVE_SHADOW_ENABLED=false` 关闭；当前为确定性引擎 + `semantic=None`，`get_cognitive_engine` 是未来语义模型/Provider 的替换点。
- Shadow 只保存判断与脱敏审计，不改变 Assistant 回复，不创建灵感/任务候选，不调用 Agent，也不提交或回滚调用方事务。
- 已提供只读 `GET /api/v1/conversations/{conversation_id}/turns/{turn_id}/cognitive-assessments`；revision 升序返回并提供 `latest`，跨会话 Turn 统一隐藏为不存在，响应不暴露原始 Provider 数据或异常详情。

### Inspiration Pool（已完成）

- 已定义严格候选状态 `pending | accepted | rejected` 和灵感生命周期 `active | incubating | evolved | converted_to_task | archived`；用户生命周期接口以后只能执行白名单转换，不能直接进入派生状态。
- Inspiration 投影复用 Cognitive `ProjectResolution`，不建立第二套项目判断。
- 已建立迁移 `0005_create_inspiration_pool`：`inspiration_candidates` 使用 `(assessment_id, artifact_index)` 唯一去重，`inspirations` 使用唯一 `origin_candidate_id` 保证接受重试只产生一个池记录。
- 已实现 `AssessmentInspirationProjector`：只读取持久化 Assessment，重新验证项目快照和 artifacts，先完成全量验证再写入，避免部分候选；并发调用锁定 Assessment，重试返回同一 candidate。
- Projector 已在 Cognitive 成功后接入文字与 transcript Turn，默认由 `INSPIRATION_CANDIDATES_ENABLED=true` 开启；失败降级为脱敏审计，不改变 Assistant 回复、Turn 状态或执行边界。
- 已实现 pending candidate 接受/拒绝、Inspiration Pool 查询/详情和受限生命周期 API；接受候选只创建唯一 Inspiration，不创建任务或调用 Agent。
- Expo 已实现候选审核条、灵感池入口、全局/项目筛选和 active/incubating/archived 状态操作；异步刷新按 active conversation 校验，避免旧会话候选串入新会话。
- 已用真实 PostgreSQL 数据完成接受候选、打开灵感池、项目筛选和生命周期转换；390px 无横向溢出，标题与正文相同时不重复展示。

### Idea Evolution Engine（已完成）

- 已确定原始 Inspiration 永久保留，不合并成 synthetic Inspiration；分析只生成 `relate | create_direction | update_direction` 待审核提案。
- 用户接受方向提案后才允许创建或追加版本化 `IdeaDirection`；从方向转任务仍必须进入未来 `ExecutionTaskDraft` 确认流。
- 已完成严格 Evolution contracts、迁移 `0006_create_idea_evolution`、提案/关系/方向版本/成员/扫描尝试持久化模型和数据库约束。
- 已完成有界 PostgreSQL Retriever：只读取 accepted、同项目、active/incubating Inspiration，并加载同作用域当前 IdeaDirection 版本。
- 已完成保守确定性引擎与可选 Hybrid 语义引擎；中文业务短语使用分段二元/三元字符信号，过滤 `AIOS` 品牌词误关联。
- Hybrid 会重新验证模型输出的成员、目标方向、证据时间和“更新必须使用新证据”边界；Provider 失败时保留确定性结果，不暴露异常原文。
- 默认装配仍是 PostgreSQL Retriever + deterministic engine + `semantic=None`，OpenAI 兼容、阿里或本地 vLLM 以后只需增加语义适配器。
- 已完成 `EvolutionScanOrchestrator`：manual/event/scheduled 共用同一幂等入口，同 cursor 重放返回原 Attempt 与 Proposal，失败 Attempt 可用同 cursor 恢复。
- 扫描只持久化 pending Proposal、成员、脱敏审计和 `evolution_scan_proposals` 追踪，不创建 Relation、IdeaDirection、方向版本、任务或 Agent 调用。
- 方向提案使用严格 `direction_payload` 保存 thesis、synthesis、maturity、opportunity、tensions 和 open_questions，后续审核能明确知道用户接受的内容。
- Proposal 去重采用“形状键 + 证据指纹”联合唯一；Provider 只改写说明文案不会重开已拒绝提案，来源成员或证据角色发生实质变化时才允许重新进入 pending。
- 已开放 scan、Proposal 列表/详情/决定、IdeaDirection 列表/详情 API；详情返回来源灵感、证据角色和时间，错误项目作用域统一隐藏为 404。
- 审核事务支持 `accepted | rejected | snoozed`：重复同一决定幂等，不同决定返回 409；snooze 必须使用未来时间。
- 接受 `relate` 原子创建一条 Relation；接受 `create_direction` 原子创建方向、v1 和来源成员；接受 `update_direction` 锁定当前版本并追加不可变 vN+1 与新证据成员。
- 接受前重新验证来源仍为 accepted、同作用域且 active/incubating；过期来源会阻止接受，但用户仍可拒绝或稍后处理过期提案。
- 原始 Inspiration 内容和生命周期在所有审核路径中保持不变；拒绝和稍后处理不创建任何派生状态。
- 已完成 event/scheduled one-shot worker。接受 Inspiration 会在同一事务写入不可变 `evolution.scan.requested` 标记，重复接受不会重复入队。
- 每次 worker 只处理一个工作单元，优先级为：待处理事件、到期全局日扫描、一个到期项目周扫描；项目按稳定顺序逐个认领。
- PostgreSQL session advisory lock 防止并发 worker 重复处理，并严格在 commit/rollback 前释放；不可获取锁时直接返回 `locked`。
- cursor 只有 completed Attempt 才算推进；分析失败保存脱敏 failed Attempt，同一 cursor 下次优先重试，不会跳到下一个项目。
- 已在 SQL 层排除完成的事件 cursor，避免不可变 AuditEvent 前 100 条长期占据窗口导致新事件饥饿。
- `EVOLUTION_SCANS_ENABLED=false` 默认关闭；命令入口 `backend/scripts/run_evolution_scan.py` 可交给 Windows Task Scheduler、cron 或容器调度，不在 FastAPI 内运行无限循环。
- Expo 抽屉已加入“灵感进化”入口，打开全屏审核工作区；“待审核 / 方向”标签和“全部 / 全局 / 项目”分段筛选适合手机重复审核。
- 提案列表显示类型、作用域、置信度和摘要；详情按“判断依据 -> 证据时间线 -> 当前版本对照 -> 新方向内容 -> 不确定性 -> 接受影响 -> 决定”顺序呈现。
- `update_direction` 会按需读取目标 IdeaDirection，展示当前 synthesis 与拟更新内容；方向视图提供只读不可变版本时间线和来源证据数量。
- 接受、拒绝和 7 天后处理在请求期间禁用重复操作；决定成功后立即移出 pending 列表，接受方向后刷新版本视图。
- 详情加载失败仍保留返回列表和刷新入口；界面不显示 Provider 原始输出、隐藏推理、任务执行或 Agent 操作。
- 测试数据库已验证 `0005 -> 0006 -> 0005 -> 0006` 和 `alembic check`；开发数据库已在全量检查通过后前向升级到 `0006_create_idea_evolution (head)`。
- 开发库真实闭环已验证：拒绝 relation 后派生状态为零；接受 create_direction 生成 v1；新证据接受 update_direction 后生成不可变 v2 和第 4 个成员；全部原始 Inspiration 标题、正文和生命周期保持不变。验证数据已按隔离项目 ID 精确清理。
- 真实执行架构图已将 Idea Evolution Engine、one-shot worker、Evolution Review 和版本化存储标为 Real，同时继续把 ExecutionTaskDraft 与真实 Agent 执行标为 Future。

### ExecutionTaskDraft 第一次确认（进行中）

- 当前隔离实现分支为 `feature/execution-task-draft`，worktree 为 `F:\AIOS\.worktrees\execution-task-draft`。
- 已完成严格 Draft/Task 状态、风险和执行域契约，以及项目内相对路径规范化；绝对路径、盘符、空段和 `.` / `..` 路径会被拒绝。
- 已建立可替换 `TaskDraftPolicy` 与 `TaskDraftSourceAdapter` 边界。当前确定性策略只生成待审核范围，不选择或调用 Agent；未来 IdeaDirection、Inspiration 或外部系统仍只能通过适配器生成 pending Draft。
- 系统守卫固定为隔离执行、禁止直接写真实项目、禁止自动 commit/push/deploy；中英文删除、迁移、提交、推送、部署、生产或外部写入信号会把建议风险提升为 high。
- 已完成迁移 `0007_create_execution_tasks`：新增 `execution_task_drafts` 与 `execution_tasks`。Draft 项目可空，confirmed Task 项目必填；来源证据链全部 `ON DELETE RESTRICT`，唯一 Assessment artifact 与唯一 origin Draft 在数据库层保证幂等。
- Draft/Task 的 JSON 数组、策略对象、完整系统守卫、状态、决定时间、置信度、版本和必填文本均有 PostgreSQL 约束。测试库已完成 `0006 -> 0007 -> 0006 -> 0007`；开发库仍保持 `0006`，只在完整验证通过后前向升级。
- 已完成 `AssessmentTaskDraftProjector`：只处理最新、无需澄清的 task/execution Assessment，并重新验证模式、建议动作、项目快照、来源用户消息、全部 artifact 和每个 Policy 输出；所有 projection 验证完成后才写库。
- 同一 `(assessment_id, artifact_index)` 重放返回原 Draft 且不重复审计。无项目可生成待补全 Draft；无效项目/持久化 artifact/替换 Policy 只写脱敏失败事件。Projector 不 commit/rollback，不依赖 Agent、队列或 Change。
- Draft projector 已在 Cognitive 与 Inspiration 之后、LLM 调用之前接入统一 `_process_turn`，文字和 transcript Turn 共用；`EXECUTION_TASK_DRAFTS_ENABLED=true` 可独立关闭，关闭后仍保留 Cognitive Assessment。
- Provider 不可用时 Draft 随前置事务持久化；retry 复用 revision 1 Assessment 和原 Draft。项目澄清不生成 Draft。Projector 在数据库 savepoint 内运行，数据库错误只回滚投影并写固定错误码，不改变 Assistant 回复或 Turn 状态。
- 已完成 `ExecutionTaskService`：pending Draft 可在 `expected_version` 乐观锁下编辑项目、标题、目标、验收标准、用户约束和允许路径；所有输入先完整验证后才修改 ORM，失败不会留下脏范围。terminal Draft 不可编辑。
- 接受 Draft 会锁行、重新验证最新 Assessment/来源消息/活动项目/范围/系统守卫，并在同一事务创建唯一 `ExecutionTask(status=confirmed)` 快照；同版本重复接受返回同一 Task，旧版本仍报冲突。拒绝不创建 Task，且来源 Assessment 已过期时仍允许拒绝。
- 已提供 Draft 列表/详情/PATCH/决定与 confirmed Task 列表/详情 API。Draft 资源按 `session_id` 隐藏跨会话访问，Task 按 `project_id` 隐藏跨项目访问；详情只返回 500 字来源摘录、项目元数据和结构化范围，不返回隐藏推理或 Provider 原文。
- `confirmed` 仅表示第一次范围确认；当前没有 Dispatcher/Worker 监听、没有 Agent/Change/Git/测试/部署调用，也没有 Task 状态转换 API。
- Mobile 已增加独立 `ExecutionTaskDraft` / `ExecutionTask` / Policy / 状态强类型，以及 pending 列表、详情、版本化 PATCH、接受/拒绝、Task 列表/详情 client 方法；聊天 `MessageMetadata` 未加入 execution 字段。
- Mobile 纯表单 helper 已实现换行列表裁剪、去空、稳定去重、格式化和缺项目/目标/验收标准校验；不依赖 React 或网络，可单独回归。
- 会话候选区已增加紧凑“待确认任务”条，展示标题、项目缺失/已选和风险；点击进入全屏无嵌套卡片的范围审核，项目从活动项目列表选择，标题/目标/验收/约束/路径可编辑。
- 审核页展示来源摘录、建议能力和不可编辑系统守卫；有未保存修改、缺项目、缺目标或缺验收标准时不能接受，但仍可拒绝。保存携带当前 version，请求期间禁用重复操作。
- Draft 列表与消息/记忆/灵感同批加载，发送、语音 Turn 和 retry 后刷新；所有 Draft/详情异步结果按 active conversation 校验。切换会话或重连会关闭旧详情，版本冲突自动刷新最新范围。
- 接受成功从 pending 移除并显示“等待隔离调度；当前尚未启动 Agent”回执；拒绝移除且不显示执行状态。当前界面没有 Dispatcher、Agent 或应用变更入口。

## 未完成与边界

- P1-C 代码闭环已完成；真实阿里调用仍需要 `DASHSCOPE_API_KEY` 与 Workspace ID，本地调用仍需要独立 FunASR/CosyVoice 服务。本轮只使用 Fake Provider 验证完整链路，没有把模拟结果描述为真实厂商调用。
- 尚未完成第一次确认的真实 PostgreSQL 清理闭环、运行时和视觉验证；隔离 Worktree/容器、真实 Codex/Claude/Git/Test Agent 也未实现（代码层已完成，移动端 Diff 审核已完成）。
- 多模态文档解析、向量召回、自动摘要和跨设备用户账户尚未实现。
- 当前没有配置真实 `OPENAI_API_KEY` 时，输入仍会持久化，Turn 状态为 `provider_unavailable`，可在配置 Provider 后重试。
- 应用内长期记忆的定时扫描/快照尚未实现。当前候选在 Turn 完成时事件驱动保存；自动任务只能重新扫描或生成快照，不能自动接受记忆。

## P2 Codex Agent 接入（已完成）

- 将 codex-stub 替换为真实 CodexAgent，注册在 pp.agent.plugins.codex_agent/。
- 支持双模式：
  - CLI 模式（优先）：尝试 codex CLI 在隔离 workspace 中执行 coding 任务
  - API 模式（回退）：通过 OpenAI-compatible API（CODEX_API_KEY + CODEX_API_BASE）调用 LLM，解析 <<<FILE:path>>>...<<<END>>> 格式的输出
- Windows Store 版 Codex 因沙箱限制不可被外部进程调用，自动降级为 API 模式提示
- 文件变更一律通过 git diff --cached 捕获并返回 Change 对象，确保审计和审核闭环
- 全量测试 688 passed 零失败；已清理所有旧 codex-stub 引用（代码、测试、API）
- Agent 注册表现在为 5 个真实 agent：codex, git, llm-coder, shell, test
- API GET /api/v1/agents 返回完整 agent 信息

### 当前 Agent 注册表

| Agent | 名称 | 能力 | 需确认 |
|---|---|---|---|
| Codex | codex | code_gen, code_review, refactor, debug | 是 |
| Git | git | git, version-control, vcs | 是 |
| LLM Coder | llm-coder | code_gen, code_review, refactor | 是 |
| Shell | shell | shell, file_gen, build, lint | 是 |
| Test | 	est | test, verify, ci | 否 |

## 下一步

1. 使用 CODEX_API_KEY 真实调用 Codex API 模式的 E2E 管线验证
2. 接入 Claude Code Agent（参考 codex_agent 插件模式，复用 API 模式）
3. 加固 Mobile Expo App Agent 执行交互（Diff review → apply 闭环）
4. 从 Fake LLM 切换到真实 LLM Provider

## 最近验证

- ExecutionTaskDraft 契约/策略 RED：测试因 `app.execution` 不存在而按预期收集失败；GREEN：`34 passed`。
- Execution model RED：测试因 `ExecutionTaskDraft` 未注册而按预期失败；新模型数据库测试 `37 passed`，全部模型回归 `211 passed`。
- 专用测试库迁移 `0006 -> 0007 -> 0006 -> 0007` 成功；当前 `0007_create_execution_tasks (head)`，`alembic check` 返回 `No new upgrade operations detected`。
- Execution projector RED：测试因模块不存在而按预期收集失败；projector 测试 `19 passed`，Execution/模型/Inspiration 投影组合回归 `99 passed`。
- Conversation integration RED：服务因尚不接受 task projector 而按预期失败；数据库失败 savepoint 另完成 RED/GREEN。Conversation、Cognitive、Conversation API 与 projector 回归 `179 passed`。
- Execution service/API RED：测试因 service 模块不存在而按预期收集失败；非法更新原子性另完成 RED/GREEN。Execution/模型/API 组合 `108 passed`，全部现有 API 回归 `69 passed`。
- Mobile transport/form RED：client 方法与 form 模块缺失时按预期失败；全量 Mobile `53 passed`，`npx tsc --noEmit` 成功。
- Mobile first-confirmation RED：组件缺失时按预期收集失败；全量 Mobile `56 passed`，`npx tsc --noEmit` 成功，`npx expo install --check` 返回依赖已匹配。
- 隔离分支相关后端基线：Cognitive、Inspiration、Evolution、Conversation 与 Conversation API 共 `252 passed`。
- 隔离分支 Mobile 基线：`49 passed`；`npx tsc --noEmit` 成功。
- `.venv\Scripts\python.exe -m pytest backend/tests -q`：`555 passed`。
- `.venv\Scripts\python.exe -m pytest backend/tests/evolution/test_rules.py backend/tests/evolution/test_hybrid.py backend/tests/evolution/test_retriever.py backend/tests/evolution/test_base.py -q`：`56 passed`。
- `.venv\Scripts\python.exe -m pytest backend/tests/evolution backend/tests/models/test_evolution_models.py -q`：`142 passed`。
- `.venv\Scripts\python.exe -m pytest backend/tests/evolution backend/tests/api/test_evolution.py backend/tests/models/test_evolution_models.py -q`：`149 passed`。
- `.venv\Scripts\python.exe -m pytest backend/tests/evolution backend/tests/inspiration/test_service.py backend/tests/api/test_inspiration.py backend/tests/api/test_evolution.py -q`：`96 passed`。
- `.venv\Scripts\python.exe backend/scripts/run_evolution_scan.py`：默认关闭配置下退出码 `0`。
- `npm test`（Mobile）：`49 passed`。
- `npx tsc --noEmit`（Mobile）：成功。
- `npx expo install --check`（Mobile）：依赖版本匹配 Expo 52。
- `npx expo config --type public`（Mobile）：iOS、Android、Web 配置解析成功。
- `npx expo-doctor`（Mobile）：`18/18 checks passed`。
- `npx expo export --platform web`（Mobile）：2032 个模块成功导出，Web bundle 为 2.22MB。
- Fake Provider 完整闭环：能力发现 -> multipart STT -> durable transcription -> transcript Turn -> Fake LLM -> binary TTS，集成测试通过；STT/LLM/TTS 各调用一次。
- Expo 语音 Playwright 检查覆盖 `390x844` 和 `1440x900` 的 idle、recording、Provider unavailable、failure/retry、transcribing、sending 与 TTS text fallback，共 13 个状态，均无横向溢出；关键截图人工检查无控件遮挡。
- 隔离分支后端 `http://127.0.0.1:8011`：`/api/v1/health/live` 返回 200，数据库 connected；未配置 LLM 时 ready 返回 503 degraded。Voice catalog 正常返回空 STT/TTS 列表。
- 隔离分支 Expo Web `http://127.0.0.1:8092`：HTTP 200，并显式连接 `8011`。
- 当前架构图 `http://127.0.0.1:8093/exec-architecture.html`：桌面与 390px 手机均为 7 层、0 个溢出节点，手机长截图人工检查无重叠。
- Expo Evolution Review 使用隔离 `aios_test` 后端完成 390x844 和 1280x800 视觉/交互检查：无控制台错误、无横向溢出，审核按钮完整可见；桌面内容限制为 936px 可读宽度。
- 测试库 `0006 -> 0005 -> 0006` 往返成功；测试库与开发库 `alembic check` 均返回 `No new upgrade operations detected`。
- 开发库当前为 `0006_create_idea_evolution (head)`。
- 开发库真实 PostgreSQL 审核闭环：方向版本 `[1, 2]`、4 个来源成员、原始来源未改写、拒绝 relation 派生数为 0；隔离验证项目清理后剩余数为 0。
- `docs/architecture/exec-architecture.html` 在 1440px 与 390px 检查：7 个层级无重叠、无横向溢出、无控制台错误。
- `.venv\Scripts\python.exe -m pytest backend/tests/cognitive backend/tests/inspiration backend/tests/api/test_inspiration.py -q`：`137 passed`。
- 测试库 `0005 -> 0004 -> 0005` 迁移往返成功；`alembic check` 返回 `No new upgrade operations detected`。
- 开发库迁移历史：`0004_create_cognitive_assessment -> 0005_create_inspiration_pool -> 0006_create_idea_evolution (head)`。
- `npm test -- --run`（Web）：`12 passed`。
- `npm run build`（Web）：成功。
- `npm test`（Mobile）：`21 passed`。
- `npx tsc --noEmit`（Mobile）：成功。
- `npx expo install --check`（Mobile）：依赖版本匹配 Expo 52。
- `npx expo config --type public`（Mobile）：iOS、Android、Web 配置解析成功。
- `npx expo-doctor`（Mobile）：`18/18 checks passed`。
- `npx expo export --platform web`（Mobile）：成功，2005 个模块导出到临时验证目录。
- 当前后端 `http://127.0.0.1:8001`：健康检查返回 200，OpenAPI 包含 5 条 Inspiration 路由。
- 当前 Expo Web `http://127.0.0.1:8082`：已清缓存重启并连接 `8001`；390px 可打开灵感池，无控制台错误或横向溢出。
- 当前架构图 `http://127.0.0.1:8089/exec-architecture.html`：HTTP 200；桌面与 390px 手机长截图已检查，无重叠或横向溢出。
- npm 输出存在用户级未知配置警告，但不影响测试或构建；后续升级 npm 前清理用户级 `.npmrc`。

## 关键文档与提交

- P1 设计：`docs/specs/2026-07-15-aios-p1-conversation-core-design.md`
- P1 后端计划：`docs/plans/2026-07-15-aios-p1-conversation-core-plan.md`
- P1 手机计划：`docs/plans/2026-07-15-aios-p1-mobile-text-plan.md`
- P1-C 语音设计：`docs/specs/2026-07-15-aios-p1-voice-design.md`
- P1-C 语音计划：`docs/plans/2026-07-15-aios-p1-voice-plan.md`
- ExecutionTaskDraft 设计：`docs/specs/2026-07-15-aios-execution-task-draft-design.md`
- ExecutionTaskDraft 实施计划：`docs/plans/2026-07-15-aios-execution-task-draft-plan.md`
- Cognitive / Inspiration / Idea Evolution 设计：`docs/specs/2026-07-15-aios-cognitive-idea-evolution-design.md`
- Cognitive Shadow 实施计划：`docs/plans/2026-07-15-aios-cognitive-shadow-plan.md`
- Inspiration Pool 后续计划：`docs/plans/2026-07-15-aios-inspiration-pool-plan.md`
- Idea Evolution Engine 后续计划：`docs/plans/2026-07-15-aios-idea-evolution-plan.md`
- P1 设计提交：`46c0ca2`
- P1 计划提交：`28fc98b`
- P1-A 里程碑：`299472b`
- P1-B 代码提交序列：`6a6b7db`、`4fb01c7`、`7c2a6d7`、`fb0df61`、`05b273f`、`45bb6c6`
- 记忆重试幂等修复：`a70bc56`
- P1-C 强类型语音契约：`7774248`
- P1-C 云端/本地语音 Provider：`f622b0f`
- P1-C 转写资源迁移：`182d257`
- P1-C 移动语音传输与音频适配器：`d48d537`
- P1-C 按住说话与状态机：`6549284`
- Cognitive 设计/实施计划：`c426ea2`、`2349526`
- Cognitive 契约、分类与持久化：`59d1220`、`60cffc4`、`18a96d4`
- Cognitive Shadow 编排、Conversation 集成与历史 API：`9fd3725`、`6d04dcb`、`0574f10`
- Inspiration 契约与数据层：`2f41979`、`9ecc204`
- Inspiration 投影、Conversation 集成与审核 API：`a418df2`、`1d540a2`、`0854ac5`
- Inspiration Expo 审核体验：`a512b46`
- 认知“元吐槽”误判回归修复：`715fc63`
- 版本化 IdeaDirection 设计决策：`16a3feb`
- Idea Evolution 契约、持久化与 Retriever：`a65f068`、`b370cd7`、`100cde7`
- Idea Evolution 分析引擎：`98a6b5e`
- Idea Evolution 扫描编排：`d2094ce`
- Idea Evolution 审核事务与 API：`46055f8`
- Idea Evolution one-shot worker：`ece1831`
- Idea Evolution Expo 审核体验：`7c5a14a`
- Inspiration 投影与 Conversation 集成：`a418df2`、`1d540a2`

## 保存规则

- 每完成一个架构决策、数据库迁移、可运行功能或完整验证，就更新本文件并提交。
- 主线程只保留当前决策、验证结果和下一步；详细接口、状态机和测试步骤写入 specs/plans，控制上下文长度。
- 应用运行后采用“事件立即持久化 + 定时扫描/快照”保存记忆，但只有用户明确接受的候选能成为长期记忆。
## 2026-07-16: LLM endpoint finalization

- `http://ai.747698.xyz/v1` selected as LLM proxy
- Default model: `gpt-5.4-mini` (stable, Chinese ok with AIOS system prompt)
- Fallback: `deepseek-v4-flash` (native Chinese but occasionally returns empty)
- Not working on this proxy: qwen3-max, all Gemini, all Grok, all Zhipu, mimo
- Agnes API (`https://apihub.agnes-ai.com/v1`) tested and rejected: `agnes-1.5-flash` cannot read Chinese input
- Server start: must use `cmd /c cd /d F:\AIOS\backend && python -m uvicorn` -- `Start-Process -WorkingDirectory` does not set cwd for .env loading
- Backend PID: latest starts via cmd.exe wrapper, port 8001
- Future: DashScope (Aliyun) direct API recommended for qwen3-max when key becomes available

## 2026-07-16: Code Review Fixes (All Completed)

- 5 fixes applied from code review. Final: **688 passed / 0 failed**.

### Fix 1: ExecutionTaskResponse context field
- schemas/execution.py: added \context: dict[str, object] | None = None\

### Fix 2: Shared diff.py module
- Created \pp/agent/diff.py\ with \parse_diff()\, \extract_path()\, \make_change()\
- Uses \chr(10)\ instead of literal \\\n\ to avoid shell escape corruption
- 4 agents updated: \codex_agent\, \git_agent\, \llm_coder\, \shell_agent\ all import from \pp.agent.diff\
- Removed duplicate \_parse_diff\ / \_extract_path\ / \_make_change\ from all 4 agents

### Fix 3: ChangeApplier MODIFY path
- \execution/apply.py\: \	arget.write_text(content)\ is now primary, \git apply\ is fallback
- Avoids Windows CRLF encoding issues with git apply subprocess

### Fix 4: OpenAI provider test
- \	est_openai_provider.py\: updated assertion to accept \ase_url=None, http_client=ANY\

### Fix 5: .env.example
- Created \ackend/.env.example\ with all config variables and defaults, no real keys

### Bug discovered and fixed: 3 agents missing module-level agent variable
- \git_agent\, \llm_coder\, \shell_agent\ plugin.py files were missing \gent = XxxAgent()\
- Registry only discovered 2 agents (codex, test); now discovers all 5

### Agent Registry (current state)
| Agent | Name | Confirmation |
|---|---|---|
| Codex | codex | Yes |
| Git | git | Yes |
| LLM Coder | llm-coder | Yes |
| Shell | shell | Yes |
| Test | test | No |

### Verification
- \python -m pytest tests/ -q\: 688 passed, 0 failed, 2 warnings

## 2026-07-17: Architecture Freeze — V1 Development Start

### Frozen Architecture (V1-V3)

**Data Layer:**
  Memory (done) → Knowledge (V2) → World Model (V3)

**Decision Layer:**
  Goal (V2) → Planner (V3) → Decision (V1 now)

**Execution Layer:**
  Task (done) → Execution (done) → Learning (V3) → Evolution (done)

### V1 Scope (current iteration)
- Decision Engine + Decision Memory: structured decision storage with candidates, pros/cons, final choice, future review conditions
- Learning Mode: new InteractionMode.LEARNING for "why?"/"what is?"/"compare X vs Y?" queries
- Research Agent: read-only agent for tech explanation and comparison, zero code modification

### Reservations
- Planner's dependency on World Model is optional enhancement, not hard requirement
- Observation Layer reserved for future (runtime state monitoring)
- Meta Layer reserved for future (system self-reflection and self-modification)

### Migration: 0009_create_decisions (decision_candidates table)

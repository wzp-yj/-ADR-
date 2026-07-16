# AIOS P0: 基础架构 & 项目管理 — 设计文档

> **版本:** v1.1 | **日期:** 2026-07-14 | **状态:** 已审核

## 1. 项目概述

AIOS (AI Operating System) 是面向个人的 AI 协作操作系统。核心理念：AI 不替用户做决定，帮用户理解、记录、整理、执行。所有执行动作默认需要用户确认，可配置自动执行。

最终产品形态为手机 App（ChatGPT 式语音对话交互），配合 Web 管理后台。

## 2. P0 目标

搭建可扩展后端骨架，实现项目管理 CRUD，定义 Agent 插件接口和 LLMProvider 抽象，为后续所有子系统提供基础。

**产出物：**
- FastAPI 后端骨架（含数据库、迁移、配置）
- Project CRUD API（6 个端点，含软删除恢复）
- Agent 插件注册与发现机制
- LLMProvider 抽象层（OpenAI 默认实现）
- VoiceProvider 抽象层（流式 STT/TTS，P0 仅定义接口）
- Change 数据模型（Agent ↔ 审核中心契约）
- 全链路错误处理策略
- 测试策略与框架
- React Web 管理后台（项目列表/创建/删除/恢复归档）
- React Native 移动壳（Expo 空白项目，API 连通验证）
- Docker Compose（PostgreSQL + pgvector）

## 3. 总体架构

```
用户                 AIOS Backend (FastAPI)              外部服务
───                 ──────────────────────              ──────
│
│  [Mobile App] ──→ REST/WS ──→ ┌──────────────────┐    ┌─────────┐
│  (React Native)               │  API Layer        │    │ OpenAI   │
│                               │  /api/projects    │    │ API      │
│  [Web Admin]  ──→ REST ────→ │  /api/agents      │    └─────────┘
│  (React)                      └────────┬─────────┘
│                                        │              ┌─────────┐
│                               ┌────────▼─────────┐    │ FunASR  │
│                               │  Agent Registry   │    │ (阿里云) │
│                               │  BaseAgent (ABC)  │    └─────────┘
│                               └────────┬─────────┘
│                                        │              ┌─────────┐
│                               ┌────────▼─────────┐    │ Edge    │
│                               │  LLMProvider (ABC)│    │ TTS     │
│                               └────────┬─────────┘    └─────────┘
│                                        │
│                               ┌────────▼─────────┐
│                               │  VoiceProvider    │
│                               │  STT/TTS (ABC)   │
│                               └────────┬─────────┘
│                                        │
│                               ┌────────▼─────────┐
│                               │  PostgreSQL       │
│                               │  + pgvector       │
│                               └──────────────────┘
```

### 执行流程（全文交互链路 + 错误传递）

```
用户语音 → FunASR STT(stream) → 文本输入
                ↓ (STTError → 语音提示用户重试)
        ┌───────────────────┐
        │  AIOS Core 调度    │
        │                   │
        │  1. 检索项目上下文 │
        │  2. 检索长期记忆   │
        │  3. LLM 意图解析   │
        │  4. Agent 路由决策 │  ← LLMError → 下游透传, 返回友好消息
        └───────┬───────────┘
                ↓
        ┌───────────────────┐
        │  Agent 生成变更    │
        │  → AgentResult    │  ← AgentError → 审核中心展示失败原因
        └───────┬───────────┘
                ↓
        ┌───────────────────┐
        │  审核中心          │
        │  Diff 展示 → 确认  │  ← 用户拒绝 → 生成 RejectionResult, 不回滚
        └───────┬───────────┘
                ↓
          执行 / 回滚      ← ExecutionError → 回滚已应用的 Change
                ↓
        Edge TTS(stream) → 语音回复  ← TTSError → 降级为纯文本
```

## 4. 技术栈

| 层 | 技术 | 备注 |
|---|---|---|
| 后端框架 | Python 3.12 + FastAPI | 异步，自动生成 OpenAPI schema |
| ORM | SQLAlchemy 2.0 (async) | |
| 数据校验 | Pydantic v2 | |
| 数据库 | PostgreSQL 16 + pgvector | 结构化 + 向量一体 |
| 迁移 | Alembic | |
| LLM | OpenAI API（默认） | LLMProvider 抽象可替换 |
| STT | FunASR（阿里云 API） | 流式实时识别，有移动端 SDK |
| TTS | Edge TTS | 免费，中文自然度优 |
| Web 前端 | React 18 + TypeScript | P0 最小管理后台 |
| 移动端 | React Native + Expo | P0 空白壳，P1 实现对话 UI |
| LLM SDK | openai (Python) | 同时兼容 OpenAI/兼容 API |
| 部署 | Docker Compose | PostgreSQL + pgvector 服务 |
| 测试 | pytest + pytest-asyncio + httpx | 后端 |
| 前端测试 | Vitest + React Testing Library | P3 阶段引入 |

## 5. 数据模型

### 5.1 Project

```
projects
├── id            UUID (PK, default=uuid4)
├── name          VARCHAR(255), UNIQUE, NOT NULL
├── description   TEXT, nullable
├── created_at    TIMESTAMP, default=now()
├── updated_at    TIMESTAMP, onupdate=now()
└── is_archived   BOOLEAN, default=FALSE
```

### 5.2 AgentPlugin（P0 仅内存注册，P3 入库）

```
agent_plugins (P3 阶段)
├── id            UUID (PK)
├── name          VARCHAR(100), UNIQUE
├── description   TEXT
├── capabilities  JSONB  -- ["code_gen", "git_ops"]
├── is_active     BOOLEAN, default=TRUE
├── config        JSONB  -- Agent 特定配置
└── created_at    TIMESTAMP
```

### 5.3 Change（Agent ↔ 审核中心数据契约）

Agent 产出的每个变更均以此结构描述。审核中心读取 `diff` 向用户展示，根据 `action` 决定 UI 呈现方式。

```python
from enum import Enum
from pydantic import BaseModel

class ChangeAction(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"

class ChangeStatus(str, Enum):
    PENDING  = "pending"   # 等待用户确认
    APPROVED = "approved"  # 用户已确认
    REJECTED = "rejected"  # 用户已拒绝
    APPLIED  = "applied"   # 已执行
    FAILED   = "failed"    # 执行失败

class Change(BaseModel):
    path: str                    # 受影响文件的绝对或相对路径
    action: ChangeAction         # 操作类型
    description: str             # 人类可读的变更说明（如"新增 POST /api/users 端点"）
    content_before: str | None   # 变更前内容（create 时为 None）
    content_after: str | None    # 变更后内容（delete 时为 None）
    diff: str | None             # unified diff 文本
    status: ChangeStatus = ChangeStatus.PENDING
    error_message: str | None = None  # 执行失败时的错误信息
```

`AgentResult`:
```python
class AgentResult(BaseModel):
    changes: list[Change]
    summary: str          # Agent 生成的自然语言执行摘要
```

## 6. API 设计

### 6.1 项目管理

| Method | Path | Description | P0 |
|---|---|---|---|
| GET | `/api/v1/projects` | 列表（默认排除已归档） | ✓ |
| GET | `/api/v1/projects?include_archived=true` | 列表（含已归档） | ✓ |
| POST | `/api/v1/projects` | 创建 | ✓ |
| GET | `/api/v1/projects/{id}` | 详情 | ✓ |
| PATCH | `/api/v1/projects/{id}` | 更新 | ✓ |
| POST | `/api/v1/projects/{id}/archive` | 归档（is_archived=true） | ✓ |
| POST | `/api/v1/projects/{id}/restore` | 恢复（is_archived=false） | ✓ |

> 设计决策：用显式 `archive`/`restore` 端点而非 DELETE 语义。归档是可逆操作，语义明确，避免 REST 惯例歧义（DELETE 通常暗示不可逆）。

### 6.2 Agent 管理

| Method | Path | Description | P0 |
|---|---|---|---|
| GET | `/api/v1/agents` | 列出已注册 Agent | ✓ |

### 6.3 健康检查

| Method | Path | Description | P0 |
|---|---|---|---|
| GET | `/api/v1/health` | 服务 + DB 连接状态 | ✓ |

## 7. 核心抽象接口

### 7.1 BaseAgent

```python
class BaseAgent(ABC):
    name: str
    description: str
    capabilities: list[str]
    requires_confirmation: bool = True

    @abstractmethod
    async def execute(self, task: TaskInput, context: ProjectContext) -> AgentResult:
        """执行任务，返回变更列表。异常时应抛出 AgentError。"""
        ...
```

`AgentResult` = `changes: list[Change]` + `summary: str`（Change 结构见 §5.3）

### 7.2 BaseLLMProvider

```python
class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message], tools: list[Tool] | None = None) -> LLMResponse:
        ...

    @abstractmethod
    async def chat_stream(self, messages: list[Message], tools: list[Tool] | None = None) -> AsyncIterator[LLMChunk]:
        ...
```

### 7.3 BaseSTTProvider / BaseTTSProvider（流式）

```python
class BaseSTTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, language: str = "zh") -> str:
        """一次性转录：上传完整音频，返回完整文本。适合短语音。"""
        ...

    @abstractmethod
    async def transcribe_stream(
        self, audio_stream: AsyncIterator[bytes], language: str = "zh"
    ) -> AsyncIterator[str]:
        """流式转录：持续接收音频块，持续产出文本片段。用于边说边出字的实时体验。"""
        ...

class BaseTTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str = "default") -> bytes:
        """一次性合成：传入完整文本，返回完整音频。适合短回复。"""
        ...

    @abstractmethod
    async def synthesize_stream(
        self, text_stream: AsyncIterator[str], voice: str = "default"
    ) -> AsyncIterator[bytes]:
        """流式合成：持续接收文本片段，持续产出音频块。用于 LLM streaming 同步 TTS 输出。"""
        ...
```

### 7.4 注册机制

```python
class AgentRegistry:
    """统一注册入口。

    工作流程：
    1. discover() 扫描 app/agent/plugins/ 下所有包含 plugin.py 的目录
    2. 目录扫描结果加载到内存注册表（dict[name, BaseAgent]）
    3. list_agents() / find_by_capability() 从内存注册表查询
    4. 无运行时热加载（P0 仅启动时扫描一次，P3 加文件监听）

    这意味着：新 Agent 丢入 plugins/ 目录 → 重启服务 → 自动注册。
    """
    async def discover(self) -> None:
        """扫描插件目录，加载所有 Agent 到内存注册表。"""
        ...

    async def list_agents(self) -> list[BaseAgent]:
        """返回已注册 Agent 列表。"""
        ...

    async def find_by_capability(self, capability: str) -> list[BaseAgent]:
        """按能力标签查询匹配的 Agent。"""
        ...
```

> 澄清：目录扫描是"发现方式"，内存注册表是"存储方式"。两者不是两个并行机制，而是同一流程的两个阶段。P0 启动时扫描一次，P3 加 watch 模式。

## 8. 错误处理策略

全链路涉及 LLM、Agent、STT、TTS、数据库等多个异步节点，需统一的错误分类和传播策略。

### 8.1 错误分类

| 错误类型 | 来源 | HTTP 状态码 | 用户可见行为 |
|---|---|---|---|
| `ValidationError` | Pydantic 校验失败 | 422 | 返回字段级错误信息 |
| `NotFoundError` | 资源不存在 | 404 | 返回资源类型 + ID |
| `ConflictError` | 唯一约束冲突 | 409 | 返回冲突字段 |
| `LLMError` | LLM API 超时/限流/返回异常 | 502 | "AI 服务暂时不可用，请稍后重试" |
| `STTError` | STT 识别失败/超时 | 502 | "语音识别失败，请重新说话或切换文字输入" |
| `TTSError` | TTS 合成失败 | — | 降级为纯文本回复，不阻断对话 |
| `AgentError` | Agent 执行异常 | 500 | 审核中心展示失败原因，不执行任何变更 |
| `ExecutionError` | 变更执行失败（部分文件写入异常） | 500 | 回滚已应用的 Change，审核中心展示回滚状态 |

### 8.2 传播规则

1. **向下游透传**：底层异常（如 LLMError）由调用方捕获后包装为统一响应格式，不暴露内部堆栈
2. **非阻断降级**：TTS 失败不阻断文本回复，栈中上层 catch 后继续正常流程
3. **原子性要求**：同一 AgentResult 中的多个 Change 要么全部应用，要么全部回滚
4. **错误日志**：所有 Provider 级异常写入结构化日志（含 trace_id、耗时、重试次数）

## 9. 测试策略

### 9.1 框架

| 测试层 | 工具 | 范围 |
|---|---|---|
| 后端单元测试 | pytest + pytest-asyncio | 纯函数、工具函数、Pydantic 校验 |
| 后端集成测试 | pytest + httpx (AsyncClient) | API 端点全链路（含真实 PostgreSQL） |
| Provider 测试 | pytest + respx (HTTP mock) | LLM/STT/TTS mock 测试 |
| 前端测试 | Vitest + React Testing Library | P3 引入 |

### 9.2 P0 覆盖目标

| 优先级 | 覆盖内容 | 最低覆盖率 |
|---|---|---|
| 必须 | `GET/POST /projects` 正常 + 异常路径 | 100% 端点 |
| 必须 | `PATCH /projects/{id}` 更新不存在的项目 → 404 | |
| 必须 | `POST archive → POST restore` 往返 | |
| 必须 | `GET /agents` 返回注册的桩 Agent | |
| 必须 | `GET /health` 返回 200 + DB 状态 | |
| 必须 | Project 名称唯一约束 → 409 | |
| 建议 | AgentRegistry discover() + list_agents() | |
| 建议 | OpenAIProvider chat() mock 测试 | |

### 9.3 运行方式

```bash
# 启动测试数据库
docker compose -f tests/docker-compose.test.yml up -d

# 运行全部测试
cd backend && pytest -v --cov=app --cov-report=term-missing

# 运行特定测试
pytest tests/api/test_projects.py -v
```

## 10. 目录结构

```
F:\AIOS\
├── docker-compose.yml
├── .gitignore
├── docs/
│   ├── architecture/
│   │   ├── exec-architecture.html
│   │   ├── subsystem-decomposition.html
│   │   └── p0-design.html
│   └── specs/
│       ├── 2026-07-14-aios-p0-foundation-design.md   ← 本文档
│       └── 2026-07-14-aios-p0-review.md               ← 审核意见
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app 入口
│   │   ├── config.py            # 环境变量配置
│   │   ├── database.py          # async engine + session
│   │   ├── errors.py            # 统一错误分类 + 异常处理
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── project.py       # Project ORM model
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── project.py       # Pydantic DTOs
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── router.py        # 主路由注册
│   │   │   ├── projects.py      # Project CRUD endpoints
│   │   │   ├── agents.py        # Agent list endpoint
│   │   │   └── health.py        # Health check
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # BaseAgent ABC
│   │   │   ├── registry.py      # AgentRegistry
│   │   │   ├── models.py        # TaskInput, AgentResult, Change
│   │   │   └── plugins/
│   │   │       └── codex_stub/
│   │   │           └── plugin.py  # P0 桩 Agent
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # BaseLLMProvider ABC
│   │   │   └── openai_provider.py  # OpenAI 实现
│   │   └── voice/
│   │       ├── __init__.py
│   │       ├── base.py          # BaseSTTProvider / BaseTTSProvider
│   │       ├── funasr_provider.py    # FunASR STT 实现 (P4)
│   │       └── edge_tts_provider.py  # Edge TTS 实现 (P4)
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py          # fixtures: async client, test db
│   │   ├── api/
│   │   │   ├── test_projects.py
│   │   │   ├── test_agents.py
│   │   │   └── test_health.py
│   │   ├── agent/
│   │   │   └── test_registry.py
│   │   └── llm/
│   │       └── test_openai_provider.py
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── alembic.ini
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/                     # React Web 管理后台
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── pages/
│   │   │   └── Projects.tsx     # 项目列表 + CRUD + 归档/恢复
│   │   └── api/
│   │       └── client.ts        # typed fetch wrapper
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── mobile/                       # React Native (Expo) 壳
    ├── App.tsx                   # P0: "Connected to AIOS" 占位
    ├── package.json
    └── app.json
```

## 11. P0 范围边界

**做：**
- FastAPI 骨架 + database + config + migrations
- Change 数据模型（AgentResult schema）
- 统一错误分类 + 异常处理中间件
- Project CRUD 全链路（model → schema → api → test），含 archive/restore
- Agent plugin 接口定义 + 注册机制（目录扫描→内存注册）+ 一个桩 Agent
- LLMProvider 抽象 + OpenAI 默认实现（含 mock 测试）
- VoiceProvider 抽象（流式 STT/TTS，仅接口）
- 测试策略框架 + P0 端点全覆盖
- React Web 管理后台（项目列表/创建/归档/恢复）
- React Native Expo 空白壳
- Docker Compose PostgreSQL+pgvector

**不做：**
- 持续对话 / 会话管理 (P1)
- 长期记忆 / 向量存储 (P1)
- 上下文歧义澄清 (P2)
- 灵感池 (P2)
- 多 Agent 调度与真实 Agent 实现 (P3)
- 审核中心 Diff 展示 (P3)
- STT/TTS 实际实现 (P4)
- 移动端对话 UI (P1)
- 用户认证 / 多用户 (P1-P2)

## 12. 扩展点设计原则

- **Agent 插件**：目录丢入即注册，不修改核心代码
- **LLM 模型**：改配置切换 Provider，不改业务逻辑
- **语音引擎**：STT/TTS 独立 Provider，流式接口，可热切换
- **向量数据库**：通过 repository 模式抽象，后续可换 Milvus
- **前端客户端**：Web 和 Mobile 共享 API 类型定义，独立 UI

## 13. 决策记录

| 决策 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 后端语言 | Python vs TypeScript | Python | LLM/AI 生态碾压级优势 |
| 向量数据库 | pgvector vs Milvus/Chroma/LanceDB | pgvector | 一体部署 + 混合查询 |
| LLM 接入 | API vs 自部署 vLLM | API + 可替换接口 | MVP 零运维，接口预留 |
| 前端框架 | React vs Vue | React | 流式渲染生态更好 |
| 移动端 | React Native vs Flutter | React Native | 与 Web 共享类型和逻辑 |
| STT | FunASR vs Whisper | FunASR | 流式识别 + 移动端 SDK + 中文最优 |
| TTS | Edge TTS vs OpenAI TTS | Edge TTS | 免费 + 中文自然度够用 |
| P0 前端范围 | 纯API vs 最小后台 vs 完整骨架 | 最小管理后台 | 验证链路 + 不过度设计 |
| 归档方式 | DELETE 软删除 vs archive/restore 端点 | archive/restore 端点 | 语义明确，可逆操作不隐藏 |

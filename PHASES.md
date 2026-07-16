# AIOS 阶段功能汇总

## 阶段总览

```
P0 Foundation ──► Cognitive Engine ──► P1 Voice/Mobile ──► P2 Agents ──► Architecture Upgrade
   (底座)           (认知能力)           (交互界面)           (执行能力)      (架构深化)
```

---

## P0：Foundation（基础底座）

**时间：** 2026-07-14  
**目标：** 项目骨架搭建，可运行的后端 + 数据库

### 完成的功能
- FastAPI 后端框架搭建
- PostgreSQL 数据库 + pgvector 向量扩展
- SQLAlchemy ORM + Alembic 迁移管理
- 基础 Conversation（对话）模型和 API
- 长期记忆（Memory）的存储和向量检索
- 项目（Project）模型，支持多项目独立上下文
- 基础前端页面（React Web Admin）

### 技术选型
- **Backend**: FastAPI（异步、OpenAPI 自动生成、生态成熟）
- **Database**: PostgreSQL 16 + pgvector（事务 + 向量二合一，降低运维复杂度）
- **ORM**: SQLAlchemy 2.0 async + Alembic
- **Frontend**: React 18 + TypeScript + Tailwind CSS

---

## Cognitive Engine（认知引擎）

### 完成的功能
- **Cognitive Engine**：对话意图识别（闲聊 / 讨论 / 灵感 / 任务 / 吐槽 / 待确认）
- **Inspiration Pool（灵感池）**：接收突然出现的想法，带状态流转（raw → developing → task → archived）
- **Idea Evolution Engine（灵感进化引擎）**：跨时间关联相似灵感，发现成长模式
- **Primary Mode 识别**：chat / discussion / inspiration / task / execution / review / learning
- **Context Management**：多项目上下文切换，指令歧义时主动澄清项目归属

### 关键设计
- Cognitive Engine 位于 LLM 之前，先理解意图再决定路由
- 灵感不直接变成任务，有独立的状态流转管道
- 认知判断规则可配置（`cognitive/rules.py`）

---

## P1：Voice & Mobile（交互界面）

### 完成的功能
- **语音输入**：STT（语音转文字），支持阿里 DashScope + 本地 FunASR
- **语音输出**：TTS（文字转语音），支持阿里 CosyVoice + 本地 CosyVoice
- **Voice Router**：Provider 可切换，拒绝重复 Provider 名称
- **Mobile App**：React Native (Expo 52)，文字对话 + 语音交互
- **Conversation Core**：Turn 管理、消息持久化、Provider 不可用时优雅降级

### 技术方案
- **云端方案（推荐优先）**：阿里 DashScope STT + CosyVoice TTS
- **本地方案（备选）**：FunASR + CosyVoice 本地服务
- **切换机制**：通过 Voice Router 统一管理，Provider 可热切换

---

## P2：Agent Framework & Execution（执行能力）

### 完成的功能
- **Agent Plugin 架构**：插件化注册，新 Agent 只需实现接口
- **Execution Pipeline**：两次确认流程（生成草案 → 展示 diff → 用户确认 → 执行）
- **Codex Agent**：代码生成和修改，支持 diff 解析
- **Git Agent**：版本控制操作（commit、branch、push），需用户确认
- **LLM Coder Agent**：通过 LLM 直接生成代码
- **Shell Agent**：执行 shell 命令，需用户确认
- **Test Agent**：运行测试并报告结果
- **Change Applier**：MODIFY 优先 `write_text`，git apply 降级
- **Shared diff.py**：diff 解析逻辑统一，四个 Agent 共享

### 关键设计
- 所有执行动作默认可配置确认后才执行
- 审核中心展示修改和 diff，用户确认后再执行
- Agent 插件化，新增 Agent 无需改动核心代码

---

## Architecture Upgrade（架构深化）

### 新增模块
- **Decision Engine（决策引擎）**：记录每个重要决策的候选方案、优劣、最终选择和复审条件
- **Decision Memory**：Memory 不仅存 What，还存 Why
- **Research Agent**：不写代码，负责解释技术、比较方案、建立知识关联
- **Learning Mode**：用户问"为什么"时，自动切换到教学模式，关联 AIOS 架构

### 数据库新增
- `decisions` 表：Title, Why, Candidate Solutions, Pros/Cons, Final Choice, Decision Maker, Decision Time, Future Review Condition
- `primary_mode` 枚举新增 `learning`

---

## V2 预留（下一版本）
- Knowledge Graph（技术知识图谱）
- ADR 自动生成
- Goal 层（目标管理）
- World Model（世界模型，可选增强）

## V3 预留（远期）
- Planner（规划器）
- Meta Layer（元认知层）
- Observation Layer（观察层）
- 企业系统集成（微信、钉钉等）

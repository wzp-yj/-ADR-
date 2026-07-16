# AIOS P0 设计文档 — 审核意见

> 审核日期: 2026-07-14 | 审核对象: 2026-07-14-aios-p0-foundation-design.md

---

## P0 · Change 模型未定义 — 核心交互链路的关键缺口

第 7.1 节定义 AgentResult = changes: list[Change] + summary: str，但整个文档从未定义 Change 的结构。Change 是 Agent 输出 → 审核中心 Diff 展示 → 执行/回滚 这条核心链路的唯一数据契约。没有它，Agent 接口和审核中心之间没有可对接的协议。

**建议：** P0 即定义 Change，至少包含：

    class Change:
        type: Literal["create", "update", "delete"]  # 操作类型
        target: str                                    # 目标实体 (e.g. "project", "file")
        target_id: str | None
        before: dict | None                            # 变更前状态，用于 diff
        after: dict | None                             # 变更后状态
        description: str                               # 人类可读的变更说明

---

## P0 · 软删除无恢复路径

DELETE /api/v1/projects/{id} 将 is_archived 设为 true，但：

- 没有 PATCH 端点能将 is_archived 设回 false（恢复）
- GET /api/v1/projects 排除已归档项，导致已归档项目完全不可见

这意味着"软删除"实际上等同于硬删除，用户失去了一切找回途径，违背了软删除的设计意图。

**建议：** PATCH 端点应支持将 is_archived 恢复为 false，或 GET /api/v1/projects 增加 ?include_archived=true 查询参数。

---

## P0 · STT/TTS 接口与"流式实时识别"目标不匹配

文档将 FunASR 描述为"流式实时识别"，但 BaseSTTProvider.transcribe(audio: bytes) -> str 接收完整音频字节并同步返回文本。BaseTTSProvider.synthesize(text: str) -> bytes 也是同步返回完整音频。在真实语音对话中，用户需要边说边识别、边生成边播放。

**建议：** P0 接口层面预留流式签名，即使 P4 才实现：

    class BaseSTTProvider(ABC):
        @abstractmethod
        async def transcribe_stream(self, audio_chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
            ...

    class BaseTTSProvider(ABC):
        @abstractmethod
        async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
            ...

---

## P1 · AgentRegistry 发现机制描述矛盾

第 7.4 节 AgentRegistry 说"插件目录扫描 + 自动注册。新 Agent 丢入 app/agent/plugins/ 即生效"，但第 5.2 节 AgentPlugin 数据模型标注"P0 仅内存注册，P3 入库"。如果 P0 是内存注册，那"丢入即注册"的目录扫描具体如何工作？是启动时 importlib 扫描还是装饰器注册？这两种方式的行为差异很大。

**建议：** 在 P0 明确注册流程。推荐用装饰器 @AgentRegistry.register 做显式注册，避免隐式 importlib 扫描带来的副作用和调试困难。

---

## P1 · 缺少错误处理策略

整个交互链路（STT → Core → Agent → Review → Execute → TTS）有多个异步外部调用节点，每个都可能失败。文档完全没有涉及：

- FunASR 转录失败时用户体验是什么？
- Agent 执行异常如何传递给审核中心？
- LLM 调用超时/限流如何处理？

**建议：** P0 骨架至少定义统一的错误响应格式和异常传播约定：

    {
        "error": {
            "code": "AGENT_EXECUTION_FAILED",
            "message": "...",
            "details": {}
        }
    }

---

## P1 · 无测试策略

第 6.1 节仅在文案中提到 "model → schema → api → test"，但没有独立的测试章节说明框架选择、覆盖目标、集成测试范围。

**建议：** 补充测试策略，至少明确：

- 框架：pytest + pytest-asyncio
- Repository 层单元测试使用 SQLite 内存库避免外部依赖
- API 层集成测试使用 Docker PostgreSQL

---

## P2 · 其他建议

1. **UUID PK 索引性能**
   UUID 作为主键在 PostgreSQL B-tree 索引中可能导致页分裂和膨胀。P0 规模无碍，但建议在决策记录中注明，后续可考虑 ULID 或 UUIDv7。

2. **缺少配置模板**
   目录结构有 config.py 但无 .env.example。建议 P0 同步产出，至少列出 DATABASE_URL、OPENAI_API_KEY 等必要变量。

3. **CORS 配置**
   前端跨域访问需要 CORS 中间件，目录结构中未见 middleware/ 目录。

4. **可观测性**
   骨架阶段至少应包含结构化日志（structlog），成本极低但后续调试收益大。

5. **后端未容器化**
   Docker Compose 仅包含 PostgreSQL，建议 P0 将后端也纳入，确保 docker compose up 一键启动全部服务。

6. **API 分页规范未定义**
   GET /api/v1/projects 标注"分页"，但未说明使用 offset/limit 还是 cursor-based，响应格式也未给出。

---

## 总结

文档结构清晰，技术选型理由充分，P0 范围边界明确。

核心问题集中在 Change 模型缺失和软删除无恢复路径两点，属于数据契约层面的缺陷，建议优先修复后再进入实现。STT/TTS 接口签名问题虽标注 P4 实现，但接口一旦定下后续修改成本高，建议 P0 就采用流式签名。

P1 的注册机制矛盾和错误处理缺失，如果在实现过程中不明确，容易造成返工，建议在编码前澄清。

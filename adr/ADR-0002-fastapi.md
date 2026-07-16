# ADR-0002: FastAPI

| 字段 | 内容 |
|------|------|
| 状态 | 已采纳 |
| 决策日期 | 2026-07-14 |
| 决策者 | taotao |

## 背景
后端需要异步IO（LLM调用、Agent执行）、自动API文档、类型安全。

## 候选方案
- **A: FastAPI**（已选）：原生async/await，Pydantic v2校验，OpenAPI自动生成，WebSocket支持
- **B: Django+DRF**：太重，异步支持弱，不适合Agent-to-API模式
- **C: Flask**：需额外插件，无自动文档

## 决策
选A。全链路异步配合SQLAlchemy async，Agent可直读OpenAPI文档。

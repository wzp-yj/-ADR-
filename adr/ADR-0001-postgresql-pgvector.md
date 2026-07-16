# ADR-0001: PostgreSQL + pgvector

| 字段 | 内容 |
|------|------|
| 状态 | 已采纳 |
| 决策日期 | 2026-07-14 |
| 决策者 | taotao |

## 背景
AIOS 需要结构化数据（项目、对话、任务）+ 向量数据（记忆检索、灵感相似度）。

## 候选方案
- **A: PostgreSQL + pgvector**（已选）：一套DB同时满足事务和向量，运维简单，pgvector支持HNSW索引
- **B: PostgreSQL + Milvus**：专业向量DB，十亿级性能好，但运维两套DB
- **C: FAISS**：无持久化，无并发，不适合

## 决策
选A。V1百万级向量pgvector足够，保留抽象接口未来可切换Milvus。
切换时机：单表向量>500万且HNSW延迟>100ms。

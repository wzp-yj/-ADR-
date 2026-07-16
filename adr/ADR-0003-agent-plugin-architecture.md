# ADR-0003: Agent Plugin Architecture

| 字段 | 内容 |
|------|------|
| 状态 | 已采纳 |
| 决策日期 | 2026-07-15 |
| 决策者 | taotao |

## 背景
需接入多种Agent（Codex、Git、Shell、Test、Research），每种有独立执行逻辑和权限。架构需支持热插拔。

## 候选方案
- **A: Plugin模式**（已选）：AgentBase基类+Factory注册，plugins/目录下独立包，共享diff.py
- **B: 微服务+gRPC**：V3可升级，MVP阶段运维成本太高
- **C: 硬编码**：不可扩展

## 决策
选A。V1同进程运行，抽象层保留gRPC接口，Research Agent仅需2文件即可接入。

# ADR-0004: Execution Pipeline

| 字段 | 内容 |
|------|------|
| 状态 | 已采纳 |
| 决策日期 | 2026-07-15 |
| 决策者 | taotao |

## 背景
核心理念：AI不替用户做决定，所有执行需用户确认。需设计可追踪、可中断、可回滚的执行管线。

## 设计
```
用户输入 -> Cognitive Engine -> 判断意图
  -> (任务) Execution Pipeline
    -> Phase1: Agent生成草案 -> 展示diff -> 用户第一次确认
      -> Phase2: ChangeApplier执行 -> 展示结果 -> 用户第二次确认
```

## 为什么两次确认
- 草案说"我准备做什么"，执行是"我实际做了什么"——两件事
- ChangeApplier MODIFY优先write_text，git apply降级（Windows CRLF安全）
- 拒绝可回滚

## 后果
ExecutionTask状态机: draft -> draft_confirmed -> executing -> executed -> confirmed|rejected

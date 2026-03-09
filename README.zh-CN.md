<div align="center">

# 🦞 Claw Fact Bus

**一群半自治的小龙虾在共享水域里，根据闻到的"事实味道"行动。**

Created and Proposed by **Carter.Yang**

[English](README.md)

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-84%20passed-brightgreen.svg)](#开发)

</div>

---

## 水族箱：从"死板工作流"到"自组织生态"

想象你在机房部署了 20 个强大的 AI Agent（我们称之为 **Claw**）。

在传统模式下，你面临两个痛苦的选择：
1. **手动编排工作流**：你需要为每一个可能的场景预设 `If A then B then C` 的逻辑。一旦场景稍微变化，整个工作流就失效了。
2. **手动触发动作**：你像个忙碌的接线员，不停地问 A："现在情况如何？"，然后告诉 B："你去把那个修了"。

**这太死板了。AI 不应该是听令行事的提线木偶，而应该是水族箱里的小龙虾。**

### 龙虾的自响应模式

在 **Claw Fact Bus** 的世界里，机房变成了一个珊瑚礁水族箱。

没有总指挥，没有预设的死板脚本。取而代之的是，**事实（Fact）像气味一样在水流（Bus）中漂散**。每只小龙虾根据自己的本能（过滤器）对特定的气味做出反应。

```
                    🌊 Fact Bus（共享水流）
    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
    
    🦞 monitor 监控虾    → 嗅到：延迟飙升（环境变化）
                          → 吐出：incident.latency.high（发布事实）
    
    🦞 analyzer 分析虾   → 嗅到：incident.*（自发响应）
                          → 吐出：db.query.slow（产生新事实）
    
    🦞 db-expert 数据库虾 → 嗅到：db.*（自发响应）
                          → 吐出：db.index.recommendation
    
    🦞 fixer 修复虾      → 嗅到：*.recommendation（自发响应）
                          → 吐出：change.proposed
    
    🦞 approver 审批虾   → 嗅到：change.proposed（自发响应）
                          → 吐出：change.approved
    
    🦞 deployer 部署虾   → 嗅到：change.approved（自发响应）
                          → 吐出：db.index.created
    
    🦞 monitor 监控虾    → 嗅到：延迟恢复正常 ✅

    ╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
    没有编排器，没有人为干预。事实在流动，龙虾在行动。一场事故自发地解决了。
```

---

## 构思与解决的问题

### 核心构思：事实驱动，而非指令驱动

传统的 AI 协作往往试图模仿人类的**命令链**（Command Chain）。但 AI Agent 的真正威力在于其**感知与推理**。

Fact Bus 的构思是将协作降维到最纯粹的形式：**信息的广播与自发的局部响应**。这借鉴了汽车工业中极其可靠的 **CAN Bus** 协议：每个传感器只管往总线上扔数据，每个执行器自己决定听哪些数据。

### 解决的痛点

1. **摆脱"编排地狱"**：
   你不再需要维护复杂的 DAG 图或状态机。工作流不是"设计"出来的，而是通过事实的因果链条"涌现"出来的。增加一个新功能，只需投入一只新龙虾，无需修改现有逻辑。

2. **从"询问"到"感知"**：
   Agent 不再等待被调用（Polling/Triggering），而是持续感知（Sensing）。这让系统从"被动响应"转变为"主动协作"。

3. **极高的鲁棒性（去中心化）**：
   如果水族箱里的一只分析虾生病了（宕机），只要还有其他能闻到同样气味的虾，生态系统就能继续运转。没有单点故障，没有中央瓶颈。

4. **知识的演化与共识**：
   通过 v2 协议的 `corroborate`（佐证）和 `contradict`（反驳），多只龙虾可以对同一个事实进行博弈，最终形成**共识**。这解决了 AI 幻觉和不可信输出的问题。

---

## 协议设计

### Fact — 不可变记录 + 可变总线状态

总线上的每个事实有两个结构区域：

```
┌─────────────────────────────────────────────────────────────┐
│              不可变记录区（气味本身）                           │
│           发布后冻结 · 由 content_hash 覆盖                   │
├─────────────────────────────────────────────────────────────┤
│  fact_id          唯一标识                                    │
│  fact_type        点分类命名 (code.review.needed)            │
│  payload          业务数据 {}                                 │
│  source_claw_id   发布者                                     │
│  created_at       Unix 时间戳                                │
│  mode             broadcast / exclusive                      │
│  priority         优先级 (0-7, CAN 风格, 越小越高)           │
│  ttl_seconds      存活时间                                    │
│  parent_fact_id   直接因果父节点（可选）                       │
│  causation_depth  因果链深度 (0 = 根事实)                    │
│  confidence       发布者自评可信度 [0.0, 1.0]                 │
│  content_hash     SHA-256(payload)                           │
│  domain_tags      领域标签（可选）                             │
│  need_capabilities 能力需求（可选）                            │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ 扩展字段 ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ │
│  semantic_kind    语义类型 (observation/request/...)          │
│  subject_key      主题键（同一对象的连续观察）                  │
│  supersedes       显式替代的 fact_id                          │
├─────────────────────────────────────────────────────────────┤
│              可变总线状态区（总线的评估）                       │
│              由引擎独占管理                                    │
├─────────────────────────────────────────────────────────────┤
│  state            工作流状态 (published/claimed/resolved)     │
│  claimed_by       认领者 claw_id (exclusive 模式)            │
│  resolved_at      完成时间戳                                  │
│  corroborations   佐证者列表                                  │
│  contradictions   反驳者列表                                  │
│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ 扩展字段 ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ │
│  epistemic_state  真值状态 (asserted/corroborated/...)       │
│  superseded_by    被哪个新 fact 替代                          │
└─────────────────────────────────────────────────────────────┘
```

**核心约束：已发布的 fact 内容永远不变。只有总线对它的评估在演化。**

### 双状态机

每个 fact 上运行两个正交的生命周期：

```
WorkflowState（任务流转 — 核心协议 §5.1）:
  PUBLISHED ──→ CLAIMED ──→ RESOLVED
       │            │
       └───→ DEAD ←─┘

EpistemicState（真值生命周期 — 扩展 1）:
  ASSERTED → CORROBORATED → CONSENSUS
      │            │
      └→ CONTESTED → REFUTED
              │
              └→ SUPERSEDED
```

一个 fact 可以是 `workflow=CLAIMED + epistemic=CONTESTED`——有人在处理它，但前提已经被质疑了。这两个维度是设计上独立的。

### SemanticKind（语义分类）

总线上不是所有东西都是原始观察。`semantic_kind` 字段标注一个 fact 在认知上*意味着*什么：

| Kind | 含义 | 示例 |
|------|------|------|
| `observation` | 直接感知到的事实 | build.failed, cpu.high |
| `assertion` | 推断或判断 | root_cause.suspected |
| `request` | 行动请求 | review.needed, deploy.requested |
| `resolution` | 处理结果 | review.completed |
| `correction` | 替代先前的 fact | 更新的诊断 |
| `signal` | 即发即弃的状态信号 | heartbeat, progress.60pct |

### Supersede（知识演化）

关于同一主题的事实会自然演化。新的温度读数替代旧的：

```json
{
  "fact_type": "env.temperature",
  "subject_key": "host:web-01/cpu-temp",
  "payload": { "celsius": 72 },
  "semantic_kind": "observation"
}
```

当新 fact 拥有相同的 `subject_key + fact_type` 时，总线自动：
1. 在旧 fact 上设置 `superseded_by`
2. 将旧 fact 的 `epistemic_state` 转为 `SUPERSEDED`
3. 向订阅者推送 `FACT_SUPERSEDED` 事件

也可以通过设置 `supersedes` 字段显式指定替代目标。

### 社会验证

其他 claw 可以为 fact 背书或质疑：

```
corroborate(fact_id, claw_id)  →  fact.corroborations 增长
                                →  可能达到 CONSENSUS

contradict(fact_id, claw_id)   →  fact.contradictions 增长
                                →  可能达到 REFUTED
```

消费者通过过滤器筛选信任：`min_epistemic_rank`、`min_confidence`、`exclude_superseded`。

### 内容完整性

每个发布到总线的 fact 都经过完整性管道：

1. **Hash** — `content_hash = SHA-256(规范化 payload)`
2. **验证** — 总线检查 hash 是否匹配
3. **签名** — 总线盖章 `signature = HMAC-SHA256(bus_secret, fact_id|hash|source|type|time)`

签名证明：*这个 fact 已被本总线实例验证并接受*。

---

## 快速开始

### 本地运行

```bash
pip install -e ".[dev]"
python -m claw_fact_bus.server.main
# → http://localhost:8080/docs
```

### Docker Compose

```bash
docker-compose up -d
open http://localhost:8080/docs
```

---

## API 使用示例

### 1. 孵化一只 Claw

```bash
curl -X POST http://localhost:8080/claws/connect \
  -H "Content-Type: application/json" \
  -d '{
    "name": "code-reviewer",
    "description": "审查 Python 代码的安全问题",
    "capability_offer": ["review", "python", "security"],
    "domain_interests": ["python", "auth"],
    "fact_type_patterns": ["code.*.needed"]
  }'
```

响应包含 `claw_id` 和 `token`（后续请求需携带）。

### 2. 吐出一个 Fact

```bash
curl -X POST http://localhost:8080/facts \
  -H "Content-Type: application/json" \
  -d '{
    "fact_type": "code.review.needed",
    "semantic_kind": "request",
    "payload": {"file": "auth.py", "pr": 42},
    "domain_tags": ["python", "auth"],
    "need_capabilities": ["review", "security"],
    "priority": 1,
    "mode": "exclusive",
    "source_claw_id": "YOUR_CLAW_ID",
    "token": "YOUR_TOKEN",
    "subject_key": "pr:42/review",
    "confidence": 0.95
  }'
```

### 3. 抓住 → 消化完成

```bash
# 认领
curl -X POST http://localhost:8080/facts/{fact_id}/claim \
  -d '{"claw_id": "YOUR_CLAW_ID", "token": "YOUR_TOKEN"}'

# 完成，吐出子 fact
curl -X POST http://localhost:8080/facts/{fact_id}/resolve \
  -d '{
    "claw_id": "YOUR_CLAW_ID",
    "token": "YOUR_TOKEN",
    "result_facts": [{
      "fact_type": "code.review.completed",
      "payload": {"file": "auth.py", "issues": 2}
    }]
  }'
```

### 4. 社会验证

```bash
# 佐证
curl -X POST http://localhost:8080/facts/{fact_id}/corroborate \
  -d '{"claw_id": "ANOTHER_CLAW"}'
# → {"success": true, "epistemic_state": "corroborated"}

# 反驳
curl -X POST http://localhost:8080/facts/{fact_id}/contradict \
  -d '{"claw_id": "ANOTHER_CLAW"}'
# → {"success": true, "epistemic_state": "contested"}
```

### 5. WebSocket — 活在水流里

```python
import asyncio, json, websockets

async def claw_life():
    async with websockets.connect("ws://localhost:8080/ws/reviewer-001") as ws:
        await ws.send(json.dumps({
            "action": "subscribe",
            "name": "code-reviewer",
            "filter": {
                "capability_offer": ["review", "python"],
                "fact_type_patterns": ["code.*.needed"],
                "semantic_kinds": ["request", "observation"],
                "min_epistemic_rank": 0,
                "exclude_superseded": True
            }
        }))

        while True:
            event = json.loads(await ws.recv())
            match event["event_type"]:
                case "fact_available":
                    print(f"🦞 嗅到: {event['fact']['fact_type']}")
                case "fact_trust_changed":
                    print(f"🌊 信任变化: {event['detail']}")
                case "fact_superseded":
                    print(f"♻️  被替代: {event['fact']['fact_id']}")
```

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                   🦞 Claw Fact Bus Server                     │
├──────────────────────────────────────────────────────────────┤
│  FastAPI                                                      │
│  ├── REST API  /facts  /claws  /schemas                      │
│  └── WebSocket /ws/{claw_id}                                 │
├──────────────────────────────────────────────────────────────┤
│  Bus Engine                                                   │
│  ├── 内容完整性     (hash 验证 + HMAC 签名)                   │
│  ├── 双状态机       (workflow × epistemic)                    │
│  ├── Supersede 索引 (subject_key → 最新 fact)                │
│  ├── 发布闸门       (5 道流控防线)                             │
│  ├── 过滤引擎       (CAN 风格 + 语义 + 认知)                 │
│  ├── 仲裁           (exclusive fact 胜者选择)                 │
│  ├── 可靠性管理     (CAN 风格 TEC/REC 故障隔离)              │
│  └── 事件分发       (WebSocket 推送 + 信任事件)              │
├──────────────────────────────────────────────────────────────┤
│  Schema Registry                                              │
│  ├── OPEN / WARN / STRICT 执行模式                           │
│  └── Schema 演化校验                                          │
├──────────────────────────────────────────────────────────────┤
│  持久化                                                       │
│  └── JSONL Fact Store（仅追加、压缩、恢复）                   │
└──────────────────────────────────────────────────────────────┘
```

### 流控与故障隔离

| 机制 | 作用 | CAN Bus 类比 |
|------|------|-------------|
| 因果链深度限制 (16层) | 防止级联爆炸 | 消息长度限制 |
| 因果链环路检测 | 防止活锁 | 错误界定 |
| 令牌桶限流 (20/5s) | 单 claw 流量控制 | 发送缓冲区 |
| 全局负载熔断 (200/5s) | 总线过载保护 | 过载帧 |
| 优先级老化 (每30s) | 防止饥饿 | 优先级仲裁 |
| 去重窗口 (10s) | 抑制重复发布 | 错误计数 |
| TEC/REC 错误计数器 | 可靠性评分 + 节点隔离 | TEC/REC |
| 内容 hash 验证 | 防篡改 | CRC 校验 |
| 总线 HMAC 签名 | 权威背书 | ACK 位 |

---

## API 参考

### HTTP 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/stats` | 统计信息（含 epistemic 分布）|
| POST | `/claws/connect` | 注册 claw（返回 token）|
| GET | `/claws` | 列出所有 claw |
| POST | `/claws/{id}/heartbeat` | 心跳 |
| POST | `/facts` | 发布 fact |
| GET | `/facts` | 查询 facts |
| GET | `/facts/{id}` | 获取单个 fact |
| POST | `/facts/{id}/claim` | 认领 exclusive fact |
| POST | `/facts/{id}/release` | 释放 claimed fact |
| POST | `/facts/{id}/resolve` | 完成 fact |
| POST | `/facts/{id}/corroborate` | 佐证（返回新 epistemic_state）|
| POST | `/facts/{id}/contradict` | 反驳（返回新 epistemic_state）|

### WebSocket 事件

| 事件 | 说明 |
|------|------|
| `fact_available` | 新 fact 匹配了你的过滤器 |
| `fact_claimed` | 一个 fact 被认领了 |
| `fact_resolved` | 一个 fact 被完成了 |
| `fact_expired` | TTL 超时 |
| `fact_dead` | 进入死信区 |
| `fact_superseded` | 被更新的 fact 替代了 |
| `fact_trust_changed` | 认知状态发生了变化 |
| `claw_state_changed` | claw 可靠性状态变化 |

---

## 配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `FACT_BUS_DATA_DIR` | `.data` | 数据目录 |
| `FACT_BUS_HOST` | `0.0.0.0` | 监听地址 |
| `FACT_BUS_PORT` | `8080` | 端口 |
| `FACT_BUS_SECRET` | 随机生成 | HMAC 签名密钥 |
| `FACT_BUS_ADMIN_KEY` | 空 | 管理端点密钥 |

---

## 开发

```bash
pip install -e ".[dev]"
pytest                  # 84 tests
ruff check src/
```

---

## 术语表

> 因为隐喻就是架构。

| 术语 | 含义 |
|------|------|
| **Claw** 🦞 | 总线上的一个自治代理节点（小龙虾）|
| **Fact** | 在水流中漂散的不可变气味 |
| **Bus** 🌊 | 承载所有事实的共享水流 |
| **Reef** 🪸 | claw 集群形成的生态系统（珊瑚礁）|
| **Filter** | claw 的感官——它对什么气味有反应 |
| **Claim** | claw 抓住一个 exclusive 气味 |
| **Supersede** | 新气味替代了关于同一主题的旧气味 |
| **Corroborate** | 另一只 claw 确认："我也闻到了" |
| **Contradict** | 另一只 claw 质疑："我闻到的不一样" |

---

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE) — 免费用于非商业用途。

---

**架构主权声明 (Architecture Sovereignty Notice):**
"小龙虾水族箱"隐喻、双状态机 (Workflow x Epistemic) 以及基于事实的自主协作的具体实现，均为 **Carter.Yang** 的原创知识产权。任何对本协议的衍生作品或在其他语言/框架中的重新实现，必须明确引用原始的 "Claw Fact Bus" 规范及其创作者。

---

<div align="center">

*没有编排器。没有命令链。只有水中的事实，和做小龙虾该做的事的小龙虾。* 🦞

</div>

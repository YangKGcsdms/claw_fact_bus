# OpenClaw Fact Bus Plugin — 技术设计文档

## 1. 目标

让 OpenClaw 实例能够：
- **感知** Fact Bus 上流动的事实
- **处理** 自己关注的事实，产生新事实
- **叠加** 因果链，驱动多个 OpenClaw 实例协同演化知识

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenClaw Gateway                          │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              extensions/fact-bus/                      │  │
│  │                                                       │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │  │
│  │  │  Service     │  │   Tools      │  │   Hooks     │  │  │
│  │  │  (管道层)    │  │  (交互层)     │  │  (自动化层)  │  │  │
│  │  │             │  │              │  │             │  │  │
│  │  │ WS 连接     │  │ fact_bus_*   │  │ message_    │  │  │
│  │  │ 事实缓存    │  │ publish      │  │ sending →   │  │  │
│  │  │ 心跳保活    │  │ query        │  │ 事实提取    │  │  │
│  │  │ 重连机制    │  │ claim        │  │             │  │  │
│  │  │             │  │ resolve      │  │             │  │  │
│  │  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  │  │
│  │         │                │                  │         │  │
│  │         └────────────────┼──────────────────┘         │  │
│  │                          │                            │  │
│  │                   ┌──────▼──────┐                     │  │
│  │                   │  Cron Job   │                     │  │
│  │                   │  (定时触发)  │                     │  │
│  │                   │  */5 * * * *│                     │  │
│  │                   └─────────────┘                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                          │                                  │
└──────────────────────────┼──────────────────────────────────┘
                           │ WebSocket
                    ┌──────▼──────┐
                    │  Fact Bus   │
                    │  Server     │
                    │  :8080      │
                    └─────────────┘
```

## 3. 三层职责划分

### 3.1 Service 层（管道层）— `src/service.ts`

**职责**：维持与 Fact Bus Server 的 WebSocket 连接，缓存收到的事实。

**核心组件**：

```typescript
// WebSocket 客户端，带自动重连
class FactBusConnection {
  private ws: WebSocket | null;
  private abortController: AbortController;
  private reconnectAttempts: number;

  async connect(clawId: string, busUrl: string): Promise<void>;
  async disconnect(): Promise<void>;
  async publish(fact: Fact): Promise<PublishResult>;
  async claim(factId: string): Promise<ClaimResult>;
  async resolve(factId: string, ...): Promise<void>;
  async corroborate(factId: string): Promise<void>;
  async contradict(factId: string): Promise<void>;
  onFact(callback: (fact: Fact) => void): void;
}

// 事实缓存，供 tool 层读取
class FactCache {
  private pending: Map<string, Fact>;      // 待处理事实
  private processing: Map<string, Fact>;   // 正在处理
  private resolved: Fact[];                 // 已完成（滑动窗口）

  push(fact: Fact): void;
  takeNext(filter?: AcceptanceFilter): Fact | null;
  markProcessing(factId: string): void;
  markResolved(factId: string): void;
  query(filter?: AcceptanceFilter): Fact[];
}
```

**生命周期**：

```
gateway_start → service.start()
  → 创建 AbortController
  → 读取配置 (busUrl, clawId, capabilities, ...)
  → 连接 WebSocket (/ws/{clawId})
  → 注册 onMessage → push 到 FactCache
  → 启动心跳定时器 (30s)

gateway_stop → service.stop()
  → abort heartbeat
  → ws.close()
```

**重连策略**：指数退避，1s → 2s → 4s → 8s → max 30s。参考 Mattermost `monitor-websocket.ts` 的 `runWithReconnect` 模式。

### 3.2 Tool 层（交互层）— `src/tools.ts`

**职责**：提供 agent 在 session 中可调用的事实操作工具。

**注册的工具**：

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `fact_bus_query` | 查看 bus 上的事实 | `state?`, `semantic_kind?`, `fact_type?`, `domain_tags?`, `limit?` |
| `fact_bus_publish` | 发布新事实 | `fact_type`, `semantic_kind`, `payload`, `domain_tags?`, `priority?`, `mode?`, `supersedes?`, `subject_key?` |
| `fact_bus_claim` | 认领一个 EXCLUSIVE 事实 | `fact_id` |
| `fact_bus_resolve` | 完成事实处理 | `fact_id`, `resolution_payload?`, `publish_children?` |
| `fact_bus_corroborate` | 确认他人事实 | `fact_id`, `confidence?` |
| `fact_bus_contradict` | 质疑他人事实 | `fact_id`, `reason` |

**Tool 实现模式**（以 `fact_bus_publish` 为例）：

```typescript
// tools.ts
import { definePluginTool } from "openclaw/plugin-sdk/plugin-tool";
import { z } from "zod";

export function createFactBusPublishTool(conn: FactBusConnection) {
  return definePluginTool({
    name: "fact_bus_publish",
    description: "Publish a new fact to the Fact Bus",
    inputSchema: z.object({
      fact_type: z.string(),
      semantic_kind: z.enum(["OBSERVATION", "ASSERTION", "REQUEST", "RESOLUTION", "CORRECTION", "SIGNAL"]),
      payload: z.record(z.unknown()),
      domain_tags: z.array(z.string()).optional(),
      priority: z.number().min(0).max(7).optional(),
      mode: z.enum(["BROADCAST", "EXCLUSIVE"]).optional(),
      supersedes: z.string().optional(),
      subject_key: z.string().optional(),
    }),
    execute: async (input, ctx) => {
      // ctx.sessionKey 可用 → 记录映射关系
      const result = await conn.publish({
        fact_type: input.fact_type,
        semantic_kind: input.semantic_kind,
        payload: input.payload,
        domain_tags: input.domain_tags ?? [],
        priority: input.priority ?? 5,
        mode: input.mode ?? "BROADCAST",
        supersedes: input.supersedes,
        subject_key: input.subject_key,
      });
      return { fact_id: result.fact_id, state: "PUBLISHED" };
    },
  });
}
```

**关键设计**：每次 tool 调用通过 `ctx.sessionKey` 获取当前 session。插件维护一个 `sessionKey ↔ clawId` 映射表，这样当 Service 收到总线事件时，可以知道应该通知哪些 session。

### 3.3 Hook 层（自动化层）— `src/hooks.ts`

**职责**：自动从 agent 对话中提取事实并发布到总线。

**注册的 hook**：

```typescript
// hooks.ts

// 1. 消息发送 hook — 从 agent 回复中提取事实
api.registerHook("message_sending", async (context) => {
  const { message, sessionKey } = context;

  // 启发式提取：检测回复中是否包含事实性陈述
  // 触发条件（满足任一）：
  // - 包含 "发现"、"确认"、"检测到"、"存在" 等关键词
  // - 包含结构化信息（URL、版本号、错误码）
  // - agent 在回复中调用了 fact_bus_publish tool（已有 tool 处理，跳过）

  const extracted = extractFactsFromText(message.content);
  for (const fact of extracted) {
    await conn.publish({
      fact_type: fact.type,
      semantic_kind: "OBSERVATION",
      payload: { text: fact.text, context: message.content.slice(0, 200) },
      domain_tags: fact.tags,
      priority: 5,
      mode: "BROADCAST",
    });
  }
  // hook 不修改 message，纯旁路
});

// 2. gateway_start — 注册 cron job + 连接 bus
api.registerHook("gateway_start", async (context) => {
  // 启动 WS 连接
  await service.start(context);

  // 注册 cron job：每 5 分钟检查 bus 上的新事实
  // 方式：通过 gateway RPC 调用 cron.add
  // （见第 4 节 Cron 集成详细设计）
});
```

## 4. Cron 集成详细设计

### 4.1 为什么需要 Cron

问题：用户不说话时，agent 不会被触发。Fact Bus 上可能有重要事实（如安全漏洞 OBSERVATION），agent 无法感知。

### 4.2 Cron Job 设计

插件在 `gateway_start` 时注册一个 cron job：

```typescript
// 通过 gateway RPC 创建 cron job
async function registerFactBusCron(api: OpenClawPluginApi) {
  const job = {
    name: "fact-bus-poll",
    description: "Poll Fact Bus for new relevant facts",
    enabled: true,
    schedule: { kind: "every", everyMs: 5 * 60 * 1000 }, // 每 5 分钟
    sessionTarget: "isolated" as const,
    wakeMode: "none" as const,  // 不需要立即触发
    payload: {
      kind: "agentTurn" as const,
      message: [
        "Check the Fact Bus for pending facts and process them.",
        "",
        "Steps:",
        "1. Use fact_bus_query to see pending facts matching your filters",
        "2. For each relevant fact:",
        "   - If REQUEST/EXCLUSIVE: fact_bus_claim then fact_bus_resolve",
        "   - If OBSERVATION: evaluate and fact_bus_corroborate or fact_bus_contradict",
        "   - If CORRECTION about your previous fact: fact_bus_corroborate",
        "3. If you discover new facts during processing: fact_bus_publish",
        "4. If no pending facts, do nothing.",
      ].join("\n"),
    },
    delivery: { kind: "none" as const },  // 结果留在 session 内
  };

  // 通过 gateway RPC 调用
  // 插件在 gateway_start 时可通过 context 获得 gateway method 调用能力
  await api.callGatewayMethod("cron.add", job);
}
```

### 4.3 Cron 触发流程

```
定时器触发 (每 5 分钟)
  → OpenClaw cron engine 创建 isolated session
  → agentTurn message: "Check the Fact Bus..."
  → agent 调用 fact_bus_query tool
    → tool 内部从 Service.FactCache 读取缓存
    → 返回 pending facts
  → agent 根据 message 决定操作
    → fact_bus_claim → fact_bus_resolve
    → fact_bus_corroborate / contradict
    → fact_bus_publish（新事实）
  → 处理完成，session 记录所有操作
  → delivery: "none" → 结果留在 isolated session
```

### 4.4 Cron vs 用户交互的协作

| 场景 | 触发方式 | session 类型 |
|------|---------|-------------|
| 用户问 "bus 上有什么新事实" | 用户消息 | 用户 session（main） |
| 用户说 "处理一下这个事实" | 用户消息 + tool 调用 | 用户 session |
| 无人值守自动处理 | cron job | isolated session |
| 重要事实需要通知用户 | cron 处理后 → enqueueSystemEvent | 用户 session |

**Cron → 用户 session 的桥接**：

当 cron isolated session 中 agent 处理了一个高优先级事实（priority <= 1 即 CRITICAL/HIGH），可以通过 `enqueueSystemEvent` 将结果注入用户 main session：

```typescript
// 在 fact_bus_resolve tool 实现中
if (resolvedFact.priority <= 1) {
  // 注入到用户主 session
  runtime.system.enqueueSystemEvent(
    `[Fact Bus] 高优先级事实已处理: ${resolvedFact.fact_type} - ${JSON.stringify(resolvedFact.resolution_payload)}`,
    { sessionKey: "main-session-key" }  // 需要从配置读取
  );
  runtime.system.requestHeartbeatNow();
}
```

## 5. 插件注册总览

```typescript
// index.ts
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { createFactBusService } from "./src/service.js";
import { createFactBusTools } from "./src/tools.js";
import { registerFactBusHooks } from "./src/hooks.js";

export default definePluginEntry({
  id: "fact-bus",
  name: "Fact Bus",
  description: "Connect OpenClaw to a Claw Fact Bus for multi-agent collaboration via facts",
  register(api) {
    // 1. 注册后台服务（WS 连接 + 事实缓存）
    const service = createFactBusService(api);
    api.registerService(service);

    // 2. 注册工具（agent 可调用的事实操作）
    for (const tool of createFactBusTools(service.getConnection())) {
      api.registerTool(tool);
    }

    // 3. 注册钩子（自动事实提取 + cron 注册）
    registerFactBusHooks(api, service);
  },
});
```

## 6. 配置

```jsonc
// openclaw.plugin.json
{
  "id": "fact-bus",
  "name": "Fact Bus",
  "configSchema": {
    "type": "object",
    "properties": {
      "busUrl": {
        "type": "string",
        "default": "http://localhost:8080",
        "description": "Fact Bus server URL"
      },
      "clawName": {
        "type": "string",
        "description": "This claw's identity name on the bus"
      },
      "capabilities": {
        "type": "array",
        "items": { "type": "string" },
        "default": [],
        "description": "Capabilities this claw declares (e.g. ['code-review', 'web-search'])"
      },
      "domainInterests": {
        "type": "array",
        "items": { "type": "string" },
        "default": [],
        "description": "Domain tags this claw is interested in"
      },
      "factTypePatterns": {
        "type": "array",
        "items": { "type": "string" },
        "default": ["*"],
        "description": "Fact type patterns to subscribe to"
      },
      "cronIntervalMs": {
        "type": "number",
        "default": 300000,
        "description": "Cron poll interval in ms (default 5 min)"
      },
      "mainSessionKey": {
        "type": "string",
        "description": "Main session key for high-priority fact injection (optional)"
      },
      "priorityThreshold": {
        "type": "number",
        "default": 1,
        "description": "Facts with priority <= this value get injected into main session"
      },
      "heartbeatIntervalMs": {
        "type": "number",
        "default": 30000,
        "description": "Heartbeat interval to Fact Bus server"
      }
    },
    "required": ["busUrl", "clawName"]
  },
  "enabledByDefault": false
}
```

## 7. 文件结构

```
extensions/fact-bus/
  openclaw.plugin.json          # 插件清单 + 配置 schema
  package.json                  # 依赖 (ws)
  index.ts                      # definePluginEntry 入口
  src/
    service.ts                  # WS 连接生命周期 + FactBusConnection + FactCache
    tools.ts                    # 6 个 registerTool
    hooks.ts                    # message_sending hook + gateway_start hook (cron 注册)
    types.ts                    # Fact, ClawIdentity, AcceptanceFilter 等类型定义
    extract.ts                  # 启发式事实提取逻辑（hooks.ts 调用）
    config.ts                   # 配置读取 + 校验
```

## 8. package.json

```json
{
  "name": "@openclaw/fact-bus",
  "version": "0.1.0",
  "type": "module",
  "main": "index.ts",
  "dependencies": {
    "ws": "^8.18.0"
  },
  "devDependencies": {
    "openclaw": "workspace:*",
    "@types/ws": "^8.5.13"
  },
  "openclaw": {
    "extensions": ["index.ts"],
    "channel": {
      "id": "fact-bus",
      "label": "Fact Bus"
    }
  }
}
```

## 9. 数据流示例：完整生命周期

```
1. OpenClaw-A 启动
   → gateway_start hook → 连接 Fact Bus WS → 注册 cron job
   → POST /claws/connect { capabilities: ["code-review"] }

2. 用户对 OpenClaw-A 说 "帮我看看这个 PR"
   → Agent 处理，发现代码有问题
   → Agent 调用 fact_bus_publish:
     { fact_type: "code.review.needed", semantic_kind: "REQUEST",
       payload: { pr_url: "...", issue: "..." }, mode: "EXCLUSIVE" }
   → Fact 进入 bus，dispatch 到匹配的 claw

3. Cron 触发 OpenClaw-B (每 5 分钟)
   → Agent 调用 fact_bus_query → 看到 code.review.needed fact
   → Agent 调用 fact_bus_claim → 拿到事实
   → Agent 处理（审查代码）
   → Agent 调用 fact_bus_resolve:
     { resolution_payload: { review: "...", approved: false } }
   → Agent 调用 fact_bus_publish:
     { fact_type: "code.issue.found", semantic_kind: "OBSERVATION",
       payload: { ... }, subject_key: "pr-123" }

4. OpenClaw-C (安全专家) 的 cron 也触发
   → fact_bus_query → 看到 code.issue.found (domain_tags: ["security"])
   → fact_bus_corroborate (确认问题存在)
   → fact_bus_publish:
     { fact_type: "security.vulnerability", semantic_kind: "OBSERVATION",
       payload: { severity: "high", ... }, priority: 0 }

5. 优先级 0 → 注入 OpenClaw-A 的 main session
   → enqueueSystemEvent("[Fact Bus] CRITICAL: security vulnerability detected...")
   → requestHeartbeatNow() → Agent 立即响应用户

6. 认识论演化:
   - OpenClaw-B 发布 ASSERTED fact → ASSERTED
   - OpenClaw-C corroborate → CORROBORATED
   - OpenClaw-D 也 corroborate → CONSENSUS
   - OpenClaw-E contradict → CONTESTED
   - OpenClaw-B 发布 supersedes → 旧 fact → SUPERSEDED
```

## 10. 实施步骤

### Phase 1: 基础管道（1-2 天）
1. 创建 `extensions/fact-bus/` 目录结构
2. 实现 `types.ts` — 从 claw_fact_bus types.py 移植核心类型
3. 实现 `config.ts` — 配置读取
4. 实现 `service.ts` — WS 连接 + FactCache（参考 Mattermost monitor-websocket.ts）
5. 实现 `index.ts` — 最小化 registerService
6. 测试：gateway 启动后能连接 Fact Bus Server

### Phase 2: 工具层（1 天）
7. 实现 `tools.ts` — 6 个 tool（参考 voice-call registerTool 模式）
8. 测试：用户 session 中能调用 fact_bus_query/publish

### Phase 3: Cron 集成（1 天）
9. 实现 `hooks.ts` — gateway_start 中注册 cron job
10. 测试：cron 定时触发 → agent 自动查询并处理事实

### Phase 4: 自动化（1 天）
11. 实现 `extract.ts` — 启发式事实提取
12. 实现 hooks 中 message_sending 的自动发布
13. 测试：agent 回复中的事实性内容自动发布到 bus

### Phase 5: 优先级桥接（半天）
14. 实现高优先级事实 → main session 注入
15. 测试：critical 事实触发用户 session 的 agent 响应

## 11. 关键约束和注意事项

1. **Cron 的 sessionTarget 选择**：
   - 用 `"isolated"` — 独立 session，不影响用户对话
   - 不用 `"main"` — main 只支持 systemEvent payload，不能运行完整 agent turn

2. **Service 没有 sessionKey**：
   - Service 本身不能注入 session
   - 解决：Tool 有 sessionKey → Tool 内部做注入
   - Cron isolated session → Tool 内部通过配置的 mainSessionKey 注入

3. **subagent.run 在 Service 中不可用**：
   - `runtime.subagent` 只在 gateway request context 中可用
   - 后台 Service 调用会报 "unavailable"
   - 解决：用 cron 替代 — cron engine 自己管理 agent turn 生命周期

4. **事实缓存是进程内**：
   - 重启后丢失。如果需要持久化，Service 可在 start 时从 Fact Bus Server 拉取最近事实重建缓存
   - API: `GET /facts?state=PUBLISHED&limit=100`

5. **幂等性**：
   - publish 时带 `content_hash`，bus engine 自动去重
   - claim 时 bus engine 保证 EXCLUSIVE 唯一性
   - 已处理的 fact_id 记录在 session store 中，避免重复处理

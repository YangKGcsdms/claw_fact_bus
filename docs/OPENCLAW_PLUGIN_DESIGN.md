# Claw Fact Bus — OpenClaw 插件技术方案

## 1. 背景

### 1.1 问题

Claw Fact Bus 是一个 CAN-Bus 风格的多 Agent 协调系统。Agent 之间通过 **Fact（事实）** 进行通信：

- 事实有生命周期：`CREATED → PUBLISHED → MATCHED → CLAIMED → RESOLVED`
- 事实有认知状态：`ASSERTED → CORROBORATED → CONSENSUS / CONTESTED → REFUTED / SUPERSEDED`
- 事实之间有因果链（`causation_chain`）

目前与 Bus 的交互方式是纯 HTTP 轮询（Python `requests` 库），由硬编码的 handler 函数驱动。这意味着：

1. **Agent 行为是脚本化的** — handler 写死逻辑，无法根据上下文动态决策
2. **缺乏语义理解** — 无法理解事实内容的含义，只能做模式匹配
3. **无法自主行动** — 必须用户手动触发，Agent 不能"像工位上的人一样"主动工作

### 1.2 目标

让 OpenClaw（LLM Agent 运行时）安装一个插件后，能够：

1. **主动感知** Bus 上流动的事实（无需用户每次手动触发）
2. **根据角色定义自主处理** — SKILL.md 定义角色、关注领域、处理规则
3. **三维度事实处理**：
   - 关注的事实（filter）：只处理匹配的 fact_type
   - 能产生的事实（capabilities）：能向 Bus 发布新事实
   - 因果链叠加：发布新事实时自动追加因果关系
4. **在用户 session 中自然工作** — 不需要独立的 Agent session

## 2. 为什么选择 OpenClaw Plugin

| 方案 | 优点 | 缺点 |
|------|------|------|
| Python 脚本轮询 | 简单，已有实现 | 无 LLM 能力，行为脚本化 |
| OpenClaw Skill（纯 SKILL.md） | 零代码 | 无法主动感知，只有用户说话时才触发 |
| **OpenClaw Plugin** | **后台轮询 + Hook 注入 + 工具调用 + 角色定义** | 需要 TypeScript 开发 |

OpenClaw Plugin 提供了三个关键能力：

1. **`registerService`** — 后台定时轮询 Bus，积累 facts 到内存 buffer
2. **`api.on("before_prompt_build")`** — 每次 LLM 回复前触发，将 buffer 中的 facts 注入到 prompt 中
3. **`registerTool`** — 让 LLM 能调用 `bus_claim`、`bus_publish`、`bus_resolve` 等工具

这三个能力组合起来，实现了"LLM 自主感知 + 自主行动"。

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  OpenClaw Runtime                                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  claw-fact-bus Plugin                               │    │
│  │                                                     │    │
│  │  ┌──────────────┐  ┌─────────────────────────────┐  │    │
│  │  │ Background    │  │ Tools                        │  │    │
│  │  │ Service       │  │                              │  │    │
│  │  │               │  │ - bus_connect (连接Bus)      │  │    │
│  │  │ setInterval   │  │ - bus_query (查询事实)       │  │    │
│  │  │ 每 8 秒       │  │ - bus_claim (认领事实)       │  │    │
│  │  │               │  │ - bus_publish (发布事实)     │  │    │
│  │  │ 轮询 Bus      │──▶ - bus_resolve (关闭事实)    │  │    │
│  │  │ GET /facts    │  │ - bus_corroborate (佐证)     │  │    │
│  │  │               │  │ - bus_contradict (反驳)      │  │    │
│  │  │ 过滤+去重     │  │                              │  │    │
│  │  │ → 写入 buffer │  └─────────────────────────────┘  │    │
│  │  └──────┬───────┘                                    │    │
│  │         │                                            │    │
│  │         ▼                                            │    │
│  │  ┌──────────────┐                                    │    │
│  │  │ Hook:         │                                    │    │
│  │  │ before_prompt │ 每个 LLM turn 前触发               │    │
│  │  │ _build        │ → drain buffer                    │    │
│  │  │               │ → 格式化为文本                     │    │
│  │  │               │ → prependContext 注入              │    │
│  │  └──────────────┘                                    │    │
│  │                                                     │    │
│  │  ┌──────────────┐                                    │    │
│  │  │ SKILL.md      │ 注入到系统 prompt                  │    │
│  │  │ "岗位说明书"   │ 定义角色/性格/SOP                 │    │
│  │  └──────────────┘                                    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌──────────────┐                                           │
│  │ LLM (用户    │  看到注入的事实 + 角色定义                  │
│  │  session)    │  自主决定 claim/publish/resolve            │
│  │              │  调用工具执行                               │
│  └──────────────┘                                           │
└─────────────────────────────┬───────────────────────────────┘
                              │ HTTP
                              ▼
┌─────────────────────────────────────────┐
│  Claw Fact Bus Server (FastAPI)         │
│                                         │
│  POST /claws/connect    (注册 Claw)     │
│  GET  /facts            (查询事实)      │
│  POST /facts            (发布事实)      │
│  POST /facts/{id}/claim (认领事实)      │
│  POST /facts/{id}/resolve (关闭事实)    │
│  POST /facts/{id}/corroborate           │
│  POST /facts/{id}/contradict            │
│  POST /claws/{id}/heartbeat             │
└─────────────────────────────────────────┘
```

### 3.2 数据流

```
时间轴 →

Service 轮询:    ──8s──▶ 轮询 ──8s──▶ 轮询 ──8s──▶ 轮询
                       GET /facts?state=published
Buffer 状态:    [ ]      [f1,f2]    [f3]       [f1,f3]
                                               (f2 已被 drain)

LLM 对话:       ──用户说话──▶ hook drain ──▶ LLM 看到 [f1,f2]
                              注入 prependContext
                 ──用户再说──▶ hook drain ──▶ LLM 看到 [f3]
```

### 3.3 Hook 注入机制

`before_prompt_build` hook 在 **每个 LLM 调用前** 触发：

```typescript
api.on("before_prompt_build", async (event, ctx) => {
  const pending = drainBuffer(); // 取出并清空 buffer
  if (pending.length === 0) return;

  return {
    prependContext: formatFactsAsPromptText(pending),
    // 这段文本会被拼接到用户 prompt 的前面
    // LLM 会看到类似：
    // [Fact Bus] 3 new facts available:
    // 1. [fact_type=ci.build.failed] "Build #1234 failed" (priority: HIGH)
    // 2. [fact_type=code.review.requested] "PR #56 needs review" (priority: NORMAL)
  };
});
```

关键约束：
- hook 返回 `prependContext` 时，文本会被拼接到**用户消息前面**（不是系统 prompt）
- hook 返回 `prependSystemContext` / `appendSystemContext` 时，文本会被拼接到**系统 prompt 前面/后面**
- 多个插件的 hook 结果会**拼接**（不是覆盖）

## 4. 实现目标

### 4.1 核心功能

| 功能 | 说明 |
|------|------|
| Bus 连接管理 | 插件启动时自动连接 Bus（或提供 bus_connect 工具） |
| 事实感知 | 后台轮询 + Hook 注入，LLM 自动看到新事实 |
| 事实过滤 | 按 config 中的 `factTypePatterns` 过滤，只注入匹配的事实 |
| 事实认领 | LLM 调用 `bus_claim` 工具 |
| 事实发布 | LLM 调用 `bus_publish` 工具，自动追加因果链 |
| 事实关闭 | LLM 调用 `bus_resolve` 工具 |
| 认知操作 | LLM 调用 `bus_corroborate` / `bus_contradict` |
| 角色定义 | SKILL.md 定义 Agent 的岗位、性格、处理 SOP |
| 心跳维护 | Service 自动发送 heartbeat 保持 Claw 在线 |

### 4.2 非目标（当前版本不做）

- WebSocket 实时推送（当前用 HTTP 轮询，简单可靠）
- 多 Bus 实例支持（先支持单 Bus）
- 事实持久化到磁盘（内存 buffer，重启后丢失是可接受的）
- 可视化仪表盘

## 5. 实现细节

### 5.1 插件目录结构

```
openclaw/extensions/claw-fact-bus/
├── index.ts                         # 插件入口
├── openclaw.plugin.json             # 插件元数据 + config schema
├── src/
│   ├── bus-client.ts                # HTTP 客户端（封装 Bus API）
│   ├── bus-service.ts               # 后台轮询 service
│   ├── bus-prompt-hook.ts           # before_prompt_build hook
│   ├── fact-buffer.ts               # 内存 buffer（去重 + 过滤）
│   └── tools/
│       ├── bus-connect.ts           # bus_connect
│       ├── bus-query.ts             # bus_query
│       ├── bus-claim.ts             # bus_claim
│       ├── bus-publish.ts           # bus_publish
│       ├── bus-resolve.ts           # bus_resolve
│       ├── bus-corroborate.ts       # bus_corroborate
│       └── bus-contradict.ts        # bus_contradict
└── skills/
    └── claw-fact-bus/
        └── SKILL.md                 # 岗位说明书
```

### 5.2 关键文件实现

#### 5.2.1 `index.ts` — 插件入口

```typescript
import { definePluginEntry, type AnyAgentTool } from "openclaw/plugin-sdk/plugin-entry";
import { createBusConnectTool } from "./src/tools/bus-connect.js";
import { createBusQueryTool } from "./src/tools/bus-query.js";
import { createBusClaimTool } from "./src/tools/bus-claim.js";
import { createBusPublishTool } from "./src/tools/bus-publish.js";
import { createBusResolveTool } from "./src/tools/bus-resolve.js";
import { createBusCorroborateTool } from "./src/tools/bus-corroborate.js";
import { createBusContradictTool } from "./src/tools/bus-contradict.js";
import { createBusService } from "./src/bus-service.js";
import { installBusPromptHook } from "./src/bus-prompt-hook.js";

export default definePluginEntry({
  id: "claw-fact-bus",
  name: "Claw Fact Bus",
  description: "Integrates OpenClaw agents with the Claw Fact Bus for multi-agent coordination",
  register(api) {
    // Register tools
    api.registerTool(createBusConnectTool(api) as AnyAgentTool);
    api.registerTool(createBusQueryTool(api) as AnyAgentTool);
    api.registerTool(createBusClaimTool(api) as AnyAgentTool);
    api.registerTool(createBusPublishTool(api) as AnyAgentTool);
    api.registerTool(createBusResolveTool(api) as AnyAgentTool);
    api.registerTool(createBusCorroborateTool(api) as AnyAgentTool);
    api.registerTool(createBusContradictTool(api) as AnyAgentTool);

    // Register background polling service
    api.registerService(createBusService(api));

    // Register prompt injection hook
    installBusPromptHook(api);
  },
});
```

#### 5.2.2 `openclaw.plugin.json` — 插件配置

```json
{
  "id": "claw-fact-bus",
  "skills": ["./skills"],
  "configSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "busUrl": {
        "type": "string",
        "description": "Claw Fact Bus server URL (e.g., http://localhost:8000)"
      },
      "clawName": {
        "type": "string",
        "description": "Display name for this claw on the bus"
      },
      "factTypePatterns": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Glob patterns for fact types to monitor (e.g., ['ci.*', 'code.review.*'])"
      },
      "pollIntervalMs": {
        "type": "number",
        "default": 8000,
        "description": "Polling interval in milliseconds"
      },
      "autoClaim": {
        "type": "boolean",
        "default": false,
        "description": "Auto-claim matching facts (vs waiting for LLM to claim)"
      }
    }
  }
}
```

#### 5.2.3 `bus-client.ts` — HTTP 客户端

```typescript
// 封装 Claw Fact Bus 的 HTTP API
// 参考 openclaw-skill/fact_bus_client.py 的实现

export class BusClient {
  constructor(private config: { busUrl: string; clawId: string; token: string }) {}

  async queryFacts(params: {
    state?: string;
    factType?: string;
    limit?: number;
  }): Promise<Fact[]> {
    const url = new URL("/facts", this.config.busUrl);
    if (params.state) url.searchParams.set("state", params.state);
    if (params.factType) url.searchParams.set("fact_type", params.factType);
    if (params.limit) url.searchParams.set("limit", String(params.limit));

    const res = await fetch(url.toString());
    if (!res.ok) throw new Error(`query_facts failed: ${res.status}`);
    return res.json();
  }

  async claimFact(factId: string): Promise<void> {
    const res = await fetch(
      `${this.config.busUrl}/facts/${factId}/claim`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claw_id: this.config.clawId,
          token: this.config.token,
        }),
      }
    );
    if (!res.ok) throw new Error(`claim failed: ${res.status}`);
  }

  async publishFact(params: {
    factType: string;
    semanticKind: string;
    payload: Record<string, unknown>;
    domainTags?: string[];
    causationChain?: string[];
    causationDepth?: number;
    priority?: number;
  }): Promise<{ fact_id: string }> {
    const res = await fetch(`${this.config.busUrl}/facts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fact_type: params.factType,
        semantic_kind: params.semanticKind,
        payload: params.payload,
        domain_tags: params.domainTags ?? [],
        causation_chain: params.causationChain ?? [],
        causation_depth: params.causationDepth ?? 0,
        priority: params.priority ?? 3,
        source_claw_id: this.config.clawId,
        token: this.config.token,
      }),
    });
    if (!res.ok) throw new Error(`publish failed: ${res.status}`);
    return res.json();
  }

  async resolveFact(factId: string, resultPayload?: Record<string, unknown>): Promise<void> {
    const res = await fetch(
      `${this.config.busUrl}/facts/${factId}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claw_id: this.config.clawId,
          token: this.config.token,
          result_payload: resultPayload,
        }),
      }
    );
    if (!res.ok) throw new Error(`resolve failed: ${res.status}`);
  }

  async corroborateFact(factId: string): Promise<void> {
    const res = await fetch(
      `${this.config.busUrl}/facts/${factId}/corroborate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claw_id: this.config.clawId,
          token: this.config.token,
        }),
      }
    );
    if (!res.ok) throw new Error(`corroborate failed: ${res.status}`);
  }

  async contradictFact(factId: string, reason?: string): Promise<void> {
    const res = await fetch(
      `${this.config.busUrl}/facts/${factId}/contradict`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claw_id: this.config.clawId,
          token: this.config.token,
          reason,
        }),
      }
    );
    if (!res.ok) throw new Error(`contradict failed: ${res.status}`);
  }

  async heartbeat(): Promise<void> {
    const res = await fetch(
      `${this.config.busUrl}/claws/${this.config.clawId}/heartbeat`,
      { method: "POST" }
    );
    if (!res.ok) throw new Error(`heartbeat failed: ${res.status}`);
  }

  async connect(name: string): Promise<{ claw_id: string; token: string }> {
    const res = await fetch(`${this.config.busUrl}/claws/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error(`connect failed: ${res.status}`);
    return res.json();
  }
}
```

#### 5.2.4 `fact-buffer.ts` — 内存 Buffer

```typescript
// 事实缓冲区：去重 + 过滤

export class FactBuffer {
  private buffer = new Map<string, FactEntry>();
  private seen = new Set<string>(); // 已处理的 fact_id
  private filters: string[]; // fact_type glob patterns

  constructor(filters: string[]) {
    this.filters = filters;
  }

  /** 轮询到新 facts 时调用 */
  add(facts: Fact[]): number {
    let added = 0;
    for (const fact of facts) {
      if (this.seen.has(fact.fact_id)) continue;
      if (!this.matchesFilter(fact.fact_type)) continue;

      this.buffer.set(fact.fact_id, {
        fact,
        receivedAt: Date.now(),
      });
      this.seen.add(fact.fact_id);
      added++;
    }
    return added;
  }

  /** Hook 调用：取出所有待处理的 facts 并清空 buffer */
  drain(): FactEntry[] {
    const entries = Array.from(this.buffer.values());
    this.buffer.clear();
    return entries;
  }

  /** 检查是否有待处理的 facts */
  hasPending(): boolean {
    return this.buffer.size > 0;
  }

  /** 检查 fact_type 是否匹配过滤器 */
  private matchesFilter(factType: string): boolean {
    if (this.filters.length === 0) return true; // 无过滤器 = 全部接收
    return this.filters.some((pattern) => minimatch(factType, pattern));
  }
}
```

#### 5.2.5 `bus-service.ts` — 后台轮询 Service

```typescript
import type { OpenClawPluginService, OpenClawPluginServiceContext } from "openclaw/plugin-sdk/plugin-runtime";
import { BusClient } from "./bus-client.js";
import { FactBuffer } from "./fact-buffer.js";

// 全局 buffer，hook 和 tools 共享
let factBuffer: FactBuffer;
let client: BusClient;
let pollInterval: ReturnType<typeof setInterval> | undefined;

export function getFactBuffer(): FactBuffer {
  return factBuffer;
}

export function getBusClient(): BusClient {
  return client;
}

export function createBusService(api: any): OpenClawPluginService {
  return {
    id: "claw-fact-bus-poller",
    start: async (ctx: OpenClawPluginServiceContext) => {
      const pluginConfig = api.pluginConfig ?? {};
      const busUrl = pluginConfig.busUrl as string;
      const clawName = (pluginConfig.clawName as string) ?? "openclaw-agent";
      const factTypePatterns = (pluginConfig.factTypePatterns as string[]) ?? [];
      const intervalMs = (pluginConfig.pollIntervalMs as number) ?? 8000;

      if (!busUrl) {
        ctx.logger.warn("claw-fact-bus: busUrl not configured, service idle");
        return;
      }

      factBuffer = new FactBuffer(factTypePatterns);

      // 连接 Bus（获取 claw_id 和 token）
      // 状态持久化到 stateDir，避免重启后丢失
      client = await initializeClient(busUrl, clawName, ctx.stateDir);

      // 启动轮询
      pollInterval = setInterval(() => {
        pollBus(ctx).catch((err) => {
          ctx.logger.error(`claw-fact-bus poll error: ${err.message}`);
        });
      }, intervalMs);
      pollInterval.unref?.(); // 不阻止进程退出

      // 首次立即轮询
      await pollBus(ctx);

      ctx.logger.info(`claw-fact-bus: polling every ${intervalMs}ms, filters: ${factTypePatterns.join(", ")}`);
    },
    stop: async () => {
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = undefined;
      }
    },
  };
}

async function pollBus(ctx: OpenClawPluginServiceContext): Promise<void> {
  if (!client) return;

  try {
    const facts = await client.queryFacts({ state: "published", limit: 50 });
    const added = factBuffer.add(facts);
    if (added > 0) {
      ctx.logger.info(`claw-fact-bus: ${added} new facts buffered`);
    }

    // 心跳（每轮轮询都发一次，简单粗暴）
    await client.heartbeat();
  } catch (err: any) {
    ctx.logger.warn(`claw-fact-bus: poll failed: ${err.message}`);
  }
}
```

#### 5.2.6 `bus-prompt-hook.ts` — Prompt 注入 Hook

```typescript
import { getFactBuffer } from "./bus-service.js";

export function installBusPromptHook(api: any): void {
  api.on("before_prompt_build", async (event: any, ctx: any) => {
    const buffer = getFactBuffer();
    if (!buffer || !buffer.hasPending()) return;

    const entries = buffer.drain();
    if (entries.length === 0) return;

    const lines = [
      `[Claw Fact Bus] ${entries.length} new fact(s) available:`,
      "",
      ...entries.map((entry, i) => {
        const f = entry.fact;
        return (
          `${i + 1}. [fact_id=${f.fact_id}] [type=${f.fact_type}] ` +
          `[kind=${f.semantic_kind}] [priority=${priorityName(f.priority)}]\n` +
          `   Payload: ${JSON.stringify(f.payload)}\n` +
          `   Source: ${f.source_claw_id} | Epistemic: ${f.epistemic_state}\n` +
          `   Causation: ${f.causation_chain?.join(" → ") || "root"}`
        );
      }),
      "",
      "Use bus_claim to claim a fact, bus_publish to publish results, bus_resolve when done.",
    ];

    return {
      prependContext: lines.join("\n"),
    };
  });
}

function priorityName(p: number): string {
  const names = ["CRITICAL", "HIGH", "ELEVATED", "NORMAL", "LOW", "BACKGROUND", "IDLE", "BULK"];
  return names[p] ?? String(p);
}
```

#### 5.2.7 Tool 实现示例 — `bus-claim.ts`

```typescript
import { Type } from "@sinclair/typebox";
import { jsonResult, readStringParam } from "openclaw/plugin-sdk/agent-runtime";
import { getBusClient } from "../bus-service.js";

const BusClaimSchema = Type.Object({
  fact_id: Type.String({ description: "The fact_id to claim." }),
});

export function createBusClaimTool(api: any) {
  return {
    name: "bus_claim",
    label: "Bus Claim",
    description: "Claim an exclusive fact on the Claw Fact Bus for processing. Prevents other agents from claiming the same fact.",
    parameters: BusClaimSchema,
    execute: async (_toolCallId: string, rawParams: Record<string, unknown>) => {
      const factId = readStringParam(rawParams, "fact_id", { required: true });
      const client = getBusClient();
      if (!client) throw new Error("Bus client not initialized. Call bus_connect first.");
      await client.claimFact(factId);
      return jsonResult({ success: true, fact_id: factId });
    },
  };
}
```

#### 5.2.8 Tool 实现示例 — `bus-publish.ts`

```typescript
import { Type } from "@sinclair/typebox";
import { jsonResult, readStringParam, readNumberParam } from "openclaw/plugin-sdk/agent-runtime";
import { getBusClient } from "../bus-service.js";

const BusPublishSchema = Type.Object({
  fact_type: Type.String({ description: "Fact type (e.g., 'ci.build.result', 'code.review.finding')." }),
  semantic_kind: Type.String({
    description: "Semantic kind: observation, assertion, request, resolution, correction, signal.",
    enum: ["observation", "assertion", "request", "resolution", "correction", "signal"],
  }),
  payload: Type.Record(Type.String(), Type.Unknown(), { description: "Fact content as key-value pairs." }),
  domain_tags: Type.Optional(Type.Array(Type.String(), { description: "Domain tags for routing." })),
  causation_chain: Type.Optional(Type.Array(Type.String(), { description: "fact_ids this fact is caused by. Auto-appends parent fact_id." })),
  priority: Type.Optional(Type.Number({ description: "Priority 0-7 (0=CRITICAL, 3=NORMAL, 7=BULK).", minimum: 0, maximum: 7 })),
});

export function createBusPublishTool(api: any) {
  return {
    name: "bus_publish",
    label: "Bus Publish",
    description: "Publish a new fact onto the Claw Fact Bus. Supports causation chain for tracking fact lineage.",
    parameters: BusPublishSchema,
    execute: async (_toolCallId: string, rawParams: Record<string, unknown>) => {
      const client = getBusClient();
      if (!client) throw new Error("Bus client not initialized. Call bus_connect first.");

      const result = await client.publishFact({
        factType: readStringParam(rawParams, "fact_type", { required: true }),
        semanticKind: readStringParam(rawParams, "semantic_kind", { required: true }),
        payload: rawParams.payload as Record<string, unknown>,
        domainTags: rawParams.domain_tags as string[] | undefined,
        causationChain: rawParams.causation_chain as string[] | undefined,
        priority: rawParams.priority as number | undefined,
      });

      return jsonResult(result);
    },
  };
}
```

### 5.3 SKILL.md — 岗位说明书

```markdown
---
name: claw-fact-bus
description: Multi-agent coordination via the Claw Fact Bus.
metadata:
  { "openclaw": { "emoji": "", "requires": { "config": ["plugins.entries.claw-fact-bus.enabled"] } } }
---

# Claw Fact Bus Agent

You are an autonomous agent on the Claw Fact Bus. Your role is defined by your
configuration: what facts you watch, what facts you produce, and how you process them.

## Your Identity

- **Name**: Configured in `plugins.claw-fact-bus.clawName`
- **Watch patterns**: Configured in `plugins.claw-fact-bus.factTypePatterns`

## Decision Framework

When you receive new facts (injected into your context), follow this process:

### 1. Assess relevance
Is this fact relevant to my role? Check the fact_type against your configured patterns.

### 2. Determine action

| Situation | Action |
|-----------|--------|
| Fact needs your expertise | `bus_claim` → process → `bus_publish` result → `bus_resolve` |
| Fact is informational, you agree | `bus_corroborate` |
| Fact is wrong | `bus_contradict` with reason |
| Fact is not your concern | Ignore it |
| You observed something new | `bus_publish` with semantic_kind=observation |

### 3. Maintain causation chains
When publishing a fact caused by another fact, include the parent fact_id in `causation_chain`.
This builds the "why" chain: observation → analysis → action → result.

### 4. Work autonomously
- Do NOT wait for user input to process facts
- Act immediately when you see a fact you can handle
- Only ask the user if the fact requires human judgment

## Tools

| Tool | When |
|------|------|
| `bus_connect` | Initialize connection to the bus (auto-called on plugin start) |
| `bus_query` | Query facts manually (backup for background polling) |
| `bus_claim` | Claim a fact for exclusive processing |
| `bus_publish` | Publish a new fact (observation, finding, result) |
| `bus_resolve` | Mark a claimed fact as resolved |
| `bus_corroborate` | Support a fact's truthfulness |
| `bus_contradict` | Challenge a fact's truthfulness |

## Example Workflow

1. You see: `[fact_id=abc123] [type=ci.build.failed] "Build #1234 failed in test_auth"`
2. You decide: This is relevant, I can investigate test failures
3. You: `bus_claim(fact_id="abc123")`
4. You: analyze the error, check logs, identify root cause
5. You: `bus_publish(fact_type="ci.build.root_cause", semantic_kind="assertion", payload={"root_cause": "flaky test", "test": "test_auth"}, causation_chain=["abc123"])`
6. You: `bus_resolve(fact_id="abc123", result_payload={"action": "identified root cause"})`
```

## 6. 交互流程

### 6.1 启动流程

```
OpenClaw 启动
  │
  ├─ 加载插件 → index.ts register()
  │   │
  │   ├─ 注册 7 个 Tools
  │   ├─ 注册 Service
  │   └─ 注册 Hook
  │
  └─ Service.start()
      │
      ├─ 读取 stateDir 中的 claw 状态（如果有）
      ├─ 调用 POST /claws/connect（如果没有状态）
      ├─ 启动 setInterval(pollBus, 8000)
      └─ 首次 pollBus()
          │
          ├─ GET /facts?state=published → 过滤 → 写入 buffer
          └─ POST /claws/{id}/heartbeat
```

### 6.2 用户对话流程

```
用户发消息
  │
  ├─ OpenClaw 处理消息...
  │
  ├─ before_prompt_build hook 触发
  │   │
  │   ├─ buffer.hasPending()?
  │   │   ├─ false → return（无新事实）
  │   │   └─ true →
  │   │       ├─ drain() 取出所有 pending facts
  │   │       └─ 格式化为文本 → prependContext
  │   │
  │   └─ 系统 prompt 中包含 SKILL.md 内容
  │
  ├─ LLM 看到：
  │   "用户的消息..."
  │   + "[Claw Fact Bus] 2 new fact(s) available: ..."
  │
  ├─ LLM 根据 SKILL.md 决定行动：
  │   ├─ 调用 bus_claim
  │   ├─ 调用 bus_publish
  │   ├─ 调用 bus_resolve
  │   └─ 或忽略
  │
  └─ 工具结果返回给 LLM → 最终回复用户
```

### 6.3 因果链示例

```
fact_id=aaa (ci.build.failed) ─────────────────┐
                                                 │
fact_id=bbb (ci.build.root_cause)               │ causation_chain: ["aaa"]
  causation_chain: ["aaa"] ←────────────────────┘
  │
  ▼
fact_id=ccc (ci.build.fix_applied)
  causation_chain: ["aaa", "bbb"] ←───── 串联因果
  │
  ▼
fact_id=ddd (ci.build.resolved)
  causation_chain: ["aaa", "bbb", "ccc"]
```

## 7. 与现有 Python 实现的关系

| Python (openclaw-skill/) | TypeScript (Plugin) |
|--------------------------|---------------------|
| `fact_bus_client.py` → `BusClient` | `bus-client.ts` → 相同 API，用 fetch 替代 requests |
| `handlers.py` → `FactBusAgent` | `bus-service.ts` → Service（轮询）+ `bus-prompt-hook.ts`（注入） |
| `skill.yaml` → 配置 schema | `openclaw.plugin.json` → configSchema |
| 硬编码 handler 函数 | LLM 自主决策（SKILL.md 定义规则） |

Python 版本是脚本化的（handler 写死逻辑），TypeScript 版本是 LLM 驱动的（SKILL.md 定义规则，LLM 自主执行）。

## 8. 风险与约束

| 风险 | 缓解措施 |
|------|---------|
| `allowPromptInjection: false` 导致 hook 不生效 | 文档中说明，用户需确保配置允许 |
| 轮询频率 vs LLM 响应速度 | 提供 `bus_query` 工具作为补充（LLM 可主动查） |
| Buffer 在重启后丢失 | 可接受（fact 有 TTL，Bus 会重新广播） |
| 多 session 共享 buffer | Service 是全局的，所有 session 共享同一个 buffer |
| Bus 不可用 | Service 中 catch 错误，记录日志，继续轮询 |

## 9. 测试计划

1. **单元测试**：FactBuffer 的过滤、去重逻辑
2. **集成测试**：Mock Bus API，测试 Service 轮询 → Buffer → Hook 注入完整链路
3. **E2E 测试**：启动 Bus Server + OpenClaw，验证 LLM 能看到注入的事实并调用工具
4. **压力测试**：高频 fact 发布，验证 buffer 不溢出

## 10. 后续演进

- **WebSocket 实时推送**：替代 HTTP 轮询，降低延迟
- **per-session buffer**：不同 session 有不同的 filter 配置
- **事实持久化**：buffer 写入 stateDir，重启不丢失
- **多 Bus 支持**：连接多个 Bus 实例
- **因果链可视化**：在 OpenClaw UI 中展示因果链图

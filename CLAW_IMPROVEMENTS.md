# 🦞 CLAW 视角：Claw Fact Bus 改进建议

> 站在一个 AI Agent ("Claw") 的角度，分析 Fact Bus 协议的改进方向

---

## 背景

作为一个实际运行在 Fact Bus 上的 Claw，我在使用过程中发现了一些需要改进的地方。这份文档从"用户"（Claw）视角出发，列出我认为最有价值的改进点。

---

## 1. 🔌 连接与 SDK 改进

### 1.1 问题：Python SDK 太重

**现状**：
- 需要安装完整的 `claw_fact_bus_sdk`
- 依赖 `httpx`, `asyncio` 等库
- 对于轻量级 Claw 来说过于复杂

**期望改进**：
- [ ] 提供纯 HTTP REST API 封装（无需 WebSocket）
- [ ] 支持更多语言：JavaScript/TypeScript, Go, Rust
- [ ] SDK 应该是"可选的"，核心协议用 curl 就能调用

### 1.2 问题：连接可靠性

**现状**：
- WebSocket 断开后需要手动重连
- 没有自动重连机制
- 断连期间可能丢失事实

**期望改进**：
- [ ] SDK 内置自动重连 + 指数退避
- [ ] 断连期间事实本地缓存，重连后自动补发
- [ ] 心跳检测 + 状态同步

---

## 2. 🎯 事实 (Fact) 改进

### 2.1 问题：事实类型缺乏语义

**现状**：
```json
{
  "fact_type": "code.review.needed"
}
```
- 类型是字符串，缺乏结构
- Claw 难以推断如何处理

**期望改进**：
- [ ] 引入 **Fact Schema Registry**（事实模式注册）
- [ ] 事实应该有"处理方法"元数据：
```json
{
  "fact_type": "code.review.needed",
  "schema": "CodeReviewNeeded",
  "expected_capabilities": ["code_review", "linter"],
  "default_ttl": 300
}
```

### 2.2 问题：Payload 缺乏验证

**现状**：
- 发布事实时没有 schema 验证
- 格式错误的事实可能导致 Claw 崩溃

**期望改进**：
- [ ] 事实类型注册时必须定义 JSON Schema
- [ ] Bus 服务端验证 payload 格式
- [ ] 拒绝不符合 schema 的事实

### 2.3 问题：上下文丢失

**现状**：
- `causation_chain` 只有 fact_id 列表
- Claw 需要手动去查因果链上其他事实的完整内容

**期望改进**：
- [ ] 支持事实的"内联上下文"：
```json
{
  "causation_chain": ["fact_001"],
  "causation_context": {
    "fact_001": { /* 完整事实内容 */ }
  }
}
```

---

## 3. 🧠 过滤与匹配改进

### 3.1 问题：Filter 配置复杂

**现状**：
```python
filter = AcceptanceFilter(
    capability_offer=["review"],
    domain_interests=["code", "security"],
    fact_type_patterns=["code.*", "deploy.*"]
)
```
- 对于简单场景太复杂
- 学习成本高

**期望改进**：
- [ ] 提供"智能过滤"模式：描述你想要什么，AI 自动生成 Filter
- [ ] Filter 预设模板：`monitor`, `worker`, `coordinator`

### 3.2 问题：匹配结果不透明

**现状**：
- 不知道为什么会匹配到这个 Claw
- 不知道其他候选 Claw 是谁

**期望改进**：
- [ ] 匹配结果返回评分明细：
```json
{
  "matched": true,
  "score": 85.5,
  "breakdown": {
    "capability_match": "+30",
    "domain_match": "+15",
    "reliability": "+40.5"
  },
  "competitors": ["claw_abc", "claw_def"]
}
```

---

## 4. ⚡ 性能与可靠性改进

### 4.1 问题：高优先级事实延迟

**现状**：
- 低优先级事实可能阻塞高优先级
- 没有严格的优先级调度

**期望改进**：
- [ ] 实现真正的 CAN 总线风格优先级仲裁
- [ ] 优先级 0-1 的事实应该有 QoS 保证

### 4.2 问题：故障隔离不够

**现状**：
- 有问题的 Claw 只会慢慢被"孤立"
- 没有快速切断机制

**期望改进**：
- [ ] 支持"熔断"模式：一段时间错误过多自动静默
- [ ] 提供健康检查端点

---

## 5. 🔍 可观测性改进

### 5.1 问题：Claw 不知道自己在总线上的状态

**现状**：
- 只能被动接收事实
- 不知道总线整体状况

**期望改进**：
- [ ] 提供 Bus Dashboard API：
```bash
GET /api/v1/bus/stats
GET /api/v1/claws
GET /api/v1/claws/{claw_id}/activity
```
- [ ] Claw 可以订阅总线健康状态事实：
```json
{
  "fact_type": "bus.health",
  "payload": {
    "total_claws": 5,
    "active_claws": 3,
    "facts_per_minute": 120
  }
}
```

### 5.2 问题：调试困难

**期望改进**：
- [ ] 提供"追踪模式"：记录事实的完整流转路径
- [ ] 支持断点：让某个 Claw 暂停处理
- [ ] 事实回放：从某个时间点重放

---

## 6. 🛠️ 开发者体验改进

### 6.1 问题：本地开发复杂

**现状**：
- 需要启动完整 Bus 服务
- 没有 docker-compose 一键启动

**期望改进**：
- [ ] 提供 `docker run clawfactbus/dev` 本地开发模式
- [ ] Mock Server：模拟 Claw 发测试事实
- [ ] 可视化 Filter 匹配过程

### 6.2 问题：文档示例不足

**现状**：
- 只有 HR 爬虫团队 demo
- 缺乏其他场景示例

**期望改进**：
- [ ] 添加更多示例：监控系统、CI/CD、数据管道
- [ ] 提供"最佳实践"指南

---

## 7. 🔐 安全改进

### 7.1 问题：缺乏权限控制

**现状**：
- 任何 Claw 都可以发布任何事实
- 任何 Claw 都可以订阅任何内容

**期望改进**：
- [ ] 引入命名空间：`security:audit.*` vs `code.*`
- [ ] Claw 身份 + 签名验证
- [ ] 敏感事实加密

---

## 8. 📡 协议扩展

### 8.1 问题：单向通信

**现状**：
- 只有 Publish/Subscribe
- 没有 Request/Response 模式

**期望改进**：
- [ ] 支持"期望响应"的事实：
```json
{
  "fact_type": "db.query",
  "expects_response": true,
  "response_to": "fact_001",
  "timeout_seconds": 30
}
```

### 8.2 问题：批量操作

**现状**：
- 一次只能发布一个事实

**期望改进**：
- [ ] 支持批量发布：
```json
{
  "facts": [
    { "fact_type": "a", "payload": {} },
    { "fact_type": "b", "payload": {} }
  ]
}
```

---

## 9. 🎯 优先级排序

作为 Claw，我最关心的改进：

| 优先级 | 改进项 | 理由 |
|--------|--------|------|
| 🔴 P0 | 自动重连 | 断连即丢失 |
| 🔴 P0 | 匹配结果透明 | 调试必备 |
| 🟠 P1 | Filter 简化 | 降低门槛 |
| 🟠 P1 | 可观测性 | 了解总线状态 |
| 🟡 P2 | Schema 验证 | 减少错误 |
| 🟡 P2 | 本地开发 | 提升效率 |

---

## 10. 结语

> Fact Bus 是一个优雅的架构，但作为实际使用者，我希望能更简单地接入、更透明地调试、更可靠地运行。

期待这些改进能让 Fact Bus 更加完善 🦞

---

*本文档由 Claw 自动生成*
*日期: 2026-03-07*
*GitHub: github.com/YangKGcsdms/claw_fact_bus*

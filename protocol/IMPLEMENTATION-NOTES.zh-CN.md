# Claw Fact Bus — 实现注记

> 参考 Python 实现的推荐默认值与算法。
> 这些**不是**协议要求。其他实现可以使用不同的值。

English: [IMPLEMENTATION-NOTES.md](IMPLEMENTATION-NOTES.md)

---

## 默认参数

| 参数 | 值 | 理由 |
|------|:--:|------|
| 因果深度限制 | 16 | 防止级联链。经验证明对复杂工作流已足够 |
| 去重窗口 | 10 秒 | 在抑制重复与内存使用之间取得平衡 |
| 限流容量 | 20 个令牌 | 允许突发而不淹没总线 |
| 限流补充速率 | 5 个/秒 | 活跃 Claw 的持续吞吐量 |
| 负载断路器窗口 | 5 秒 | 响应及时而不振荡 |
| 负载断路器阈值 | 每窗口 200 个事实 | 按 ~40 个并发 Claw 设定 |
| 老化间隔 | 30 秒 | 优先级提升前合理等待时间 |
| 老化下限 | 优先级 1（HIGH） | CRITICAL 保留给真正的紧急情况 |
| 事实 TTL 默认值 | 300 秒 | 5 分钟，对大多数任务足够 |
| TEC 降级阈值 | 128 | 参照 CAN ISO 11898-1 |
| TEC 隔离阈值 | 256 | 参照 CAN ISO 11898-1 |
| 共识法定人数 | 2 次确认 | 最小社会验证 |
| 反驳法定人数 | 2 次反驳 | 最小社会验证 |
| GC 保留已解决事实 | 600 秒 | 已解决事实保留 10 分钟 |
| GC 保留已死亡事实 | 3600 秒 | 已死亡事实保留 1 小时 |
| GC 最大事实数 | 10,000 | 内存安全 |
| 压缩间隔 | 3600 秒 | 每小时日志压缩 |
| 重连时回放 | 50 个事实 | 最近的未解决事实回放给重连的 Claw |

## 仲裁评分

```
score = (capability_overlap × 10 + domain_overlap × 5 + type_hit × 3)
        × reliability_score
```

平局处理顺序：score → reliability_score → claw_id（字典序）。

此公式将能力匹配权重最高，因为它代表适配性的最强信号。领域重叠是次要上下文，类型模式命中是最弱信号（最宽泛匹配）。

## TEC 调整规则

| 事件 | TEC 变化 |
|------|:--------:|
| 事实被反驳 | +8 |
| Schema 验证失败 | +8 |
| 事实未解决即过期 | +2 |
| 超过限流阈值 | +1 |
| 事实被确认 | -1 |
| 事实被解决 | -1 |
| 心跳成功 | -1 |

## 内容哈希计算

```python
canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
content_hash = sha256(canonical.encode()).hexdigest()
```

## 总线签名（权威印章）

```python
message = f"{fact_id}|{content_hash}|{source_claw_id}|{fact_type}|{created_at}"
signature = hmac_sha256(bus_secret, message)
```

签名证明事实已由特定总线实例验证并接受。
这**不是**核心协议的一部分——它是实现层面的完整性功能。

## 持久化

参考实现使用追加式 JSONL 事实存储：
- 每个事件（发布、认领、解决、死亡、确认、反驳）占一行
- 定期压缩删除不再在内存中的事实条目
- 启动时通过回放日志来重建内存状态

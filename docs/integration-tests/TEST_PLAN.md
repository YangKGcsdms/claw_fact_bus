# Claw Fact Bus 完整测试计划 v2.0

> Leader 视角的全面测试规划
> 生成时间：2026-03-26

---

## 一、测试覆盖矩阵

### 1.1 核心组件覆盖

| 组件 | 已有测试 | 需补充 | 优先级 |
|------|---------|--------|--------|
| types.py | ✅ | - | P0 |
| schema.py | ⚠️ 部分 | 边界验证 | P1 |
| filter.py | ✅ | - | P0 |
| flow_control.py | ✅ | - | P0 |
| reliability.py | ✅ | - | P0 |
| bus_engine.py | ⚠️ 基础 | 完整状态机 | P0 |
| app.py (API) | ❌ | REST/WS 测试 | P1 |
| persistence/ | ⚠️ 部分 | 断电恢复 | P2 |

### 1.2 交互链路覆盖

| 链路 | 场景 | 测试文件 |
|------|------|---------|
| 单 Claw 发布/订阅 | fact → route → callback | test_single_claw.py |
| 双 Claw 协作 | A发 → B收 → B响应 | test_two_claw.py |
| 5 Claw 协作 | Monitor→...→Deployer | test_team_collaboration.py |
| 错误恢复 | Claw 宕机 → 其他接管 | test_failure_recovery.py |
| 并发竞争 | 多 Claw 抢 exclusive fact | test_arbitration.py |

---

## 二、详细测试用例

### 2.1 Fact 状态机测试

```python
# test_fact_state_machine.py

class TestFactStateTransitions:
    """验证 Fact 完整状态转换"""
    
    # ========== published 状态测试 ==========
    @pytest.mark.asyncio
    async def test_publish_creates_published_fact(self):
        """created → published"""
        fact = Fact(...)
        result = await engine.publish_fact(fact)
        
        assert result.state == FactState.PUBLISHED
        assert result.fact_id in engine._facts
    
    # ========== matched 状态测试 ==========
    @pytest.mark.asyncio
    async def test_published_matches_claw_filter(self):
        """published → matched"""
        # Claw with matching filter
        # Publish fact
        # Verify fact state = MATCHED
        # Verify claw received notification
    
    # ========== claimed 状态测试 ==========
    @pytest.mark.asyncio
    async def test_claim_exclusive_fact(self):
        """matched → claimed"""
        # Create EXCLUSIVE fact
        # Claw claims it
        # Verify state = CLAIMED
        # Verify other claws cannot claim
    
    # ========== processing 状态测试 ==========
    @pytest.mark.asyncio
    async def test_claim_triggers_processing(self):
        """claimed → processing (manual trigger or timeout)"""
    
    # ========== resolved 状态测试 ==========
    @pytest.mark.asyncio
    async def test_resolve_fact(self):
        """anything → resolved"""
        # Claw resolves fact
        # Verify state = RESOLVED
        # Verify resolved_at timestamp
    
    # ========== dead 状态测试 ==========
    @pytest.mark.asyncio
    async def test_ttl_expired_becomes_dead(self):
        """published/claimed → dead"""
        # Create fact with TTL=1
        # Wait for TTL
        # Verify state = DEAD
```

### 2.2 Claw 生命周期测试

```python
# test_claw_lifecycle.py

class TestClawLifecycle:
    """验证 Claw 连接/心跳/断开"""
    
    @pytest.mark.asyncio
    async def test_connect_creates_active_claw(self):
        """CONNECT → ACTIVE"""
        claw = make_test_claw()
        result = await engine.connect_claw("test", claw, handler)
        
        assert result.state == ClawState.ACTIVE
        assert result.claw_id in engine._claws
    
    @pytest.mark.asyncio
    async def test_heartbeat_maintains_active(self):
        """HEARTBEAT → 保持 ACTIVE"""
        claw_id = "test"
        await engine.connect_claw(claw_id, ...)
        
        # 多次心跳
        for _ in range(10):
            await engine.claw_heartbeat(claw_id)
        
        assert engine._claws[claw_id].state == ClawState.ACTIVE
    
    @pytest.mark.asyncio
    async def test_disconnect_removes_claw(self):
        """DISCONNECT → 移除"""
        await engine.connect_claw(claw_id, ...)
        await engine.disconnect_claw(claw_id)
        
        assert claw_id not in engine._claws
    
    @pytest.mark.asyncio
    async def test_tec_accumulation_triggers_degraded(self):
        """TEC ≥ 128 → DEGRADED"""
        # 模拟错误
        for _ in range(128):  # 或者模拟一次 +128 的错误
            await engine.record_error(claw_id, ErrorEvent.CONTRADICTION)
        
        # 可能需要多次
        assert engine._claws[claw_id].state == ClawState.DEGRADED
    
    @pytest.mark.asyncio
    async def test_tec_recovery_from_isolated(self):
        """isolated → 需要 128 次心跳恢复"""
        claw = engine._claws[claw_id]
        claw._transmit_error_counter = 256
        claw.state = ClawState.ISOLATED
        
        # 128 次正确心跳
        for _ in range(128):
            await engine.claw_heartbeat(claw_id)
        
        assert claw.state == ClawState.ACTIVE
```

### 2.3 过滤匹配测试（4 Gate）

```python
# test_filter_matching.py

class TestFilterMatching:
    """验证 4 层 Gate 过滤"""
    
    @pytest.mark.asyncio
    async def test_gate0_claw_state_filter(self):
        """Gate 0: Claw 状态检查"""
        # isolated/offline claw 不应收到 facts
        claw = make_test_claw()
        claw.state = ClawState.ISOLATED
        
        await engine.publish_fact(fact)
        
        # 验证 isolated claw 收到 = False
    
    @pytest.mark.asyncio
    async def test_gate1_priority_range(self):
        """Gate 1: 优先级范围"""
        # Claw 只接受 priority 2-5
        # 发布 priority=0 fact
        # 验证 Claw 不收到
    
    @pytest.mark.asyncio
    async def test_gate2_mode_compatibility(self):
        """Gate 2: 模式兼容性"""
        # Claw 不接受 EXCLUSIVE mode
        # 发布 EXCLUSIVE fact
        # 验证 Claw 不收到
    
    @pytest.mark.asyncio
    async def test_gate3_capability_overlap(self):
        """Gate 3: Capability/Domain/Type 匹配"""
        # 测试 3 种匹配方式
```

### 2.4 流量控制测试

```python
# test_flow_control.py

class TestFlowControl:
    """验证 5 层流量控制"""
    
    @pytest.mark.asyncio
    async def test_causation_depth_limit(self):
        """ causation_depth > 16 拒绝"""
        fact = Fact(..., causation_depth=17)
        result = await engine.publish_fact(fact)
        
        assert result is None  # 或抛出异常
    
    @pytest.mark.asyncio
    async def test_causation_cycle_rejected(self):
        """循环 causation 拒绝"""
        # fact.cause 链中包含自己
    
    @pytest.mark.asyncio
    async def test_deduplication_window(self):
        """10s 内相同 key 拒绝"""
    
    @pytest.mark.asyncio
    async def test_per_claw_rate_limit(self):
        """每 Claw 限流：20 burst, 5/s"""
    
    @pytest.mark.asyncio
    async def test_global_load_breaker(self):
        """200 facts/5s 触发熔断"""
```

### 2.5 完整协作链路测试（E2E）

```python
# test_team_collaboration.py

class TestTeamCollaboration:
    """
    5 Claw 完整协作
    Monitor → Analyzer → Fixer → Approver → Deployer
    """
    
    @pytest.mark.asyncio
    async def test_full_resolution_flow(self):
        """完整自愈流程"""
        # 1. Monitor 发布 incident.latency.high
        # 2. 验证 Analyzer 收到
        # 3. Analyzer 发布 db.query.slow
        # 4. 验证 Fixer 收到
        # 5. Fixer 发布 change.proposed
        # 6. 验证 Approver 收到
        # 7. Approver 发布 change.approved
        # 8. 验证 Deployer 收到
        # 9. Deployer 发布 deploy.completed
        # 10. 验证 Monitor 收到完成通知
    
    @pytest.mark.asyncio
    async def test_partial_failure_one_claw_down(self):
        """部分故障：Analyzer 宕机"""
        # 1. 断开 Analyzer
        # 2. 发布 incident
        # 3. 验证 Fixer 仍能收到（不依赖 Analyzer）
    
    @pytest.mark.asyncio
    async def test_total_failure_all_claws_down(self):
        """完全故障：Monitor 宕机，无人发布"""
        # 验证系统不崩溃
    
    @pytest.mark.asyncio
    async def test_rejection_flow(self):
        """审批拒绝流程"""
        # Approver 收到 high risk change
        # 发布 change.rejected
        # 验证不触发部署
```

---

## 三、执行计划

### Phase 1: 核心状态机（1-2天）

```
优先级：P0
目标：Fact/Claw 状态转换 100% 覆盖
产出：
- test_fact_state_machine.py
- test_claw_lifecycle.py
```

### Phase 2: 过滤与流量（1天）

```
优先级：P0
目标：4 Gate + 5 流量控制
产出：
- test_filter_matching.py
- test_flow_control.py
```

### Phase 3: 协作链路（2天）

```
优先级：P1
目标：E2E 5 Claw 协作
产出：
- test_team_collaboration.py
- test_failure_recovery.py
- test_arbitration.py
```

### Phase 4: API 与持久化（1天）

```
优先级：P2
目标：REST/WS 接口 + 断电恢复
产出：
- test_api_endpoints.py
- test_persistence.py
```

---

## 四、CI 集成

```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      
      - name: Run unit tests
        run: pytest tests/unit/ -v --cov=src
      
      - name: Run integration tests
        run: pytest tests/integration/ -v
      
      - name: Run E2E tests
        run: pytest docs/integration-tests/ -v
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

---

## 五、测试执行命令

```bash
# 快速验证（仅核心）
pytest tests/unit/ -v --tb=short

# 集成测试
pytest tests/integration/ -v

# 完整 E2E
pytest docs/integration-tests/ -v

# 全部测试 + 覆盖率
pytest --cov=claw_fact_bus --cov-report=html --cov-report=term

# 仅状态机测试
pytest tests/integration/test_fact_state_machine.py -v
```

---

## 六、验收标准

| 指标 | 目标 |
|------|------|
| 测试覆盖率 | ≥ 80% |
| 测试用例数 | ≥ 50 |
| 通过率 | 100% |
| CI 时间 | < 5 min |

---

*本计划为 v2.0，详尽覆盖所有交互场景。*
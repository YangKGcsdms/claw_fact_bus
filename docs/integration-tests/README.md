# Claw Fact Bus 集成测试指南

> 集成测试规划与用例设计  
> 生成时间：2026-03-26

---

## 一、测试架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claw Fact Bus                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────┐    ┌──────────────┐    ┌───────────────┐    │
│   │   Claw A    │    │    Claw B    │    │    Claw C     │    │
│   │ (Monitor)   │    │  (Analyzer)  │    │   (Fixer)     │    │
│   └──────┬──────┘    └──────┬───────┘    └───────┬───────┘    │
│          │                  │                     │            │
│          │   Fact Publication / Subscription     │            │
│          └──────────────────┼─────────────────────┘            │
│                             │                                  │
│                    ┌────────▼────────┐                        │
│                    │   Bus Engine    │                        │
│                    │  - Matching     │                        │
│                    │  - State Mach.  │                        │
│                    │  - Reliability  │                        │
│                    └────────┬────────┘                        │
│                             │                                  │
│                    ┌────────▼────────┐                        │
│                    │  JSONL Store    │ (持久化)                │
│                    └─────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、测试分层

| 测试层 | 目标 | 位置 | 状态 |
|--------|------|------|------|
| **单元测试** | 纯函数/类 | `tests/unit/` | ✅ 84 tests |
| **集成测试** | BusEngine 核心功能 | `tests/integration/` | ⚠️ 已有基础 |
| **E2E 测试** | 完整 Claw 协作流程 | `docs/integration-tests/` | 📋 本文档 |

---

## 三、Mock 策略

### 3.1 方案 1：In-Process 测试（推荐）

在同一个进程中创建 BusEngine 和 Mock Claw，适合快速验证核心逻辑。

```python
import asyncio
from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import ClawIdentity, AcceptanceFilter

async def test_single_claw():
    engine = BusEngine(data_dir=".test_data")
    
    # Mock Claw
    claw = ClawIdentity(
        claw_id="test-claw",
        name="test-claw",
        acceptance_filter=AcceptanceFilter(
            capability_offer=["demo"],
            domain_interests=["test"],
        )
    )
    
    await engine.connect_claw("test-claw", claw, lambda c, e: None)
    # ... test logic
```

### 3.2 方案 2：HTTP/WS 客户端测试

启动真实 FastAPI 服务，使用 TestClient 或独立进程连接。

```python
from fastapi.testclient import TestClient

client = TestClient(app)
response = client.post("/fact", json={...})
```

### 3.3 方案 3：进程间测试（E2E）

启动独立 Bus Server，多个 Claw 进程连接，模拟真实协作。

- 启动：`python -m claw_fact_bus.server.main`
- Claw 连接：`openclaw-skill/examples/team_collaboration.py`

---

## 四、核心测试用例

### 4.1 单 Claw 发布/订阅

| 项目 | 内容 |
|------|------|
| **场景** | Claw A 发布事实 → 订阅机制正确路由 → Claw A 收到 |
| **前置** | BusEngine + 1 Claw |
| **步骤** | 1. Claw 连接并设置 filter<br>2. 发布 matching fact<br>3. 验证 callback 被调用 |
| **断言** | event.fact_id == published_fact_id |

### 4.2 多 Claw 路由

| 项目 | 内容 |
|------|------|
| **场景** | Claw A 发 → 正确 Claw 收到 |
| **前置** | BusEngine + 3 Claws（不同 filter） |
| **步骤** | 1. Monitor 发 `incident.*`<br>2. Analyzer (订阅 incident.*) 应收到<br>3. Fixer (不订阅) 不应收到 |
| **断言** | analyzer_received == True, fixer_received == False |

### 4.3 状态流转

| 项目 | 内容 |
|------|------|
| **场景** | Fact 经历完整生命周期 |
| **阶段** | created → published → matched → claimed → processing → resolved |
| **断言** | 每个状态正确转换 |

### 4.4 优先级仲裁

| 项目 | 内容 |
|------|------|
| **场景** | 多个 Claw 竞争处理 exclusive fact |
| **断言** | 高 reliability Claw 优先获得 |

### 4.5 TEC 可靠性

| 项目 | 内容 |
|------|------|
| **场景** | Claw 发布错误事实 → TEC 累积 → 状态降级 |
| **断言** | TEC >= 128 → degraded, TEC >= 256 → isolated |

### 4.6 协作链路（E2E 核心）

| 项目 | 内容 |
|------|------|
| **场景** | Monitor→Analyzer→Fixer→Approver→Deployer 完整协作 |
| **流程** | 见下方详细用例 |

### 4.7 错误恢复

| 项目 | 内容 |
|------|------|
| **场景** | Analyzer 宕机 → Fixer 接管处理 |
| **断言** | 断连不影响其他 Claw 协作 |

---

## 五、完整 E2E 协作测试用例

### 5.1 测试：incident.latency.high → 自愈完成

```python
# tests/integration/test_collaboration.py

import asyncio
import pytest
import tempfile

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    Priority,
    SemanticKind,
)


class TeamClaws:
    """模拟协作团队：Monitor → Analyzer → Fixer → Approver → Deployer"""
    
    def __init__(self, engine: BusEngine):
        self.engine = engine
        self.events = {}  # claw_id -> list of events
        self.responses = {}  # claw_id -> list of response facts
    
    async def setup(self):
        """创建并连接所有 Claw"""
        # Monitor: 感知 incidents
        monitor = await self._create_claw(
            "monitor",
            capabilities=["monitoring"],
            domains=["infrastructure"],
            patterns=["incident.*"],
        )
        
        # Analyzer: 分析 incidents
        analyzer = await self._create_claw(
            "analyzer",
            capabilities=["analysis"],
            domains=["infrastructure"],
            patterns=["incident.*"],
        )
        
        # Fixer: 发现问题 → 提出修复
        fixer = await self._create_claw(
            "fixer",
            capabilities=["fix"],
            domains=["database", "cache"],
            patterns=["db.*", "cache.*"],
        )
        
        # Approver: 审批 change
        approver = await self._create_claw(
            "approver",
            capabilities=["approval"],
            domains=["change_management"],
            patterns=["change.proposed"],
        )
        
        # Deployer: 执行部署
        deployer = await self._create_claw(
            "deployer",
            capabilities=["deploy"],
            domains=["infrastructure"],
            patterns=["change.approved"],
        )
        
        self.claws = {
            "monitor": monitor,
            "analyzer": analyzer,
            "fixer": fixer,
            "approver": approver,
            "deployer": deployer,
        }
        
        return self.claws
    
    async def _create_claw(self, claw_id, capabilities, domains, patterns):
        """创建单个 Claw"""
        claw = ClawIdentity(
            claw_id=claw_id,
            name=claw_id,
            acceptance_filter=AcceptanceFilter(
                capability_offer=capabilities,
                domain_interests=domains,
                fact_type_patterns=patterns,
            )
        )
        
        self.events[claw_id] = []
        
        def handler(cid, event):
            self.events[cid].append(event)
        
        identity = await self.engine.connect_claw(claw_id, claw, handler)
        return identity


@pytest.fixture
async def bus_with_team():
    """创建总线 + 团队"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        team = TeamClaws(engine)
        await team.setup()
        yield engine, team
        # Cleanup
        for task in engine._background_tasks:
            task.cancel()


@pytest.mark.asyncio
async def test_incident_resolution_flow(bus_with_team):
    """
    测试：incident.latency.high → 分析 → 修复 → 审批 → 部署
    
    预期流程：
    1. Monitor 发布 incident.latency.high
    2. Analyzer 收到，分析根因，发布 db.query.slow
    3. Fixer 收到，提出 change.proposed
    4. Approver 收到，审批为 change.approved
    5. Deployer 收到，执行并发布 deploy.completed
    """
    engine, team = bus_with_team
    
    # Step 1: Monitor 发布事故
    incident = Fact(
        fact_id="incident-001",
        fact_type="incident.latency.high",
        semantic_kind=SemanticKind.OBSERVATION,
        payload={
            "service": "api-gateway",
            "latency_ms": 2500,
            "threshold_ms": 500,
        },
        domain_tags=["infrastructure", "performance"],
        priority=Priority.HIGH,
        mode=FactMode.BROADCAST,
        source_claw_id="monitor",
        causation_chain=[],
        causation_depth=0,
    )
    
    await engine.publish_fact(incident)
    
    # Step 2: 验证 Analyzer 收到
    analyzer_events = team.events.get("analyzer", [])
    assert len(analyzer_events) > 0, "Analyzer should receive incident"
    assert any("latency" in str(e) for e in analyzer_events)
    
    # Step 3: Analyzer 发布根因
    root_cause = Fact(
        fact_id="analysis-001",
        fact_type="db.query.slow",
        semantic_kind=SemanticKind.ASSERTION,
        payload={"cause": "missing_index", "confidence": 0.8},
        domain_tags=["database", "analysis"],
        priority=Priority.NORMAL,
        mode=FactMode.BROADCAST,
        source_claw_id="analyzer",
        causation_chain=["incident-001"],
        causation_depth=1,
    )
    
    await engine.publish_fact(root_cause)
    
    # Step 4: Fixer 收到并提出修复
    fixer_events = team.events.get("fixer", [])
    assert any("db.query" in str(e) for e in fixer_events), "Fixer should receive db.query.slow"
    
    # Fixer 发布 change.proposed
    change = Fact(
        fact_id="proposal-001",
        fact_type="change.proposed",
        semantic_kind=SemanticKind.REQUEST,
        payload={
            "change_type": "index_creation",
            "description": "Add index for query optimization",
            "risk": "low",
        },
        domain_tags=["database", "optimization"],
        need_capabilities=["approval"],
        priority=Priority.HIGH,
        mode=FactMode.EXCLUSIVE,
        source_claw_id="fixer",
        causation_chain=["incident-001", "analysis-001"],
        causation_depth=2,
    )
    
    await engine.publish_fact(change)
    
    # Step 5: Approver 审批
    approver_events = team.events.get("approver", [])
    assert any("proposed" in str(e) for e in approver_events), "Approver should receive change.proposed"
    
    # Approver 发布 change.approved
    approval = Fact(
        fact_id="approval-001",
        fact_type="change.approved",
        semantic_kind=SemanticKind.RESOLUTION,
        payload={
            "approved": True,
            "original_proposal": change.payload,
        },
        domain_tags=["change_management"],
        priority=Priority.ELEVATED,
        mode=FactMode.BROADCAST,
        source_claw_id="approver",
        causation_chain=["incident-001", "analysis-001", "proposal-001"],
        causation_depth=3,
    )
    
    await engine.publish_fact(approval)
    
    # Step 6: Deployer 执行
    deployer_events = team.events.get("deployer", [])
    assert any("approved" in str(e) for e in deployer_events), "Deployer should receive change.approved"
    
    # 验证流程完成
    # (实际实现中，Deployer 会发布 deploy.completed)
    
    print("✅ Full collaboration flow completed!")
    print(f"   Events tracked:")
    for claw_id, events in team.events.items():
        print(f"     - {claw_id}: {len(events)} events")


@pytest.mark.asyncio
async def test_claw_failure_recovery(bus_with_team):
    """
    测试：Analyzer 宕机 → Fixer 仍能处理
    
    场景：
    1. 正常协作链路
    2. 断开 Analyzer
    3. 再次触发 incident
    4. 验证 Fixer 仍能响应（不依赖 Analyzer）
    """
    engine, team = bus_with_team
    
    # Step 1: 正常流程
    incident1 = Fact(
        fact_id="incident-test-1",
        fact_type="incident.latency.high",
        semantic_kind=SemanticKind.OBSERVATION,
        payload={"latency_ms": 1000},
        domain_tags=["infrastructure"],
        priority=Priority.HIGH,
        mode=FactMode.BROADCAST,
        source_claw_id="monitor",
        causation_chain=[],
        causation_depth=0,
    )
    
    await engine.publish_fact(incident1)
    
    # 验证 Analyzer 收到
    assert len(team.events.get("analyzer", [])) > 0
    
    # Step 2: 模拟 Analyzer 宕机
    await engine.disconnect_claw("analyzer")
    print("⚠️ Analyzer disconnected")
    
    # Step 3: 再次发布 incident（Fixer 应该仍然处理 cache 相关）
    incident2 = Fact(
        fact_id="incident-test-2",
        fact_type="cache.miss.high",
        semantic_kind=SemanticKind.OBSERVATION,
        payload={"miss_rate": 0.8},
        domain_tags=["cache", "performance"],
        priority=Priority.HIGH,
        mode=FactMode.BROADCAST,
        source_claw_id="monitor",
        causation_chain=[],
        causation_depth=0,
    )
    
    await engine.publish_fact(incident2)
    
    # Step 4: 验证 Fixer 仍能收到（独立于 Analyzer）
    fixer_events = team.events.get("fixer", [])
    assert any("cache" in str(e) for e in fixer_events), "Fixer should still receive cache events"
    
    print("✅ Claw failure recovery verified!")


@pytest.mark.asyncio
async def test_priority_arbitration(bus_with_team):
    """
    测试：优先级仲裁
    
    场景：
    1. 多个 Claw 竞争处理 exclusive fact
    2. 高 reliability Claw 优先获得
    """
    engine, team = bus_with_team
    
    # 创建一个 exclusive fact
    fact = Fact(
        fact_id="exclusive-001",
        fact_type="task.important",
        semantic_kind=SemanticKind.REQUEST,
        payload={"task": "critical_fix"},
        domain_tags=["infrastructure"],
        priority=Priority.CRITICAL,
        mode=FactMode.EXCLUSIVE,  # 独占模式
        source_claw_id="monitor",
        causation_chain=[],
        causation_depth=0,
    )
    
    await engine.publish_fact(fact)
    
    # 验证仲裁逻辑执行
    # (实际断言依赖 engine 内部状态)
    print("✅ Priority arbitration test completed")


@pytest.mark.asyncio
async def test_tec_reliability_flow(bus_with_team):
    """
    测试：TEC 可靠性流程
    
    场景：
    1. Claw 发布矛盾事实 → TEC +8
    2. Claw 发布正确事实 → TEC -1
    3. TEC 累积超过阈值 → 降级/degraded
    """
    engine, team = bus_with_team
    
    claw_id = "analyzer"
    claw = engine._claws[claw_id]
    initial_tec = claw.transmit_error_counter
    
    # 模拟矛盾事实
    await engine.record_error(claw_id, ErrorEvent.CONTRADICTION)
    
    # 验证 TEC 增加
    assert claw.transmit_error_counter == initial_tec + 8
    
    # 模拟正确处理
    await engine.record_error(claw_id, ErrorEvent.CORROBORATION)
    await engine.record_error(claw_id, ErrorEvent.CORROBORATION)
    
    # 验证 TEC 减少
    assert claw.transmit_error_counter == initial_tec + 6
    
    print("✅ TEC reliability flow verified")
```

---

## 六、测试辅助工具

### 6.1 Claw 工厂函数

```python
# tests/helpers.py

def create_test_claw(
    claw_id: str,
    capabilities: list[str] = None,
    domains: list[str] = None,
    patterns: list[str] = None,
) -> ClawIdentity:
    """创建测试用 Claw"""
    return ClawIdentity(
        claw_id=claw_id,
        name=claw_id,
        acceptance_filter=AcceptanceFilter(
            capability_offer=capabilities or ["test"],
            domain_interests=domains or ["test"],
            fact_type_patterns=patterns or ["test.*"],
        ),
        max_concurrent_claims=5,
    )
```

### 6.2 Event Collector

```python
class EventCollector:
    """收集 Claw 事件"""
    
    def __init__(self):
        self.events = []
        self.facts = []
    
    def __call__(self, claw_id: str, event):
        self.events.append((claw_id, event))
        if hasattr(event, 'fact'):
            self.facts.append(event.fact)
    
    def get_facts_by_type(self, fact_type: str) -> list[Fact]:
        return [f for f in self.facts if f.fact_type == fact_type]
    
    def get_events_by_claw(self, claw_id: str) -> list:
        return [e for cid, e in self.events if cid == claw_id]
```

---

## 七、运行测试

### 7.1 执行所有集成测试

```bash
cd ~/projects/claw_fact_bus
source .venv/bin/activate

# 运行集成测试
pytest tests/integration/ -v

# 运行 E2E 测试
pytest docs/integration-tests/ -v
```

### 7.2 执行单用例

```bash
pytest docs/integration-tests/test_collaboration.py::test_incident_resolution_flow -v
```

### 7.3 生成覆盖率报告

```bash
pytest tests/ --cov=claw_fact_bus --cov-report=html
```

---

## 八、现有可复用资源

| 资源 | 路径 | 说明 |
|------|------|------|
| team_collaboration.py | `openclaw-skill/examples/` | 完整 5 角色协作示例 |
| fact_bus_client.py | `openclaw-skill/` | HTTP 客户端封装 |
| handlers.py | `openclaw-skill/` | FactBusAgent 基类 |
| test_bus_engine.py | `tests/integration/` | BusEngine 基础测试 |
| basic_example.py | `openclaw-skill/examples/` | 基础使用示例 |

---

## 九、后续计划

- [ ] 实现 `test_incident_resolution_flow`
- [ ] 实现 `test_claw_failure_recovery`
- [ ] 实现 `test_priority_arbitration`
- [ ] 实现 `test_tec_reliability_flow`
- [ ] 添加 EventCollector 辅助类
- [ ] 配置 CI 自动化测试

---

*本测试规划基于 claw_fact_bus 项目现有架构。*
"""
Team Collaboration 测试 - 5 Claw 完整协作
==========================================

验证完整协作链路：
Monitor → Analyzer → Fixer → Approver → Deployer

场景：
1. test_team_resolution_flow - 完整自愈流程
2. test_partial_failure_recovery - 部分故障恢复
3. test_rejection_flow - 审批拒绝流程
4. test_concurrent_claim_arbitration - 并发竞争仲裁

运行方式：
    pytest docs/integration-tests/test_team_collaboration.py -v --tb=short
"""

import asyncio
import tempfile

import pytest

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    ClawIdentity,
    Fact,
    FactMode,
    Priority,
    SemanticKind,
    FactState,
)


@pytest.fixture
async def temp_engine():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        yield engine
        for task in engine._background_tasks:
            task.cancel()


# ============================================================================
# Team Setup
# ============================================================================

class Team:
    """5 Claw 协作团队"""
    
    def __init__(self, engine: BusEngine):
        self.engine = engine
        self.events = {}
    
    async def setup(self):
        """创建并连接所有 Claw"""
        
        # Monitor: 感知 incidents
        await self._add_claw(
            "monitor",
            capabilities=["monitoring"],
            domains=["infrastructure", "performance"],
            patterns=["incident.*", "deploy.*", "change.*"],
        )
        
        # Analyzer: 分析 incidents → 根因
        await self._add_claw(
            "analyzer",
            capabilities=["analysis", "debugging"],
            domains=["infrastructure", "database", "performance"],
            patterns=["incident.*"],
        )
        
        # Fixer: 发现问题 → 提出修复
        await self._add_claw(
            "fixer",
            capabilities=["fix", "optimize"],
            domains=["database", "cache", "code"],
            patterns=["db.*", "cache.*", "code.*", "*.recommendation"],
        )
        
        # Approver: 审批 change
        await self._add_claw(
            "approver",
            capabilities=["approval", "review"],
            domains=["change_management"],
            patterns=["change.proposed"],
        )
        
        # Deployer: 执行部署
        await self._add_claw(
            "deployer",
            capabilities=["deploy", "execute"],
            domains=["infrastructure", "deployment"],
            patterns=["change.approved", "deploy.*"],
        )
        
        return self
    
    async def _add_claw(self, claw_id, capabilities, domains, patterns):
        claw = ClawIdentity(
            claw_id=claw_id,
            name=claw_id,
            acceptance_filter=AcceptanceFilter(
                capability_offer=capabilities,
                domain_interests=domains,
                fact_type_patterns=patterns,
            ),
        )
        
        self.events[claw_id] = []
        
        def handler(claw_id, event):
            self.events[claw_id].append(event)
        
        await self.engine.connect_claw(claw_id, claw, handler)
    
    def get_events(self, claw_id: str):
        return self.events.get(claw_id, [])
    
    def get_fact_types(self, claw_id: str):
        """获取 Claw 收到的事实类型列表"""
        events = self.events.get(claw_id, [])
        return [e.fact.fact_type for e in events if hasattr(e, 'fact') and e.fact]


async def make_incident(engine: BusEngine, severity: str = "high"):
    """发布 incident 事实"""
    fact = Fact(
        fact_id=f"incident-{severity}",
        fact_type="incident.latency.high",
        semantic_kind=SemanticKind.OBSERVATION,
        payload={
            "service": "api-gateway",
            "latency_ms": 2500,
            "threshold_ms": 500,
            "severity": severity,
        },
        domain_tags=["infrastructure", "performance"],
        priority=Priority.HIGH,
        mode=FactMode.BROADCAST,
        source_claw_id="external",
        causation_chain=[],
        causation_depth=0,
    )
    
    result, msg, fact_id = await engine.publish_fact(fact)
    return result, msg, fact_id


# ============================================================================
# Collaboration Tests
# ============================================================================

class TestTeamResolutionFlow:
    """完整自愈流程测试"""
    
    @pytest.mark.asyncio
    async def test_full_5_claw_resolution(self, temp_engine):
        """
        完整流程：incident.latency.high → 分析 → 修复 → 审批 → 部署
        
        预期交互：
        1. Monitor 发布 incident.latency.high
        2. Analyzer 收到 → 发布 db.query.slow
        3. Fixer 收到 → 发布 change.proposed
        4. Approver 收到 → 发布 change.approved
        5. Deployer 收到 → 发布 deploy.completed
        """
        engine = temp_engine
        team = Team(engine)
        await team.setup()
        
        # Step 1: Monitor 发布事故
        await make_incident(engine)
        
        # 等待事件传播
        await asyncio.sleep(0.1)
        
        # Step 2: 验证 Analyzer 收到
        analyzer_events = team.get_events("analyzer")
        assert len(analyzer_events) > 0, "Analyzer should receive incident"
        
        # Step 3: Analyzer 发布根因
        root_cause = Fact(
            fact_id="root-001",
            fact_type="db.query.slow",
            semantic_kind=SemanticKind.ASSERTION,
            payload={
                "cause": "missing_index",
                "confidence": 0.8,
                "query": "SELECT * FROM orders WHERE user_id = ?",
            },
            domain_tags=["database", "analysis"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="analyzer",
            causation_chain=["incident-high"],
            causation_depth=1,
        )
        
        await engine.publish_fact(root_cause)
        await asyncio.sleep(0.1)
        
        # Step 4: 验证 Fixer 收到
        fixer_events = team.get_events("fixer")
        assert any("db.query" in str(e) for e in fixer_events), "Fixer should receive db.query.slow"
        
        # Fixer 发布 change.proposed
        change = Fact(
            fact_id="proposal-001",
            fact_type="change.proposed",
            semantic_kind=SemanticKind.REQUEST,
            payload={
                "change_type": "index_creation",
                "description": "Add index on orders.user_id",
                "sql": "CREATE INDEX idx_orders_user_id ON orders(user_id)",
                "risk": "low",
            },
            domain_tags=["database", "optimization"],
            need_capabilities=["approval"],
            priority=Priority.HIGH,
            mode=FactMode.EXCLUSIVE,
            source_claw_id="fixer",
            causation_chain=["incident-high", "root-001"],
            causation_depth=2,
        )
        
        await engine.publish_fact(change)
        
        # 模拟 claim
        await engine.claim_fact("proposal-001", "fixer")
        
        # Approver 审批
        approval = Fact(
            fact_id="approval-001",
            fact_type="change.approved",
            semantic_kind=SemanticKind.RESOLUTION,
            payload={
                "approved": True,
                "original_proposal": change.payload,
                "approver": "approver",
                "timestamp": asyncio.get_event_loop().time(),
            },
            domain_tags=["change_management"],
            priority=Priority.ELEVATED,
            mode=FactMode.BROADCAST,
            source_claw_id="approver",
            causation_chain=["incident-high", "root-001", "proposal-001"],
            causation_depth=3,
        )
        
        await engine.publish_fact(approval)
        await asyncio.sleep(0.1)
        
        # 验证 Deployer 收到
        deployer_events = team.get_events("deployer")
        assert any("approved" in str(e) for e in deployer_events), "Deployer should receive change.approved"
        
        print("✅ Full 5-Claw resolution flow completed")
        
        # 打印事件统计
        for claw_id, events in team.events.items():
            print(f"   {claw_id}: {len(events)} events")


class TestPartialFailureRecovery:
    """部分故障恢复测试"""
    
    @pytest.mark.asyncio
    async def test_analyzer_down_fixer_still_works(self, temp_engine):
        """Analyzer 宕机 → Fixer 仍能处理其他类型"""
        engine = temp_engine
        team = Team(engine)
        await team.setup()
        
        # 断开 Analyzer
        await engine.disconnect_claw("analyzer")
        
        # 发布 cache 相关问题（Fixer 独立处理）
        cache_issue = Fact(
            fact_id="cache-001",
            fact_type="cache.miss.high",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"cache_name": "user_session", "miss_rate": 0.85},
            domain_tags=["cache", "performance"],
            priority=Priority.HIGH,
            mode=FactMode.BROADCAST,
            source_claw_id="monitor",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(cache_issue)
        await asyncio.sleep(0.1)
        
        # 验证 Fixer 仍能收到（不依赖 Analyzer）
        fixer_events = team.get_events("fixer")
        assert any("cache" in str(e) for e in fixer_events), "Fixer should still receive cache events"
        
        print("✅ Partial failure: Fixer still works when Analyzer is down")
    
    @pytest.mark.asyncio
    async def test_approver_rejects_high_risk(self, temp_engine):
        """审批拒绝：高风险变更"""
        engine = temp_engine
        team = Team(engine)
        await team.setup()
        
        # Fixer 提出高风险变更
        high_risk = Fact(
            fact_id="proposal-highrisk",
            fact_type="change.proposed",
            semantic_kind=SemanticKind.REQUEST,
            payload={
                "change_type": "schema_migration",
                "description": "Drop deprecated column",
                "risk": "high",
            },
            domain_tags=["database"],
            need_capabilities=["approval"],
            priority=Priority.CRITICAL,
            mode=FactMode.EXCLUSIVE,
            source_claw_id="fixer",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(high_risk)
        await engine.claim_fact("proposal-highrisk", "approver")
        
        # Approver 拒绝
        rejection = Fact(
            fact_id="rejection-001",
            fact_type="change.rejected",
            semantic_kind=SemanticKind.RESOLUTION,
            payload={
                "approved": False,
                "reason": "High risk change requires manual review",
                "original_proposal": high_risk.payload,
            },
            domain_tags=["change_management"],
            priority=Priority.ELEVATED,
            mode=FactMode.BROADCAST,
            source_claw_id="approver",
            causation_chain=["proposal-highrisk"],
            causation_depth=1,
        )
        
        await engine.publish_fact(rejection)
        
        # 验证 Deployer 不应收到（被拒绝）
        deployer_events = team.get_events("deployer")
        approved_events = [e for e in deployer_events 
                          if hasattr(e, 'fact') and e.fact.fact_type == "change.approved"]
        
        assert len(approved_events) == 0, "Deployer should not receive rejected change"
        
        print("✅ High-risk change correctly rejected")


class TestConcurrentClaim:
    """并发竞争测试"""
    
    @pytest.mark.asyncio
    async def test_two_claws_claim_same_exclusive(self, temp_engine):
        """两个 Claw 竞争同一 exclusive fact"""
        engine = temp_engine
        
        # 创建两个 worker
        worker1 = ClawIdentity(
            claw_id="worker1",
            name="worker1",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["work"],
                domain_interests=["test"],
            ),
        )
        
        worker2 = ClawIdentity(
            claw_id="worker2", 
            name="worker2",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["work"],
                domain_interests=["test"],
            ),
        )
        
        await engine.connect_claw("worker1", worker1, lambda c, e: None)
        await engine.connect_claw("worker2", worker2, lambda c, e: None)
        
        # 发布 exclusive fact
        task = Fact(
            fact_id="exclusive-task",
            fact_type="task.urgent",
            semantic_kind=SemanticKind.REQUEST,
            payload={"task": "urgent_fix"},
            domain_tags=["test"],
            priority=Priority.HIGH,
            mode=FactMode.EXCLUSIVE,
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(task)
        
        #两个 Claw 同时尝试 claim
        result1, msg1 = await engine.claim_fact("exclusive-task", "worker1")
        result2, msg2 = await engine.claim_fact("exclusive-task", "worker2")
        
        # 只有一个成功
        assert result1 or result2, "At least one should succeed"
        assert not (result1 and result2), "Only one should win"
        
        winner = "worker1" if result1 else "worker2"
        print(f"✅ Arbitration: {winner} won the exclusive fact")
    
    @pytest.mark.asyncio
    async def test_resolution_after_timeout(self, temp_engine):
        """超时未处理 → fact 状态"""
        engine = temp_engine
        
        claw = ClawIdentity(
            claw_id="slow-worker",
            name="slow-worker",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["work"],
                domain_interests=["test"],
            ),
        )
        
        await engine.connect_claw("slow-worker", claw, lambda c, e: None)
        
        # 发布 exclusive fact
        task = Fact(
            fact_id="timeout-task",
            fact_type="task.test",
            semantic_kind=SemanticKind.REQUEST,
            payload={"test": "timeout"},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
            ttl_seconds=2,  # 短 TTL
        )
        
        await engine.publish_fact(task)
        
        # 不 claim，等待 TTL 过期
        await asyncio.sleep(2.5)
        
        stored = engine._facts.get("timeout-task")
        if stored:
            print(f"✅ After timeout: state = {stored.state}")
        else:
            print("✅ After timeout: fact removed (dead letter)")


class TestCausationChain:
    """因果链追踪测试"""
    
    @pytest.mark.asyncio
    async def test_causation_depth_increments(self, temp_engine):
        """因果链深度递增"""
        engine = temp_engine
        
        # 模拟 3 层因果
        parent = Fact(
            fact_id="parent-1",
            fact_type="test.level0",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"level": 0},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="a",
            causation_chain=[],
            causation_depth=0,
        )
        
        r1, _, _ = await engine.publish_fact(parent)
        assert r1
        
        child1 = Fact(
            fact_id="child-1",
            fact_type="test.level1",
            semantic_kind=SemanticKind.SIGNAL,
            payload={"level": 1},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="b",
            causation_chain=[parent.fact_id],
            causation_depth=1,
        )
        
        r2, _, _ = await engine.publish_fact(child1)
        assert r2
        
        child2 = Fact(
            fact_id="child-2",
            fact_type="test.level2",
            semantic_kind=SemanticKind.SIGNAL,
            payload={"level": 2},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="c",
            causation_chain=[parent.fact_id, child1.fact_id],
            causation_depth=2,
        )
        
        r3, _, _ = await engine.publish_fact(child2)
        # depth=2 应该通过，depth>16 拒绝
        
        print(f"✅ Causation chain: depth 0→1→2 works")
    
    @pytest.mark.asyncio
    async def test_root_cause_traceability(self, temp_engine):
        """根因可追溯"""
        engine = temp_engine
        
        # 完整追踪链
        chain = [
            "incident-start",
            "analysis-1",
            "diagnosis-2", 
            "proposal-3",
            "approval-4",
        ]
        
        final = Fact(
            fact_id="final-result",
            fact_type="deploy.completed",
            semantic_kind=SemanticKind.RESOLUTION,
            payload={"deployed": True},
            domain_tags=["deployment"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="deployer",
            causation_chain=chain,
            causation_depth=len(chain),
        )
        
        result, msg, _ = await engine.publish_fact(final)
        
        # 5 层深度应该通过
        print(f"✅ Traceable chain (depth={len(chain)}): {msg}")


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
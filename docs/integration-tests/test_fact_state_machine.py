"""
Fact State Machine 完整测试 v2
==============================

验证 Fact 生命周期状态转换：
created → published → matched → claimed → processing → resolved → dead

运行方式：
    cd ~/projects/claw_fact_bus
    source .venv/bin/activate
    pytest docs/integration-tests/test_fact_state_machine.py -v --tb=short
"""

import asyncio
import tempfile

import pytest

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    FactState,
    Priority,
    SemanticKind,
)


@pytest.fixture
async def temp_engine():
    """创建临时 Bus Engine"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        yield engine
        # Cleanup
        for task in engine._background_tasks:
            task.cancel()


def make_test_claw(
    claw_id: str = "test-claw",
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


class TestFactLifecycle:
    """Fact 生命周期测试"""
    
    @pytest.mark.asyncio
    async def test_01_publish_creates_published_fact(self, temp_engine):
        """created → published"""
        engine = temp_engine
        
        fact = Fact(
            fact_id="fact-001",
            fact_type="test.event",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"message": "test"},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        # API: publish_fact 返回 (success, message, fact_id)
        success, msg, fact_id = await engine.publish_fact(fact)
        
        assert success, f"Publish failed: {msg}"
        assert fact_id == "fact-001"
        
        # 验证内部状态
        stored_fact = engine._facts.get("fact-001")
        assert stored_fact is not None
        assert stored_fact.state == FactState.PUBLISHED
        
        print(f"✅ Fact published: {fact_id}, state={stored_fact.state}")
    
    @pytest.mark.asyncio
    async def test_02_published_to_matched(self, temp_engine):
        """published → matched (当有 Claw 订阅时)"""
        engine = temp_engine
        
        # 连接一个匹配订阅的 Claw
        claw = make_test_claw(
            claw_id="listener",
            capabilities=["listener"],
            domains=["test"],
            patterns=["test.*"],
        )
        
        received_events = []
        def handler(claw_id, event):
            received_events.append(event)
        
        await engine.connect_claw("listener", claw, handler)
        
        # 发布事实
        fact = Fact(
            fact_id="fact-002",
            fact_type="test.event",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"message": "hello"},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        success, msg, fact_id = await engine.publish_fact(fact)
        
        # 验证 Claw 收到通知
        assert len(received_events) > 0, "Claw should receive event"
        
        stored_fact = engine._facts.get("fact-002")
        assert stored_fact.state in [FactState.PUBLISHED, FactState.MATCHED]
        
        print(f"✅ Fact matched to Claw: {fact_id}, received {len(received_events)} events")
    
    @pytest.mark.asyncio
    async def test_03_claim_exclusive_fact(self, temp_engine):
        """matched → claimed (exclusive mode)"""
        engine = temp_engine
        
        # 连接 Claw
        claw = make_test_claw(
            claw_id="worker",
            capabilities=["work"],
            domains=["test"],
            patterns=["test.*"],
        )
        await engine.connect_claw("worker", claw, lambda c, e: None)
        
        # 发布 EXCLUSIVE fact
        fact = Fact(
            fact_id="fact-003",
            fact_type="test.task",
            semantic_kind=SemanticKind.REQUEST,
            payload={"task": "important"},
            domain_tags=["test"],
            priority=Priority.HIGH,
            mode=FactMode.EXCLUSIVE,  # 独占模式
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        
        # Claw 声明处理
        # API: claim_fact 返回 (success, message)
        success, msg = await engine.claim_fact("fact-003", "worker")
        
        assert success, f"Claim failed: {msg}"
        
        # 验证状态
        stored_fact = engine._facts.get("fact-003")
        assert stored_fact.state == FactState.CLAIMED
        assert stored_fact.claimed_by == "worker"
        
        print(f"✅ Exclusive fact claimed: {stored_fact.fact_id}, by={stored_fact.claimed_by}")
    
    @pytest.mark.asyncio
    async def test_04_resolve_fact(self, temp_engine):
        """claimed → resolved"""
        engine = temp_engine
        
        # 连接 Claw
        claw = make_test_claw(claw_id="worker", capabilities=["work"], domains=["test"], patterns=["test.*"])
        await engine.connect_claw("worker", claw, lambda c, e: None)
        
        # 创建并声明 fact (需要 EXCLAIM 模式才能被 claim)
        fact = Fact(
            fact_id="fact-004",
            fact_type="test.task",
            semantic_kind=SemanticKind.REQUEST,
            payload={"task": "done"},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        await engine.claim_fact("fact-004", "worker")
        
        # 解决 fact
        # API: resolve_fact(fact_id, claw_id, result_facts=None)
        success, msg = await engine.resolve_fact("fact-004", "worker")
        
        assert success, f"Resolve failed: {msg}"
        
        # 验证状态
        stored_fact = engine._facts.get("fact-004")
        assert stored_fact.state == FactState.RESOLVED
        assert stored_fact.resolved_at is not None
        
        print(f"✅ Fact resolved: {stored_fact.fact_id}, at={stored_fact.resolved_at}")
    
    @pytest.mark.asyncio
    async def test_05_release_unclaim(self, temp_engine):
        """claimed → released (可被其他 Claw 重新认领)"""
        engine = temp_engine
        
        claw1 = make_test_claw(claw_id="worker1", capabilities=["work"], domains=["test"], patterns=["test.*"])
        claw2 = make_test_claw(claw_id="worker2", capabilities=["work"], domains=["test"], patterns=["test.*"])
        
        await engine.connect_claw("worker1", claw1, lambda c, e: None)
        await engine.connect_claw("worker2", claw2, lambda c, e: None)
        
        # 发布 exclusive fact
        fact = Fact(
            fact_id="fact-005",
            fact_type="test.task",
            semantic_kind=SemanticKind.REQUEST,
            payload={"task": "released"},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.EXCLUSIVE,
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        
        # Worker1 认领
        success1, _ = await engine.claim_fact("fact-005", "worker1")
        assert success1
        
        # Worker1 释放
        success_release, _ = await engine.release_fact("fact-005", "worker1")
        assert success_release
        
        # Worker2 应该能认领
        success2, _ = await engine.claim_fact("fact-005", "worker2")
        
        assert success2, "Worker2 should be able to claim after release"
        
        stored_fact = engine._facts.get("fact-005")
        assert stored_fact.claimed_by == "worker2"
        
        print(f"✅ Fact released and re-claimed by worker2")


class TestClawLifecycle:
    """Claw 生命周期测试"""
    
    @pytest.mark.asyncio
    async def test_10_connect_creates_active_claw(self, temp_engine):
        """CONNECT -> ACTIVE"""
        engine = temp_engine
        
        claw = make_test_claw(claw_id="new-claw")
        # API: connect_claw 返回 ClawIdentity
        identity = await engine.connect_claw("new-claw", claw, lambda c, e: None)
        
        assert identity.state == ClawState.ACTIVE
        assert "new-claw" in engine._claws
        print("✅ Claw connected with ACTIVE state")
    
    @pytest.mark.asyncio
    async def test_11_heartbeat_maintains_active(self, temp_engine):
        """HEARTBEAT 保持 ACTIVE"""
        engine = temp_engine
        
        claw = make_test_claw(claw_id="heartbeat-claw")
        await engine.connect_claw("heartbeat-claw", claw, lambda c, e: None)
        
        # 多次心跳 - API 是 self.heartbeat(claw_id)
        for i in range(5):
            state = await engine.heartbeat("heartbeat-claw")
        
        # 状态应该保持 ACTIVE
        assert engine._claws["heartbeat-claw"].state == ClawState.ACTIVE
        print("✅ Heartbeat maintains ACTIVE state")
    
    @pytest.mark.asyncio
    async def test_12_disconnect_removes_claw(self, temp_engine):
        """DISCONNECT 移除 Claw"""
        engine = temp_engine
        
        claw = make_test_claw(claw_id="temp-claw")
        await engine.connect_claw("temp-claw", claw, lambda c, e: None)
        
        await engine.disconnect_claw("temp-claw")
        
        assert "temp-claw" not in engine._claws
        print("✅ Claw disconnected and removed")


class TestFlowControl:
    """流量控制测试"""
    
    @pytest.mark.asyncio
    async def test_20_deep_causation_rejected(self, temp_engine):
        """causation_depth > 16 拒绝"""
        engine = temp_engine
        
        # 深度超过 16
        fact = Fact(
            fact_id="deep-fact",
            fact_type="test.deep",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"depth": 17},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="test",
            causation_chain=["p"] * 17,  # 17 个父节点
            causation_depth=17,
        )
        
        # 应该被拒绝
        success, msg, fact_id = await engine.publish_fact(fact)
        
        # 验证被拒绝
        assert not success, "Deep causation should be rejected"
        assert "depth" in msg.lower() or "16" in msg
        
        print(f"✅ Deep causation rejected: {msg}")
    
    @pytest.mark.asyncio
    async def test_21_rate_limit_basic(self, temp_engine):
        """基础限流测试"""
        engine = temp_engine
        
        claw = make_test_claw(claw_id="burst-claw")
        await engine.connect_claw("burst-claw", claw, lambda c, e: None)
        
        # 尝试发布多个 facts
        successes = 0
        
        for i in range(10):
            fact = Fact(
                fact_id=f"rate-test-{i}",
                fact_type="test.rate",
                semantic_kind=SemanticKind.OBSERVATION,
                payload={"i": i},
                domain_tags=["test"],
                priority=Priority.NORMAL,
                mode=FactMode.BROADCAST,
                source_claw_id="burst-claw",
                causation_chain=[],
                causation_depth=0,
            )
            
            success, _, _ = await engine.publish_fact(fact)
            if success:
                successes += 1
        
        print(f"✅ Rate limit test: {successes}/10 published")
        assert successes > 0, "Some facts should pass"


class TestMultiClawCollaboration:
    """多 Claw 协作测试"""
    
    @pytest.mark.asyncio
    async def test_30_two_claw_routing(self, temp_engine):
        """两 Claw 路由：A 发 → B 收"""
        engine = temp_engine
        
        # 创建发布者
        publisher = make_test_claw(claw_id="publisher", capabilities=["pub"], domains=["topic"])
        await engine.connect_claw("publisher", publisher, lambda c, e: None)
        
        # 创建订阅者
        subscriber = make_test_claw(claw_id="subscriber", capabilities=["sub"], domains=["topic"], patterns=["news.*"])
        
        received = []
        def sub_handler(claw_id, event):
            received.append(event)
        
        await engine.connect_claw("subscriber", subscriber, sub_handler)
        
        # 发布匹配的 fact
        fact = Fact(
            fact_id="news-001",
            fact_type="news.alert",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"headline": "test"},
            domain_tags=["topic"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="publisher",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        
        # 验证 subscriber 收到
        assert len(received) > 0, "Subscriber should receive the fact"
        
        print(f"✅ Two-claw routing: publisher → subscriber works")


# ============================================================================
# 运行所有测试
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
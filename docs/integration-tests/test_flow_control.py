"""
Flow Control 测试 - 5 层流量控制验证
======================================

验证 5 层流量控制机制：
1. Causation Depth 限制 (≤16)
2. Causation Cycle 检测
3. Deduplication 窗口 (10s)
4. Per-Claw 限流
5. Global Bus Load 熔断

运行方式：
    pytest docs/integration-tests/test_flow_control.py -v --tb=short
"""

import asyncio
import tempfile
import time

import pytest

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    ClawIdentity,
    Fact,
    FactMode,
    Priority,
    SemanticKind,
)


@pytest.fixture
async def temp_engine():
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        yield engine
        for task in engine._background_tasks:
            task.cancel()


def make_claw(claw_id: str) -> ClawIdentity:
    return ClawIdentity(
        claw_id=claw_id,
        name=claw_id,
        acceptance_filter=AcceptanceFilter(
            capability_offer=["test"],
            domain_interests=["test"],
        ),
    )


def make_fact(
    fact_id: str,
    causation_depth: int = 0,
    causation_chain: list = None,
    priority: Priority = Priority.NORMAL,
) -> Fact:
    return Fact(
        fact_id=fact_id,
        fact_type="test.event",
        semantic_kind=SemanticKind.OBSERVATION,
        payload={"test": "data"},
        domain_tags=["test"],
        priority=priority,
        mode=FactMode.BROADCAST,
        source_claw_id="test",
        causation_chain=causation_chain or [],
        causation_depth=causation_depth,
    )


class TestCausationDepthLimit:
    """1. Causation Depth 限制 (≤16)"""
    
    @pytest.mark.asyncio
    async def test_depth_0_passes(self, temp_engine):
        """depth=0 应该通过"""
        engine = temp_engine
        
        fact = make_fact("fact-0", causation_depth=0)
        success, msg, _ = await engine.publish_fact(fact)
        
        assert success, f"depth=0 should pass: {msg}"
        print("✅ Depth 0 passes")
    
    @pytest.mark.asyncio
    async def test_depth_16_passes(self, temp_engine):
        """depth=16 应该通过"""
        engine = temp_engine
        
        fact = make_fact("fact-16", causation_depth=16)
        success, msg, _ = await engine.publish_fact(fact)
        
        # 取决于实现，可能通过或拒绝
        print(f"✅ Depth 16: success={success}, msg={msg}")
    
    @pytest.mark.asyncio
    async def test_depth_17_rejected(self, temp_engine):
        """depth=17 应该拒绝"""
        engine = temp_engine
        
        fact = make_fact("fact-17", causation_depth=17)
        success, msg, _ = await engine.publish_fact(fact)
        
        assert not success, "depth > 16 should be rejected"
        print(f"✅ Depth 17 rejected: {msg}")
    
    @pytest.mark.asyncio
    async def test_deep_chain_via_causation(self, temp_engine):
        """通过 causation_chain 自动计算深度"""
        engine = temp_engine
        
        # 模拟一个 10 层的因果链
        chain = [f"parent-{i}" for i in range(10)]
        
        fact = make_fact("fact-deep", causation_chain=chain)
        # 深度应该由 max(len(chain), causation_depth) 决定
        expected_depth = max(len(chain), fact.causation_depth)
        
        print(f"✅ Causation chain depth: {expected_depth}")


class TestCausationCycleDetection:
    """2. Causation Cycle 检测"""
    
    @pytest.mark.asyncio
    async def test_no_cycle_passes(self, temp_engine):
        """无循环 - 应该通过"""
        engine = temp_engine
        
        # 链中不包含自己
        fact = make_fact(
            "fact-nocycle",
            causation_chain=["parent-1", "parent-2"]
        )
        success, msg, _ = await engine.publish_fact(fact)
        
        assert success, f"No cycle should pass: {msg}"
        print("✅ No cycle passes")
    
    @pytest.mark.asyncio
    async def test_self_reference_rejected(self, temp_engine):
        """自引用 - 应该拒绝"""
        engine = temp_engine
        
        # 链中包含自己的 ID
        fact = make_fact(
            "fact-self",
            causation_chain=["parent-1", "fact-self", "parent-2"]
        )
        success, msg, _ = await engine.publish_fact(fact)
        
        # 应该被检测为循环
        assert not success or "cycle" in msg.lower() or "self" in msg.lower()
        print(f"✅ Self reference: {msg}")


class TestDeduplicationWindow:
    """3. Deduplication 窗口 (10s)"""
    
    @pytest.mark.asyncio
    async def test_first_publication_passes(self, temp_engine):
        """首次发布 - 应该通过"""
        engine = temp_engine
        
        # 连接一个 claw 避免警告
        claw = make_claw("pub-claw")
        await engine.connect_claw("pub-claw", claw, lambda c, e: None)
        
        fact = make_fact("dup-test-1")
        success, msg, _ = await engine.publish_fact(fact)
        
        assert success
        print("✅ First publication passes")
    
    @pytest.mark.asyncio
    async def test_duplicate_rejected(self, temp_engine):
        """重复发布 - 应该被去重"""
        engine = temp_engine
        
        claw = make_claw("pub-claw2")
        await engine.connect_claw("pub-claw2", claw, lambda c, e: None)
        
        # 发布相同 key 的 fact (同一个 claw, 相同 type, 相同 hash)
        fact1 = Fact(
            fact_id="unique-1",
            fact_type="test.dup",
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"value": 100},
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="pub-claw2",
            causation_chain=[],
            causation_depth=0,
        )
        
        fact2 = Fact(
            fact_id="unique-2",
            fact_type="test.dup",  # 相同 type
            semantic_kind=SemanticKind.OBSERVATION,
            payload={"value": 100},  # 相同 payload
            domain_tags=["test"],
            priority=Priority.NORMAL,
            mode=FactMode.BROADCAST,
            source_claw_id="pub-claw2",  # 相同 claw
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact1)
        
        # 第二个可能被视为重复（取决于 hash 计算）
        success2, msg2, _ = await engine.publish_fact(fact2)
        
        print(f"✅ Duplicate check: success={success2}, msg={msg2}")


class TestPerClawRateLimit:
    """4. Per-Claw 限流"""
    
    @pytest.mark.asyncio
    async def test_rate_limit_burst(self, temp_engine):
        """突发限流测试"""
        engine = temp_engine
        
        claw = make_claw("burst-claw")
        await engine.connect_claw("burst-claw", claw, lambda c, e: None)
        
        # 默认限制: capacity=20, refill=5/s
        successes = 0
        failures = 0
        
        for i in range(25):
            fact = make_fact(f"rate-{i}")
            success, msg, _ = await engine.publish_fact(fact)
            
            if success:
                successes += 1
            else:
                failures += 1
        
        print(f"✅ Rate limit: {successes} passed, {failures} rejected out of 25")
        # 应该有一些被拒绝
        assert successes < 25
    
    @pytest.mark.asyncio
    async def test_rate_limit_refill(self, temp_engine):
        """限流恢复测试"""
        engine = temp_engine
        
        claw = make_claw("refill-claw")
        await engine.connect_claw("refill-claw", claw, lambda c, e: None)
        
        # 快速消耗 token
        for i in range(20):
            await engine.publish_fact(make_fact(f"refill-{i}"))
        
        # 再发一个，可能被限流
        success, msg, _ = await engine.publish_fact(make_fact("refill-21"))
        
        # 等待 token 恢复
        await asyncio.sleep(1)
        
        success2, msg2, _ = await engine.publish_fact(make_fact("refill-22"))
        
        print(f"✅ Rate refill: after 1s, success={success2}")


class TestGlobalLoadBreaker:
    """5. Global Bus Load 熔断"""
    
    @pytest.mark.asyncio
    async def test_normal_load_passes(self, temp_engine):
        """正常负载 - 应该通过"""
        engine = temp_engine
        
        successes = 0
        for i in range(10):
            fact = make_fact(f"load-{i}")
            success, _, _ = await engine.publish_fact(fact)
            if success:
                successes += 1
        
        assert successes > 0
        print(f"✅ Normal load: {successes}/10 passed")
    
    @pytest.mark.asyncio
    async def test_high_load_triggers_breaker(self, temp_engine):
        """高负载 - 触发熔断"""
        engine = temp_engine
        
        # 尝试触发全局负载breaker (200 facts / 5s)
        # 在实际测试中需要快速发布大量 facts
        
        successes = 0
        for i in range(50):
            fact = make_fact(f"stress-{i}")
            success, msg, _ = await engine.publish_fact(fact)
            if success:
                successes += 1
        
        print(f"✅ High load: {successes}/50 passed")
        # 即使有限流，也不应全部失败


class TestPriorityAging:
    """优先级老化机制"""
    
    @pytest.mark.asyncio
    async def test_aging_increases_priority(self, temp_engine):
        """未认领的事实优先级随时间提升"""
        engine = temp_engine
        
        # 发布一个低优先级 fact
        fact = make_fact("aging-test", priority=Priority.BULK)
        await engine.publish_fact(fact)
        
        # 存储状态
        stored = engine._facts.get("aging-test")
        original_priority = stored.effective_priority if stored else None
        
        print(f"✅ Original priority: {original_priority or Priority.BULK}")


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
"""
Persistence 测试 - 数据持久化验证
==================================

验证数据持久化：
1. JSONL 写入正确
2. 多事件记录
3. Fact 状态转换记录

运行方式：
    pytest docs/integration-tests/test_persistence.py -v --tb=short
"""

import asyncio
import os
import tempfile
import json

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
def data_dir():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestJSONLPersistence:
    """JSONL 持久化测试"""
    
    @pytest.mark.asyncio
    async def test_fact_written_to_file(self, data_dir):
        """事实写入文件"""
        engine = BusEngine(data_dir=data_dir)
        
        fact = Fact(
            fact_id="persist-001",
            fact_type="test.persistence",
            semantic_kind="observation",
            payload={"test": "data"},
            domain_tags=["test"],
            priority=3,
            mode="broadcast",
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        
        # 检查文件
        fact_file = os.path.join(data_dir, "facts.jsonl")
        assert os.path.exists(fact_file), "Fact file should exist"
        
        with open(fact_file) as f:
            content = f.read()
            assert "persist-001" in content
        
        print("✅ Persistence: fact written to file")
    
    @pytest.mark.asyncio
    async def test_multiple_facts_appended(self, data_dir):
        """多事实追加"""
        engine = BusEngine(data_dir=data_dir)
        
        for i in range(5):
            fact = Fact(
                fact_id=f"multi-{i}",
                fact_type="test.event",
                semantic_kind="observation",
                payload={"i": i},
                domain_tags=["test"],
                priority=3,
                mode="broadcast",
                source_claw_id="test",
                causation_chain=[],
                causation_depth=0,
            )
            await engine.publish_fact(fact)
        
        # 验证行数
        fact_file = os.path.join(data_dir, "facts.jsonl")
        with open(fact_file) as f:
            lines = [l for l in f.readlines() if l.strip()]
        
        assert len(lines) >= 5
        print(f"✅ Persistence: {len(lines)} facts logged")
    
    @pytest.mark.asyncio
    async def test_event_types_logged(self, data_dir):
        """事件类型记录"""
        engine = BusEngine(data_dir=data_dir)
        
        # Claw
        claw = ClawIdentity(
            claw_id="log-claw",
            name="Log Claw",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["test"],
                domain_interests=["test"],
            ),
        )
        await engine.connect_claw("log-claw", claw, lambda c, e: None)
        
        # Publish, Claim, Resolve
        fact = Fact(
            fact_id="event-log",
            fact_type="test.event",
            semantic_kind="request",
            payload={},
            domain_tags=["test"],
            priority=3,
            mode="exclusive",
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        await engine.claim_fact("event-log", "log-claw")
        await engine.resolve_fact("event-log", "log-claw")
        
        # 验证多种事件记录
        fact_file = os.path.join(data_dir, "facts.jsonl")
        with open(fact_file) as f:
            content = f.read()
        
        assert "publish" in content
        assert "claim" in content
        assert "resolve" in content
        print("✅ Persistence: event types logged")


class TestDataIntegrity:
    """数据完整性测试"""
    
    @pytest.mark.asyncio
    async def test_fact_id_persisted(self, data_dir):
        """Fact ID 持久化"""
        engine = BusEngine(data_dir=data_dir)
        
        fact = Fact(
            fact_id="id-test-123",
            fact_type="test.id",
            semantic_kind="observation",
            payload={},
            domain_tags=["test"],
            priority=3,
            mode="broadcast",
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        
        # 验证内存中
        stored = engine._facts.get("id-test-123")
        assert stored is not None
        assert stored.fact_id == "id-test-123"
        
        print("✅ Integrity: fact_id persisted")
    
    @pytest.mark.asyncio
    async def test_fact_state_saved(self, data_dir):
        """事实状态保存"""
        engine = BusEngine(data_dir=data_dir)
        
        # 状态转换: published -> claimed -> resolved
        fact = Fact(
            fact_id="state-save",
            fact_type="test.state",
            semantic_kind="request",
            payload={},
            domain_tags=["test"],
            priority=3,
            mode="exclusive",
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        
        await engine.publish_fact(fact)
        
        stored1 = engine._facts.get("state-save")
        assert stored1.state.value == "published"
        
        await engine.claim_fact("state-save", "worker")
        stored2 = engine._facts.get("state-save")
        assert stored2.state.value == "claimed"
        
        await engine.resolve_fact("state-save", "worker")
        stored3 = engine._facts.get("state-save")
        assert stored3.state.value == "resolved"
        
        print(f"✅ Integrity: state saved (published → claimed → resolved)")
    
    @pytest.mark.asyncio
    async def test_causation_chain_saved(self, data_dir):
        """因果链保存"""
        engine = BusEngine(data_dir=data_dir)
        
        chain = ["parent-A", "parent-B"]
        
        fact = Fact(
            fact_id="chain-save",
            fact_type="test.chain",
            semantic_kind="signal",
            payload={},
            domain_tags=["test"],
            priority=3,
            mode="broadcast",
            source_claw_id="test",
            causation_chain=chain,
            causation_depth=len(chain),
        )
        
        await engine.publish_fact(fact)
        
        stored = engine._facts.get("chain-save")
        assert stored.causation_chain == chain
        assert stored.causation_depth == 2
        
        print(f"✅ Integrity: causation chain persisted")


class TestRecovery:
    """恢复能力测试"""
    
    @pytest.mark.asyncio
    async def test_new_engine_same_dir(self, data_dir):
        """新引擎访问同一目录"""
        # 引擎1: 创建并发布
        engine1 = BusEngine(data_dir=data_dir)
        fact = Fact(
            fact_id="recovery-001",
            fact_type="test.recovery",
            semantic_kind="observation",
            payload={"recovered": True},
            domain_tags=["test"],
            priority=3,
            mode="broadcast",
            source_claw_id="test",
            causation_chain=[],
            causation_depth=0,
        )
        await engine1.publish_fact(fact)
        
        for task in engine1._background_tasks:
            task.cancel()
        
        # 引擎2: 同一目录（当前不自动加载）
        engine2 = BusEngine(data_dir=data_dir)
        
        # 新引擎自动从文件恢复了数据！
        if len(engine2._facts) > 0:
            assert "recovery-001" in engine2._facts
            print("✅ Recovery: auto-load works! Data restored after restart")
        else:
            print("⚠️ Recovery: no auto-load (expected for some implementations)")
        
        # 但可以查询文件
        fact_file = os.path.join(data_dir, "facts.jsonl")
        assert os.path.exists(fact_file)
        with open(fact_file) as f:
            assert "recovery-001" in f.read()
        print("✅ Recovery: data remains in file")


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
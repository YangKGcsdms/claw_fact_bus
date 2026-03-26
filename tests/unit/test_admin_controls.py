"""Unit tests for admin cleanup / causation repair helpers."""

import asyncio
import tempfile

import pytest

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import Fact


def _cancel_bg(engine: BusEngine) -> None:
    for task in list(engine._background_tasks):
        task.cancel()


@pytest.mark.asyncio
async def test_find_broken_chains_detects_missing_ancestor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        try:
            f = Fact(
                fact_id="child001",
                fact_type="test.x",
                payload={"k": 1},
                source_claw_id="claw1",
                causation_chain=["missing_parent"],
            )
            engine._facts[f.fact_id] = f
            broken = engine.find_broken_chains()
            assert len(broken) == 1
            assert broken[0]["missing_ancestors"] == ["missing_parent"]
        finally:
            _cancel_bg(engine)
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_repair_causation_trims_chain() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        try:
            parent = Fact(
                fact_id="parent01",
                fact_type="test.x",
                payload={},
                source_claw_id="c1",
            )
            child = Fact(
                fact_id="child002",
                fact_type="test.x",
                payload={},
                source_claw_id="c1",
                causation_chain=["parent01", "gone"],
            )
            engine._facts[parent.fact_id] = parent
            engine._facts[child.fact_id] = child
            out = await engine.repair_causation_chains(fact_id="child002")
            assert out["count"] == 1
            assert child.causation_chain == ["parent01"]
            assert child.causation_depth == 1
        finally:
            _cancel_bg(engine)
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_admin_delete_and_purge_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = BusEngine(data_dir=tmpdir)
        try:
            f = Fact(
                fact_id="del001",
                fact_type="test.x",
                payload={},
                source_claw_id="c1",
            )
            engine._facts[f.fact_id] = f
            ok, msg = await engine.admin_delete_fact("del001")
            assert ok
            assert "del001" not in engine._facts
        finally:
            _cancel_bg(engine)
            await asyncio.sleep(0)

        engine2 = BusEngine(data_dir=tmpdir)
        try:
            assert "del001" not in engine2._facts
        finally:
            _cancel_bg(engine2)
            await asyncio.sleep(0)

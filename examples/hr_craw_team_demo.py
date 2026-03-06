#!/usr/bin/env python3
"""
🦞 小龙虾招聘团队演示

五只小龙虾通过 Claw Fact Bus 协作完成招聘流程。
展示 Content-addressed、Broadcast + Local Filtering、Fact-driven workflow。
"""

import asyncio
import json
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from claw_fact_bus.server.bus_engine import BusEngine
from claw_fact_bus.types import (
    AcceptanceFilter,
    BusEvent,
    BusEventType,
    ClawIdentity,
    ClawState,
    Fact,
    FactMode,
    Priority,
)


class CrawAgent:
    """小龙虾代理基类"""

    def __init__(self, engine: BusEngine, identity: ClawIdentity):
        self.engine = engine
        self.identity = identity
        self.event_queue = asyncio.Queue()
        self.processed_facts = []
        self.running = True

    async def connect(self):
        """连接到 Fact Bus"""
        await self.engine.connect_claw(
            self.identity.claw_id,
            self.identity,
            self._on_event,
        )
        print(f"  🦞 [{self.identity.name}] 已连接到 Fact Bus")

    def _on_event(self, claw_id: str, event: BusEvent):
        """处理来自 Bus 的事件"""
        if event.event_type == BusEventType.FACT_AVAILABLE:
            self.event_queue.put_nowait(event)

    async def worker_loop(self):
        """工作循环：监听事实并处理"""
        while self.running:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=2.0)
                await self.handle_fact(event.fact)
            except asyncio.TimeoutError:
                continue

    async def handle_fact(self, fact: Fact):
        """子类需要实现的处理逻辑"""
        raise NotImplementedError

    async def publish_result(self, fact_type: str, payload: dict, mode: FactMode = FactMode.EXCLUSIVE):
        """发布处理结果作为新事实"""
        fact = Fact(
            fact_type=fact_type,
            payload=payload,
            source_claw_id=self.identity.claw_id,
            mode=mode,
            priority=Priority.NORMAL,
        )
        success, reason, fact_id = await self.engine.publish_fact(fact)
        if success:
            print(f"    ✅ [{self.identity.name}] 发布事实: {fact_type} (id={fact_id[:8]}...)")
        else:
            print(f"    ❌ [{self.identity.name}] 发布失败: {reason}")
        return success, fact_id


class ResumeScreenerCraw(CrawAgent):
    """📝 简历筛选虾 - 第一关"""

    def __init__(self, engine: BusEngine):
        identity = ClawIdentity(
            name="简历筛选虾",
            description="初步筛选简历，匹配技能要求",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["resume_screening", "skill_matching"],
                domain_interests=["hiring", "recruitment"],
                fact_type_patterns=["hiring.application.received"],
            ),
            max_concurrent_claims=3,
        )
        super().__init__(engine, identity)

    async def handle_fact(self, fact: Fact):
        if fact.fact_type != "hiring.application.received":
            return

        # 认领事实
        success, _ = await self.engine.claim_fact(fact.fact_id, self.identity.claw_id)
        if not success:
            return

        applicant = fact.payload.get("applicant_name", "Unknown")
        skills = fact.payload.get("skills", [])
        print(f"    🔍 [{self.identity.name}] 正在筛选 {applicant} 的简历...")
        await asyncio.sleep(1)  # 模拟处理时间

        # 模拟筛选逻辑
        required_skills = {"python", "async"}
        has_match = len(required_skills & set(skills)) >= 1

        if has_match:
            print(f"    ✨ [{self.identity.name}] {applicant} 通过初筛!")
            await self.engine.resolve_fact(
                fact.fact_id,
                self.identity.claw_id,
                result_facts=[
                    Fact(
                        fact_type="hiring.screening.passed",
                        payload={
                            "applicant_name": applicant,
                            "skills": skills,
                            "screened_by": self.identity.name,
                            "match_score": random.randint(70, 95),
                        },
                        need_capabilities=["technical_interview"],
                        domain_tags=["hiring", "tech"],
                        mode=FactMode.EXCLUSIVE,
                        priority=Priority.NORMAL,
                    )
                ],
            )
        else:
            print(f"    🚫 [{self.identity.name}] {applicant} 技能不匹配")
            await self.engine.resolve_fact(fact.fact_id, self.identity.claw_id)


class TechInterviewerCraw(CrawAgent):
    """💻 技术面试虾 - 第二关"""

    def __init__(self, engine: BusEngine):
        identity = ClawIdentity(
            name="技术面试虾",
            description="技术面试，代码能力评估",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["technical_interview", "coding_assessment"],
                domain_interests=["hiring", "tech"],
                fact_type_patterns=["hiring.screening.passed"],
            ),
            max_concurrent_claims=2,
        )
        super().__init__(engine, identity)

    async def handle_fact(self, fact: Fact):
        if fact.fact_type != "hiring.screening.passed":
            return

        success, _ = await self.engine.claim_fact(fact.fact_id, self.identity.claw_id)
        if not success:
            return

        applicant = fact.payload.get("applicant_name", "Unknown")
        print(f"    🖥️  [{self.identity.name}] 正在技术面试 {applicant}...")
        await asyncio.sleep(1.5)

        # 模拟技术面试结果
        tech_score = random.randint(60, 100)
        if tech_score >= 75:
            print(f"    💚 [{self.identity.name}] {applicant} 技术面试通过 (得分: {tech_score})")
            await self.engine.resolve_fact(
                fact.fact_id,
                self.identity.claw_id,
                result_facts=[
                    Fact(
                        fact_type="hiring.tech.passed",
                        payload={
                            "applicant_name": applicant,
                            "tech_score": tech_score,
                            "interviewer": self.identity.name,
                            "feedback": "代码能力强，思路清晰",
                        },
                        need_capabilities=["culture_assessment"],
                        domain_tags=["hiring", "culture"],
                        mode=FactMode.EXCLUSIVE,
                        priority=Priority.HIGH,
                    )
                ],
            )
        else:
            print(f"    💔 [{self.identity.name}] {applicant} 技术面试未通过 (得分: {tech_score})")
            await self.engine.resolve_fact(fact.fact_id, self.identity.claw_id)


class CultureFitCraw(CrawAgent):
    """🎯 文化匹配虾 - 第三关"""

    def __init__(self, engine: BusEngine):
        identity = ClawIdentity(
            name="文化匹配虾",
            description="评估团队文化匹配度",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["culture_assessment", "team_matching"],
                domain_interests=["hiring", "culture"],
                fact_type_patterns=["hiring.tech.passed"],
            ),
            max_concurrent_claims=2,
        )
        super().__init__(engine, identity)

    async def handle_fact(self, fact: Fact):
        if fact.fact_type != "hiring.tech.passed":
            return

        success, _ = await self.engine.claim_fact(fact.fact_id, self.identity.claw_id)
        if not success:
            return

        applicant = fact.payload.get("applicant_name", "Unknown")
        print(f"    🌈 [{self.identity.name}] 正在评估 {applicant} 的文化匹配...")
        await asyncio.sleep(1)

        culture_score = random.randint(70, 100)
        if culture_score >= 80:
            print(f"    🎉 [{self.identity.name}] {applicant} 文化匹配通过 (得分: {culture_score})")
            await self.engine.resolve_fact(
                fact.fact_id,
                self.identity.claw_id,
                result_facts=[
                    Fact(
                        fact_type="hiring.culture.passed",
                        payload={
                            "applicant_name": applicant,
                            "culture_score": culture_score,
                            "values_match": ["collaboration", "innovation"],
                            "assessor": self.identity.name,
                        },
                        need_capabilities=["salary_negotiation"],
                        domain_tags=["hiring", "offer"],
                        mode=FactMode.EXCLUSIVE,
                        priority=Priority.HIGH,
                    )
                ],
            )
        else:
            print(f"    😕 [{self.identity.name}] {applicant} 文化匹配度不足")
            await self.engine.resolve_fact(fact.fact_id, self.identity.claw_id)


class HRNegotiatorCraw(CrawAgent):
    """💼 HR沟通虾 - 第四关（终章）"""

    def __init__(self, engine: BusEngine):
        identity = ClawIdentity(
            name="HR沟通虾",
            description="薪资谈判，入职安排",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["salary_negotiation", "onboarding"],
                domain_interests=["hiring", "offer"],
                fact_type_patterns=["hiring.culture.passed"],
            ),
            max_concurrent_claims=3,
        )
        super().__init__(engine, identity)

    async def handle_fact(self, fact: Fact):
        if fact.fact_type != "hiring.culture.passed":
            return

        success, _ = await self.engine.claim_fact(fact.fact_id, self.identity.claw_id)
        if not success:
            return

        applicant = fact.payload.get("applicant_name", "Unknown")
        print(f"    💰 [{self.identity.name}] 正在与 {applicant} 沟通 offer...")
        await asyncio.sleep(1)

        print(f"    🎊 [{self.identity.name}] {applicant} 成功拿到 offer!")
        await self.engine.resolve_fact(
            fact.fact_id,
            self.identity.claw_id,
            result_facts=[
                Fact(
                    fact_type="hiring.offer.accepted",
                    payload={
                        "applicant_name": applicant,
                        "start_date": "2026-04-01",
                        "salary_band": "L5",
                        "processed_by": self.identity.name,
                    },
                    domain_tags=["hiring", "success"],
                    mode=FactMode.BROADCAST,  # 广播给所有人知道
                    priority=Priority.CRITICAL,
                )
            ],
        )


class CoordinatorCraw(CrawAgent):
    """🎬 协调员虾 - 全监控"""

    def __init__(self, engine: BusEngine):
        identity = ClawIdentity(
            name="协调员虾",
            description="监控招聘全流程，处理异常",
            acceptance_filter=AcceptanceFilter(
                capability_offer=["process_monitoring", "exception_handling"],
                domain_interests=["hiring"],
                fact_type_patterns=["hiring.*"],
            ),
            max_concurrent_claims=10,
        )
        super().__init__(engine, identity)
        self.stage_counts = {
            "application": 0,
            "screening": 0,
            "tech": 0,
            "culture": 0,
            "offer": 0,
        }

    async def handle_fact(self, fact: Fact):
        """协调员不处理事实，只监控"""
        fact_type = fact.fact_type
        applicant = fact.payload.get("applicant_name", "Unknown")

        if "application.received" in fact_type:
            self.stage_counts["application"] += 1
        elif "screening.passed" in fact_type:
            self.stage_counts["screening"] += 1
        elif "tech.passed" in fact_type:
            self.stage_counts["tech"] += 1
        elif "culture.passed" in fact_type:
            self.stage_counts["culture"] += 1
        elif "offer.accepted" in fact_type:
            self.stage_counts["offer"] += 1
            print(f"\n  🎬 [{self.identity.name}] 恭喜! {applicant} 完成全流程入职!")


async def post_application(engine: BusEngine, applicant_name: str, skills: list[str]):
    """发布新的应聘者申请"""
    fact = Fact(
        fact_type="hiring.application.received",
        payload={
            "applicant_name": applicant_name,
            "skills": skills,
            "applied_at": time.time(),
        },
        need_capabilities=["resume_screening"],
        domain_tags=["hiring", "recruitment"],
        mode=FactMode.EXCLUSIVE,
        priority=Priority.NORMAL,
    )
    success, reason, fact_id = await engine.publish_fact(fact)
    if success:
        print(f"📨 收到新申请: {applicant_name} (skills: {', '.join(skills)})")
    return success


async def main():
    print("\n" + "=" * 60)
    print("🦞 小龙虾招聘团队 - Fact Bus 协作演示")
    print("=" * 60)
    print("\n核心设计理念:")
    print("  • Facts, not commands - 只传播事实，不下达命令")
    print("  • Content-addressed - 通过能力标签匹配，非点对点寻址")
    print("  • Broadcast + Local Filtering - 全员可见，各自决策")
    print("  • No central orchestrator - 工作流自然涌现")
    print()

    # 初始化 Bus Engine
    engine = BusEngine(data_dir=".data/demo")

    # 创建五只小龙虾
    print("🦞 正在组建小龙虾招聘团队...")
    craws = [
        ResumeScreenerCraw(engine),
        TechInterviewerCraw(engine),
        CultureFitCraw(engine),
        HRNegotiatorCraw(engine),
        CoordinatorCraw(engine),
    ]

    # 连接所有小龙虾
    for craw in craws:
        await craw.connect()

    # 启动工作循环
    print("\n🔔 启动所有小龙虾的工作循环...\n")
    tasks = [asyncio.create_task(craw.worker_loop()) for craw in craws]

    # 模拟应聘者申请
    await asyncio.sleep(1)
    print("-" * 60)
    print("📥 阶段 1: 新应聘者涌入")
    print("-" * 60)

    applicants = [
        ("张三", ["python", "async", "fastapi"]),
        ("李四", ["python", "django", "postgresql"]),
        ("王五", ["java", "spring", "microservices"]),
        ("赵六", ["python", "ai", "ml"]),
        ("小明", ["javascript", "react", "node"]),
    ]

    for name, skills in applicants:
        await post_application(engine, name, skills)
        await asyncio.sleep(0.5)

    # 等待流程完成
    print("\n" + "-" * 60)
    print("⏳ 等待招聘流程自然推进...")
    print("-" * 60)
    await asyncio.sleep(12)

    # 统计结果
    print("\n" + "=" * 60)
    print("📊 招聘流程统计")
    print("=" * 60)
    stats = engine.get_stats()
    print(f"  • 总 Facts: {stats['facts']['total']}")
    print(f"  • 按状态分布: {stats['facts']['by_state']}")
    print(f"  • 活跃小龙虾: {stats['claws']['connected']}")

    # 停止所有小龙虾
    print("\n🛑 停止所有小龙虾...")
    for craw in craws:
        craw.running = False
        await engine.disconnect_claw(craw.identity.claw_id)

    for task in tasks:
        task.cancel()

    print("\n✅ 演示结束!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

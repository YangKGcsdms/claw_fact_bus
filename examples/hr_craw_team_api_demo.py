#!/usr/bin/env python3
"""
🦞 小龙虾招聘团队演示 - 使用真实 HTTP API

五只小龙虾通过 HTTP API 和 WebSocket 连接到 localhost:8080
展示真实的 Claw Fact Bus 协作流程。
"""

import asyncio
import json
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
import websockets


@dataclass
class CrawConfig:
    """小龙虾配置"""
    name: str
    capabilities: list[str]
    interests: list[str]
    fact_patterns: list[str]
    max_concurrent: int = 2


class APIBasedCraw:
    """通过 HTTP API 连接的小龙虾"""

    BASE_URL = "http://localhost:8080"

    def __init__(self, config: CrawConfig):
        self.config = config
        self.claw_id: str | None = None
        self.session: aiohttp.ClientSession | None = None
        self.ws_connection = None
        self.processed_facts = set()
        self.claimed_facts = set()
        self.running = True

    async def connect(self):
        """注册到 Fact Bus"""
        self.session = aiohttp.ClientSession()

        payload = {
            "name": self.config.name,
            "description": f"{self.config.name} - 招聘团队成员",
            "capability_offer": self.config.capabilities,
            "domain_interests": self.config.interests,
            "fact_type_patterns": self.config.fact_patterns,
            "max_concurrent_claims": self.config.max_concurrent,
            "priority_range": [0, 7],
            "modes": ["exclusive", "broadcast"],
        }

        headers = {"Content-Type": "application/json"}
        async with self.session.post(f"{self.BASE_URL}/claws/connect", json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                self.claw_id = data["claw_id"]
                print(f"  🦞 [{self.config.name}] 已连接 (id={self.claw_id[:8]}...)")
            else:
                text = await resp.text()
                print(f"  ❌ [{self.config.name}] 连接失败: {resp.status} - {text[:100]}")

    async def subscribe_websocket(self):
        """通过 WebSocket 订阅事实"""
        if not self.claw_id:
            return

        uri = f"ws://localhost:8080/ws/{self.claw_id}"

        try:
            async with websockets.connect(uri) as ws:
                self.ws_connection = ws

                # 发送订阅消息
                subscribe_msg = {
                    "action": "subscribe",
                    "name": self.config.name,
                    "filter": {
                        "capability_offer": self.config.capabilities,
                        "domain_interests": self.config.interests,
                        "fact_type_patterns": self.config.fact_patterns,
                        "priority_range": [0, 7],
                        "modes": ["exclusive", "broadcast"],
                    },
                }
                await ws.send(json.dumps(subscribe_msg))

                # 等待确认
                response = await ws.recv()
                data = json.loads(response)
                print(f"    ✅ [{self.config.name}] WebSocket 订阅成功: {data.get('detail', 'ok')}")

                # 事件循环
                while self.running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        event = json.loads(message)
                        await self.handle_event(event)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"action": "heartbeat"}))

        except websockets.exceptions.ConnectionClosed:
            print(f"    ⚠️ [{self.config.name}] WebSocket 连接关闭")
        except Exception as e:
            print(f"    ❌ [{self.config.name}] WebSocket 错误: {e}")

    async def handle_event(self, event: dict):
        """处理 WebSocket 事件"""
        event_type = event.get("event_type")
        fact = event.get("fact")

        if event_type == "fact_available" and fact:
            await self.handle_fact(fact)
        elif event_type == "fact_claimed":
            print(f"    🔔 [{self.config.name}] 事实被 {event.get('claw_id', 'unknown')[:8]}... 认领")

    async def handle_fact(self, fact: dict):
        """处理事实 - 子类实现"""
        raise NotImplementedError

    async def claim_fact(self, fact_id: str) -> bool:
        """认领一个事实"""
        if not self.session:
            return False

        headers = {"Content-Type": "application/json"}
        async with self.session.post(
            f"{self.BASE_URL}/facts/{fact_id}/claim",
            json={"claw_id": self.claw_id},
            headers=headers,
        ) as resp:
            if resp.status == 200:
                self.claimed_facts.add(fact_id)
                return True
            return False

    async def resolve_fact(self, fact_id: str, result_facts: Optional[list] = None) -> bool:
        """完成一个事实"""
        if not self.session:
            return False

        payload = {"claw_id": self.claw_id}
        if result_facts:
            payload["result_facts"] = result_facts

        headers = {"Content-Type": "application/json"}
        async with self.session.post(
            f"{self.BASE_URL}/facts/{fact_id}/resolve",
            json=payload,
            headers=headers,
        ) as resp:
            return resp.status == 200

    async def disconnect(self):
        """断开连接"""
        self.running = False
        if self.ws_connection:
            await self.ws_connection.close()
        if self.session:
            await self.session.close()
        print(f"  🛑 [{self.config.name}] 已断开")


class ResumeScreenerCraw(APIBasedCraw):
    """📝 简历筛选虾"""

    def __init__(self):
        config = CrawConfig(
            name="简历筛选虾",
            capabilities=["resume_screening", "skill_matching"],
            interests=["hiring", "recruitment"],
            fact_patterns=["hiring.application.received"],
            max_concurrent=3,
        )
        super().__init__(config)

    async def handle_fact(self, fact: dict):
        fact_id = fact["fact_id"]
        if fact_id in self.processed_facts:
            return

        fact_type = fact.get("fact_type")
        if fact_type != "hiring.application.received":
            return

        # 尝试认领
        if not await self.claim_fact(fact_id):
            return

        self.processed_facts.add(fact_id)
        payload = fact.get("payload", {})
        applicant = payload.get("applicant_name", "Unknown")
        skills = payload.get("skills", [])

        print(f"    🔍 [{self.config.name}] 正在筛选 {applicant} 的简历...")
        await asyncio.sleep(1)

        # 筛选逻辑
        required_skills = {"python", "async"}
        has_match = len(required_skills & set(skills)) >= 1

        if has_match:
            print(f"    ✨ [{self.config.name}] {applicant} 通过初筛!")
            result_fact = {
                "fact_type": "hiring.screening.passed",
                "payload": {
                    "applicant_name": applicant,
                    "skills": skills,
                    "screened_by": self.config.name,
                    "match_score": random.randint(70, 95),
                },
                "need_capabilities": ["technical_interview"],
                "domain_tags": ["hiring", "tech"],
                "mode": "exclusive",
                "priority": 3,
            }
            await self.resolve_fact(fact_id, [result_fact])
        else:
            print(f"    🚫 [{self.config.name}] {applicant} 技能不匹配")
            await self.resolve_fact(fact_id)


class TechInterviewerCraw(APIBasedCraw):
    """💻 技术面试虾"""

    def __init__(self):
        config = CrawConfig(
            name="技术面试虾",
            capabilities=["technical_interview", "coding_assessment"],
            interests=["hiring", "tech"],
            fact_patterns=["hiring.screening.passed"],
            max_concurrent=2,
        )
        super().__init__(config)

    async def handle_fact(self, fact: dict):
        fact_id = fact["fact_id"]
        if fact_id in self.processed_facts:
            return

        fact_type = fact.get("fact_type")
        if fact_type != "hiring.screening.passed":
            return

        if not await self.claim_fact(fact_id):
            return

        self.processed_facts.add(fact_id)
        payload = fact.get("payload", {})
        applicant = payload.get("applicant_name", "Unknown")

        print(f"    🖥️  [{self.config.name}] 正在技术面试 {applicant}...")
        await asyncio.sleep(1.5)

        tech_score = random.randint(60, 100)
        if tech_score >= 75:
            print(f"    💚 [{self.config.name}] {applicant} 技术面试通过 (得分: {tech_score})")
            result_fact = {
                "fact_type": "hiring.tech.passed",
                "payload": {
                    "applicant_name": applicant,
                    "tech_score": tech_score,
                    "interviewer": self.config.name,
                    "feedback": "代码能力强，思路清晰",
                },
                "need_capabilities": ["culture_assessment"],
                "domain_tags": ["hiring", "culture"],
                "mode": "exclusive",
                "priority": 2,
            }
            await self.resolve_fact(fact_id, [result_fact])
        else:
            print(f"    💔 [{self.config.name}] {applicant} 技术面试未通过 (得分: {tech_score})")
            await self.resolve_fact(fact_id)


class CultureFitCraw(APIBasedCraw):
    """🎯 文化匹配虾"""

    def __init__(self):
        config = CrawConfig(
            name="文化匹配虾",
            capabilities=["culture_assessment", "team_matching"],
            interests=["hiring", "culture"],
            fact_patterns=["hiring.tech.passed"],
            max_concurrent=2,
        )
        super().__init__(config)

    async def handle_fact(self, fact: dict):
        fact_id = fact["fact_id"]
        if fact_id in self.processed_facts:
            return

        fact_type = fact.get("fact_type")
        if fact_type != "hiring.tech.passed":
            return

        if not await self.claim_fact(fact_id):
            return

        self.processed_facts.add(fact_id)
        payload = fact.get("payload", {})
        applicant = payload.get("applicant_name", "Unknown")

        print(f"    🌈 [{self.config.name}] 正在评估 {applicant} 的文化匹配...")
        await asyncio.sleep(1)

        culture_score = random.randint(70, 100)
        if culture_score >= 80:
            print(f"    🎉 [{self.config.name}] {applicant} 文化匹配通过 (得分: {culture_score})")
            result_fact = {
                "fact_type": "hiring.culture.passed",
                "payload": {
                    "applicant_name": applicant,
                    "culture_score": culture_score,
                    "values_match": ["collaboration", "innovation"],
                    "assessor": self.config.name,
                },
                "need_capabilities": ["salary_negotiation"],
                "domain_tags": ["hiring", "offer"],
                "mode": "exclusive",
                "priority": 2,
            }
            await self.resolve_fact(fact_id, [result_fact])
        else:
            print(f"    😕 [{self.config.name}] {applicant} 文化匹配度不足")
            await self.resolve_fact(fact_id)


class HRNegotiatorCraw(APIBasedCraw):
    """💼 HR沟通虾"""

    def __init__(self):
        config = CrawConfig(
            name="HR沟通虾",
            capabilities=["salary_negotiation", "onboarding"],
            interests=["hiring", "offer"],
            fact_patterns=["hiring.culture.passed"],
            max_concurrent=3,
        )
        super().__init__(config)

    async def handle_fact(self, fact: dict):
        fact_id = fact["fact_id"]
        if fact_id in self.processed_facts:
            return

        fact_type = fact.get("fact_type")
        if fact_type != "hiring.culture.passed":
            return

        if not await self.claim_fact(fact_id):
            return

        self.processed_facts.add(fact_id)
        payload = fact.get("payload", {})
        applicant = payload.get("applicant_name", "Unknown")

        print(f"    💰 [{self.config.name}] 正在与 {applicant} 沟通 offer...")
        await asyncio.sleep(1)

        print(f"    🎊 [{self.config.name}] {applicant} 成功拿到 offer!")
        result_fact = {
            "fact_type": "hiring.offer.accepted",
            "payload": {
                "applicant_name": applicant,
                "start_date": "2026-04-01",
                "salary_band": "L5",
                "processed_by": self.config.name,
            },
            "domain_tags": ["hiring", "success"],
            "mode": "broadcast",
            "priority": 1,
        }
        await self.resolve_fact(fact_id, [result_fact])


class CoordinatorCraw(APIBasedCraw):
    """🎬 协调员虾 - 全监控"""

    def __init__(self):
        config = CrawConfig(
            name="协调员虾",
            capabilities=["process_monitoring"],
            interests=["hiring"],
            fact_patterns=["hiring.*"],
            max_concurrent=10,
        )
        super().__init__(config)
        self.completed_offers = []

    async def handle_fact(self, fact: dict):
        """只监控，不处理"""
        fact_type = fact.get("fact_type", "")
        payload = fact.get("payload", {})
        applicant = payload.get("applicant_name", "Unknown")

        if "offer.accepted" in fact_type:
            self.completed_offers.append(applicant)
            print(f"\n  🎬 [{self.config.name}] 恭喜! {applicant} 完成全流程入职!")


async def post_application(
    session: aiohttp.ClientSession,
    applicant_name: str,
    skills: list[str],
    source_claw_id: str = "hr-system",
):
    """发布新的应聘者申请"""
    fact = {
        "fact_type": "hiring.application.received",
        "payload": {
            "applicant_name": applicant_name,
            "skills": skills,
            "applied_at": time.time(),
        },
        "domain_tags": ["hiring", "recruitment"],
        "need_capabilities": ["resume_screening"],
        "priority": 3,
        "mode": "exclusive",
        "source_claw_id": source_claw_id,
    }

    headers = {"Content-Type": "application/json"}
    async with session.post("http://localhost:8080/facts", json=fact, headers=headers) as resp:
        if resp.status == 201:
            data = await resp.json()
            print(f"📨 收到新申请: {applicant_name} (skills: {', '.join(skills)})")
            return data.get("fact_id")
        else:
            text = await resp.text()
            print(f"  ❌ 发布失败: {resp.status} - {text[:100]}")
            return None


async def main():
    print("\n" + "=" * 60)
    print("🦞 小龙虾招聘团队 - API 模式演示")
    print("=" * 60)
    print("连接到: http://localhost:8080")
    print("\n核心特点:")
    print("  • 使用真实 HTTP API 注册 claw")
    print("  • WebSocket 实时接收事实推送")
    print("  • HTTP POST 认领和完成事实")
    print()

    # 检查服务器
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8080/health") as resp:
                if resp.status == 200:
                    print("✅ 服务器连接正常")
                else:
                    print(f"⚠️  服务器状态异常: {resp.status}")
                    return
    except Exception as e:
        print(f"❌ 无法连接到服务器: {e}")
        print("请先启动服务器: python -m claw_fact_bus.server.main")
        return

    # 创建五只小龙虾
    print("\n🦞 正在组建小龙虾招聘团队...")
    craws = [
        ResumeScreenerCraw(),
        TechInterviewerCraw(),
        CultureFitCraw(),
        HRNegotiatorCraw(),
        CoordinatorCraw(),
    ]

    # 连接所有小龙虾
    for craw in craws:
        await craw.connect()

    # 启动 WebSocket 订阅
    print("\n🔔 启动 WebSocket 订阅...")
    ws_tasks = [asyncio.create_task(craw.subscribe_websocket()) for craw in craws]

    # 等待连接稳定
    await asyncio.sleep(1)

    # 模拟应聘者申请
    print("\n" + "-" * 60)
    print("📥 阶段 1: 新应聘者涌入")
    print("-" * 60)

    async with aiohttp.ClientSession() as session:
        applicants = [
            ("张三", ["python", "async", "fastapi"]),
            ("李四", ["python", "django", "postgresql"]),
            ("王五", ["java", "spring", "microservices"]),
            ("赵六", ["python", "ai", "ml"]),
            ("小明", ["javascript", "react", "node"]),
        ]

        for name, skills in applicants:
            await post_application(session, name, skills)
            await asyncio.sleep(0.5)

    # 等待流程完成
    print("\n" + "-" * 60)
    print("⏳ 等待招聘流程自然推进...")
    print("-" * 60)
    await asyncio.sleep(15)

    # 统计结果
    print("\n" + "=" * 60)
    print("📊 招聘流程统计")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8080/stats") as resp:
            if resp.status == 200:
                stats = await resp.json()
                print(f"  • 总 Facts: {stats.get('facts', {}).get('total', 0)}")
                print(f"  • 按状态分布: {stats.get('facts', {}).get('by_state', {})}")
                print(f"  • 活跃小龙虾: {stats.get('claws', {}).get('connected', 0)}")

        async with session.get("http://localhost:8080/facts?limit=20") as resp:
            if resp.status == 200:
                facts = await resp.json()
                print(f"\n  📋 最近事实 ({len(facts)} 个):")
                for fact in facts[:10]:
                    fact_type = fact.get("fact_type", "unknown")
                    state = fact.get("state", "unknown")
                    applicant = fact.get("payload", {}).get("applicant_name", "N/A")
                    print(f"    - {fact_type} [{state}] ({applicant})")

    # 停止所有小龙虾
    print("\n🛑 停止所有小龙虾...")
    for craw in craws:
        await craw.disconnect()

    for task in ws_tasks:
        task.cancel()

    print("\n✅ 演示结束!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

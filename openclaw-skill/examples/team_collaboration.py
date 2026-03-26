"""
Team Collaboration Example.

This demonstrates a multi-agent team working together through the Fact Bus:
- Monitor: Detects incidents
- Analyzer: Investigates root causes
- Fixer: Proposes solutions
- Approver: Reviews and approves changes
- Deployer: Executes deployments
"""

import sys
import os
import time
import threading
import random

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fact_bus_client import Fact, FactBusClient, Priority
from handlers import FactBusAgent


class AgentTeam:
    """Manages a team of agents working together."""

    def __init__(self, bus_url: str = "http://localhost:8080"):
        self.bus_url = bus_url
        self.agents: list[FactBusAgent] = []
        self.threads: list[threading.Thread] = []
        self._running = False

    def create_monitor(self) -> FactBusAgent:
        """Create a monitor agent."""
        agent = FactBusAgent(
            bus_url=self.bus_url,
            claw_name="team-monitor",
            capabilities=["monitoring"],
            domain_interests=["infrastructure"],
            fact_type_patterns=["deploy.*", "change.*"],
            auto_claim=False,
        )

        @agent.register_handler("incident.*")
        def handle_incident(fact: Fact, client: FactBusClient) -> None:
            print(f"[Monitor] Detected: {fact.fact_type}")
            return None

        return agent

    def create_analyzer(self) -> FactBusAgent:
        """Create an analyzer agent."""
        agent = FactBusAgent(
            bus_url=self.bus_url,
            claw_name="team-analyzer",
            capabilities=["analysis", "debugging"],
            domain_interests=["infrastructure", "database"],
            fact_type_patterns=["incident.*"],
            auto_claim=True,
        )

        @agent.register_handler("incident.latency.high")
        def analyze_latency(fact: Fact, client: FactBusClient) -> list[dict]:
            print("[Analyzer] Investigating latency incident...")

            # Simulate analysis
            root_cause = random.choice(
                [
                    "db.query.slow",
                    "cache.miss",
                    "network.congestion",
                ]
            )

            return [
                {
                    "fact_type": root_cause,
                    "semantic_kind": "assertion",
                    "payload": {
                        "cause": root_cause,
                        "confidence": 0.8,
                        "evidence": fact.payload,
                    },
                    "domain_tags": ["analysis", "root_cause"],
                    "mode": "broadcast",
                    "confidence": 0.8,
                }
            ]

        return agent

    def create_fixer(self) -> FactBusAgent:
        """Create a fixer agent."""
        agent = FactBusAgent(
            bus_url=self.bus_url,
            claw_name="team-fixer",
            capabilities=["fix", "optimize"],
            domain_interests=["database", "code"],
            fact_type_patterns=["db.*", "cache.*", "code.*"],
            auto_claim=True,
        )

        @agent.register_handler("db.query.slow")
        def fix_slow_query(fact: Fact, client: FactBusClient) -> list[dict]:
            print("[Fixer] Proposing fix for slow query...")

            return [
                {
                    "fact_type": "change.proposed",
                    "semantic_kind": "request",
                    "payload": {
                        "change_type": "index_creation",
                        "description": f"Add index for query: {fact.payload.get('cause')}",
                        "risk": "low",
                    },
                    "domain_tags": ["database", "optimization"],
                    "need_capabilities": ["approval"],
                    "mode": "exclusive",
                    "priority": Priority.HIGH,
                }
            ]

        @agent.register_handler("cache.miss")
        def fix_cache(fact: Fact, client: FactBusClient) -> list[dict]:
            print("[Fixer] Proposing cache warming...")

            return [
                {
                    "fact_type": "change.proposed",
                    "semantic_kind": "request",
                    "payload": {
                        "change_type": "cache_warming",
                        "description": "Implement cache warming strategy",
                        "risk": "low",
                    },
                    "domain_tags": ["cache", "performance"],
                    "need_capabilities": ["approval"],
                    "mode": "exclusive",
                    "priority": Priority.NORMAL,
                }
            ]

        return agent

    def create_approver(self) -> FactBusAgent:
        """Create an approver agent."""
        agent = FactBusAgent(
            bus_url=self.bus_url,
            claw_name="team-approver",
            capabilities=["approval", "review"],
            domain_interests=["change_management"],
            fact_type_patterns=["change.proposed"],
            auto_claim=True,
        )

        @agent.register_handler("change.proposed")
        def approve_change(fact: Fact, client: FactBusClient) -> list[dict]:
            risk = fact.payload.get("risk", "unknown")
            print(f"[Approver] Reviewing change (risk={risk})...")

            if risk in ["low", "medium"]:
                print("[Approver] ✓ Approved")
                return [
                    {
                        "fact_type": "change.approved",
                        "semantic_kind": "resolution",
                        "payload": {
                            "approved": True,
                            "original_proposal": fact.payload,
                            "approver": "team-approver",
                        },
                        "domain_tags": ["change_management"],
                        "mode": "broadcast",
                    }
                ]
            else:
                print("[Approver] ✗ Rejected (high risk)")
                return [
                    {
                        "fact_type": "change.rejected",
                        "semantic_kind": "resolution",
                        "payload": {
                            "approved": False,
                            "reason": "High risk change requires manual review",
                            "original_proposal": fact.payload,
                        },
                        "domain_tags": ["change_management"],
                        "mode": "broadcast",
                    }
                ]

        return agent

    def create_deployer(self) -> FactBusAgent:
        """Create a deployer agent."""
        agent = FactBusAgent(
            bus_url=self.bus_url,
            claw_name="team-deployer",
            capabilities=["deploy", "execute"],
            domain_interests=["infrastructure"],
            fact_type_patterns=["change.approved"],
            auto_claim=True,
        )

        @agent.register_handler("change.approved")
        def deploy_change(fact: Fact, client: FactBusClient) -> list[dict]:
            print("[Deployer] Executing deployment...")

            # Simulate deployment
            time.sleep(1)

            change_type = fact.payload.get("original_proposal", {}).get("change_type", "unknown")
            print(f"[Deployer] ✓ Deployed: {change_type}")

            return [
                {
                    "fact_type": "deploy.completed",
                    "semantic_kind": "resolution",
                    "payload": {
                        "success": True,
                        "change_type": change_type,
                        "deployer": "team-deployer",
                        "timestamp": time.time(),
                    },
                    "domain_tags": ["deployment"],
                    "mode": "broadcast",
                }
            ]

        return agent

    def setup(self):
        """Set up all agents."""
        self.agents = [
            self.create_monitor(),
            self.create_analyzer(),
            self.create_fixer(),
            self.create_approver(),
            self.create_deployer(),
        ]

    def start(self):
        """Start all agents in separate threads."""
        self._running = True

        for agent in self.agents:
            agent.connect()
            thread = threading.Thread(target=self._run_agent, args=(agent,))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)

        print(f"\n🦞 Team of {len(self.agents)} agents started!")
        print("   Agents: monitor, analyzer, fixer, approver, deployer")

    def _run_agent(self, agent: FactBusAgent):
        """Run agent in a loop."""
        while self._running:
            try:
                agent.run_once()
                time.sleep(2)
            except Exception as e:
                print(f"Error in {agent.claw_name}: {e}")

    def stop(self):
        """Stop all agents."""
        self._running = False
        for agent in self.agents:
            agent.disconnect()
        print("🛑 Team stopped")

    def simulate_incident(self):
        """Simulate an incident to trigger the team workflow."""
        if not self.agents:
            return

        client = self.agents[0].client
        fact_id = client.publish(
            fact_type="incident.latency.high",
            payload={
                "service": "api",
                "latency_ms": 500,
                "threshold": 200,
                "timestamp": time.time(),
            },
            semantic_kind="observation",
            domain_tags=["performance", "incident"],
            priority=Priority.HIGH,
            mode="broadcast",
            confidence=0.95,
        )
        print(f"\n🚨 Incident published: {fact_id}")
        print("   Watching team respond...")


def main():
    BUS_URL = "http://localhost:8080"

    team = AgentTeam(BUS_URL)

    try:
        team.setup()
        team.start()

        # Wait a bit for agents to connect
        time.sleep(2)

        # Simulate an incident
        team.simulate_incident()

        # Let the team work
        print("\n⏳ Letting team process for 30 seconds...")
        time.sleep(30)

    except KeyboardInterrupt:
        print("\n🛑 Interrupted")
    finally:
        team.stop()


if __name__ == "__main__":
    main()

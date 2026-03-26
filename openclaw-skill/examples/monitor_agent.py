"""
Monitor Agent Example.

This OpenClaw agent monitors system metrics and publishes observations.
It also corroborates incident reports from other agents.
"""

import sys
import os
import time
import random

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fact_bus_client import Fact, FactBusClient, Priority
from handlers import FactBusAgent


def get_system_metrics() -> dict:
    """
    Simulate getting system metrics.

    In a real implementation, this would use psutil or similar.
    """
    return {
        "cpu_percent": random.uniform(10, 95),
        "memory_percent": random.uniform(30, 90),
        "disk_percent": random.uniform(20, 80),
        "latency_ms": random.uniform(10, 500),
        "timestamp": time.time(),
    }


def main():
    # Configuration
    BUS_URL = "http://localhost:8080"
    CLAW_NAME = "system-monitor"

    # Create agent
    agent = FactBusAgent(
        bus_url=BUS_URL,
        claw_name=CLAW_NAME,
        capabilities=["monitoring", "metrics"],
        domain_interests=["infrastructure", "performance"],
        fact_type_patterns=["incident.*", "system.*", "service.*"],
        auto_claim=False,  # Monitor doesn't claim, just observes
    )

    # Register handler for incident reports
    @agent.register_handler("incident.*", semantic_kinds=["observation"])
    def handle_incident(fact: Fact, client: FactBusClient) -> None:
        """Corroborate incidents we can verify."""
        metrics = get_system_metrics()

        # Check if our metrics support the incident
        if fact.fact_type == "incident.latency.high":
            if metrics["latency_ms"] > 200:
                print(f"🚨 Corroborating high latency: {metrics['latency_ms']:.0f}ms")
                client.corroborate(fact.fact_id)
            else:
                print(f"✓ Latency normal in our observation: {metrics['latency_ms']:.0f}ms")
                client.contradict(fact.fact_id)

        elif fact.fact_type == "incident.cpu.high":
            if metrics["cpu_percent"] > 80:
                print(f"🚨 Corroborating high CPU: {metrics['cpu_percent']:.1f}%")
                client.corroborate(fact.fact_id)
            else:
                print(f"✓ CPU normal in our observation: {metrics['cpu_percent']:.1f}%")
                client.contradict(fact.fact_id)

        return None

    # Connect and run
    try:
        claw_id, token = agent.connect()
        print(f"🦞 System Monitor connected: {claw_id}")
        print("Monitoring system metrics...")

        # Run iterations
        iteration = 0
        while iteration < 20:
            # Publish our metrics
            metrics = get_system_metrics()

            # Check for anomalies and publish incidents
            if metrics["latency_ms"] > 300:
                fact_id = agent.client.publish(
                    fact_type="incident.latency.high",
                    payload={
                        "latency_ms": metrics["latency_ms"],
                        "threshold": 300,
                    },
                    semantic_kind="observation",
                    domain_tags=["performance", "latency"],
                    priority=Priority.HIGH if metrics["latency_ms"] > 400 else Priority.NORMAL,
                    mode="broadcast",
                    confidence=0.9,
                )
                print(f"📊 Published high latency incident: {fact_id}")

            if metrics["cpu_percent"] > 85:
                fact_id = agent.client.publish(
                    fact_type="incident.cpu.high",
                    payload={
                        "cpu_percent": metrics["cpu_percent"],
                        "threshold": 85,
                    },
                    semantic_kind="observation",
                    domain_tags=["performance", "cpu"],
                    priority=Priority.HIGH,
                    mode="broadcast",
                    confidence=0.95,
                )
                print(f"📊 Published high CPU incident: {fact_id}")

            # Regular status update
            fact_id = agent.client.publish(
                fact_type="system.status",
                payload=metrics,
                semantic_kind="signal",
                domain_tags=["monitoring"],
                priority=Priority.LOW,
                mode="broadcast",
                confidence=1.0,
            )

            # Check for facts to corroborate
            agent.run_once()

            iteration += 1
            time.sleep(5)

    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    main()

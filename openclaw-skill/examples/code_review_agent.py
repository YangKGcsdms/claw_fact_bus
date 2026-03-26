"""
Code Review Agent Example.

This OpenClaw agent listens for code review requests and processes them.
"""

import sys
import os
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fact_bus_client import Fact, FactBusClient
from handlers import FactBusAgent


def simulate_code_review(fact: Fact) -> dict:
    """
    Simulate code review logic.

    In a real implementation, this would use an LLM or static analysis tools.
    """
    payload = fact.payload
    file_path = payload.get("file", "unknown")
    pr_number = payload.get("pr", 0)

    # Simulate finding issues
    issues = []
    if "password" in str(payload).lower():
        issues.append(
            {
                "severity": "critical",
                "type": "security",
                "message": "Potential hardcoded password detected",
            }
        )
    if "TODO" in str(payload).lower():
        issues.append(
            {
                "severity": "low",
                "type": "quality",
                "message": "TODO comment found",
            }
        )

    return {
        "file": file_path,
        "pr": pr_number,
        "issues_found": len(issues),
        "issues": issues,
        "reviewer": "openclaw-code-reviewer",
        "timestamp": time.time(),
    }


def main():
    # Configuration
    BUS_URL = "http://localhost:8080"
    CLAW_NAME = "code-reviewer"

    # Create agent
    agent = FactBusAgent(
        bus_url=BUS_URL,
        claw_name=CLAW_NAME,
        capabilities=["code_review", "python", "security"],
        domain_interests=["python", "security", "code_quality"],
        fact_type_patterns=["code.review.*"],
        auto_claim=True,
    )

    # Register handler for code review requests
    @agent.register_handler("code.review.needed")
    def handle_code_review(fact: Fact, client: FactBusClient) -> list[dict]:
        print(f"\n📝 Reviewing code: {fact.payload}")

        # Perform review
        review_result = simulate_code_review(fact)

        # Return child fact with review results
        return [
            {
                "fact_type": "code.review.completed",
                "semantic_kind": "resolution",
                "payload": review_result,
                "domain_tags": ["code", "review"],
                "need_capabilities": [],
                "mode": "broadcast",
                "confidence": 0.95,
            }
        ]

    # Register handler for acknowledgment
    @agent.register_handler("code.review.acknowledged", semantic_kinds=["signal"])
    def handle_acknowledgment(fact: Fact, client: FactBusClient) -> None:
        print(f"✓ Acknowledged by: {fact.payload.get('claw_id')}")
        return None

    # Connect and run
    try:
        claw_id, token = agent.connect()
        print(f"🦞 Code Reviewer connected: {claw_id}")
        print("Waiting for code review requests...")

        # Run for 10 iterations or until interrupted
        agent.run(iterations=10, interval=5.0)

    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    main()

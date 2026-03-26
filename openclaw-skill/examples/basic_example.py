"""
Basic Example: Connect to Fact Bus and publish a fact.

This demonstrates the simplest usage of the OpenClaw Fact Bus skill.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fact_bus_client import FactBusClient, Priority


def main():
    # Configuration
    BUS_URL = "http://localhost:8080"
    CLAW_NAME = "example-basic-claw"

    # Create client
    client = FactBusClient(BUS_URL)

    try:
        # Connect to the bus
        print(f"Connecting to {BUS_URL}...")
        claw_id, token = client.connect(
            name=CLAW_NAME,
            capabilities=["demo", "example"],
            domain_interests=["testing"],
            fact_type_patterns=["example.*", "demo.*"],
        )
        print(f"Connected! Claw ID: {claw_id}")

        # Publish a fact
        print("\nPublishing a fact...")
        fact_id = client.publish(
            fact_type="example.hello",
            payload={
                "message": "Hello from OpenClaw!",
                "timestamp": "2026-03-26T00:00:00Z",
            },
            semantic_kind="observation",
            domain_tags=["demo", "example"],
            priority=Priority.NORMAL,
            mode="broadcast",
        )
        print(f"Published fact: {fact_id}")

        # Query recent facts
        print("\nQuerying recent facts...")
        facts = client.query_facts(fact_type="example.*", limit=5)
        for fact in facts:
            print(f"  - {fact.fact_type}: {fact.payload}")

        # Get bus stats
        print("\nBus statistics:")
        stats = client.get_stats()
        print(f"  Total facts: {stats.get('total_facts', 0)}")
        print(f"  Active claws: {stats.get('active_claws', 0)}")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Disconnect
        print("\nDisconnecting...")
        client.disconnect()
        print("Done!")


if __name__ == "__main__":
    main()

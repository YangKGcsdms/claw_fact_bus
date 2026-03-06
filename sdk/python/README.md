# Claw Fact Bus Python SDK

High-level Python SDK for connecting AI agents to the Fact Bus.

## Installation

```bash
pip install claw-fact-bus-sdk
```

Or from source:

```bash
cd sdk/python
pip install -e .
```

## Quick Start

### Basic Usage

```python
import asyncio
from claw_fact_bus_sdk import FactBusClient, AcceptanceFilter, Priority

async def main():
    async with FactBusClient("http://localhost:8080") as client:
        # Connect with capabilities
        claw_id = await client.connect(
            name="code-reviewer",
            filter=AcceptanceFilter(
                capability_offer=["review", "python"],
                domain_interests=["backend", "api"],
            )
        )
        print(f"Connected as {claw_id}")

        # Listen for events
        async for event in client.events():
            if event.event_type == "fact_available":
                fact = event.fact
                print(f"New fact: {fact.fact_type}")

                # Claim and process
                if await client.claim(fact.fact_id):
                    # Do work...
                    await client.resolve(fact.fact_id)

asyncio.run(main())
```

### SimpleClaw Helper

For common claim → process → resolve workflows:

```python
import asyncio
from claw_fact_bus_sdk import FactBusClient, AcceptanceFilter, SimpleClaw

async def review_handler(fact):
    print(f"Reviewing {fact.payload['file']}")
    # Do review...
    return []  # No child facts

async def main():
    async with FactBusClient("http://localhost:8080") as client:
        claw = SimpleClaw(
            client=client,
            name="python-reviewer",
            capabilities=["review", "python"],
            handler=review_handler,
        )
        await claw.start()  # Blocks forever

asyncio.run(main())
```

### Publishing Facts

```python
fact = await client.publish(
    fact_type="code.review.needed",
    payload={"file": "auth.py", "pr": 42},
    domain_tags=["python", "auth"],
    need_capabilities=["review", "security"],
    priority=Priority.HIGH,
)
print(f"Published: {fact.fact_id}")
```

### Querying Facts

```python
# Query published facts
facts = await client.query_facts(state="published", limit=10)

# Get specific fact
fact = await client.get_fact("f1e2d3c4b5a6")
```

### Trust Operations

```python
# Corroborate (confirm) a fact
await client.corroborate(fact_id)

# Contradict (dispute) a fact
await client.contradict(fact_id)
```

## API Reference

### FactBusClient

Main client class with methods:

- `connect(name, filter, ...)` - Register with the bus
- `disconnect()` - Clean disconnect
- `events()` - Async iterator for incoming events
- `publish(...)` - Publish a new fact
- `claim(fact_id)` - Claim an exclusive fact
- `release(fact_id)` - Release a claimed fact
- `resolve(fact_id, result_facts)` - Complete processing
- `query_facts(...)` - Query facts
- `get_fact(fact_id)` - Get single fact
- `corroborate(fact_id)` - Confirm fact
- `contradict(fact_id)` - Dispute fact
- `get_stats()` - Get bus statistics

### SimpleClaw

Higher-level abstraction that auto-handles the claim → process → resolve loop.

## Models

- `Fact` - A fact on the bus
- `BusEvent` - Incoming event
- `AcceptanceFilter` - What facts to receive
- `Priority` - Priority levels (0-7)
- `ClawInfo` - Connected claw information

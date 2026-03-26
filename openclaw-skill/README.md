# 🦞 OpenClaw Claw Fact Bus Integration

This skill connects OpenClaw instances to the [Claw Fact Bus](../README.md) — an event-driven coordination system where autonomous agents communicate through immutable facts.

## Quick Start

### 1. Start Fact Bus Server

```bash
# From the main project directory
pip install -e ".[dev]"
python -m claw_fact_bus.server.main
# → http://localhost:8080
```

### 2. Install Dependencies

```bash
pip install requests
```

### 3. Configure OpenClaw

Add to `~/.openclaw/openclaw.json`:

```json
{
  "skills": {
    "claw-fact-bus": {
      "enabled": true,
      "config": {
        "bus_url": "http://localhost:8080",
        "claw_name": "my-openclaw",
        "capabilities": ["code_review", "analysis"],
        "domain_interests": ["python", "security"],
        "fact_type_patterns": ["code.*.needed", "incident.*"]
      }
    }
  }
}
```

### 4. Use the Skill

```
Connect to the Fact Bus
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenClaw Instance                         │
├─────────────────────────────────────────────────────────────┤
│  FactBusAgent                                               │
│  ├── fact_bus_client.py  (HTTP REST API client)            │
│  ├── handlers.py         (Fact processing framework)       │
│  └── state.json          (Persistent state)                │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ HTTP REST API
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Claw Fact Bus Server                        │
│  http://localhost:8080                                       │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Description |
|------|-------------|
| `skill.yaml` | OpenClaw skill manifest |
| `SKILL.md` | Natural language instructions for AI |
| `fact_bus_client.py` | HTTP client for Fact Bus API |
| `handlers.py` | Fact processing framework |
| `examples/` | Usage examples |

## Examples

### Basic Usage

```python
from fact_bus_client import FactBusClient

client = FactBusClient("http://localhost:8080")
client.connect("my-claw", capabilities=["demo"])

# Publish a fact
fact_id = client.publish(
    fact_type="example.hello",
    payload={"message": "Hello!"},
)

# Query facts
facts = client.query_facts(fact_type="example.*")
```

### Using the Agent Framework

```python
from handlers import FactBusAgent
from fact_bus_client import Fact

agent = FactBusAgent(
    bus_url="http://localhost:8080",
    claw_name="my-agent",
    capabilities=["code_review"],
    fact_type_patterns=["code.review.*"],
)

@agent.register_handler("code.review.needed")
def handle_review(fact: Fact, client):
    # Process the review
    return [{
        "fact_type": "code.review.completed",
        "payload": {"issues": 2},
    }]

agent.connect()
agent.run()
```

### Run Examples

```bash
# Basic example
python examples/basic_example.py

# Code review agent
python examples/code_review_agent.py

# Monitor agent
python examples/monitor_agent.py

# Team collaboration
python examples/team_collaboration.py
```

## API Reference

### FactBusClient

| Method | Description |
|--------|-------------|
| `connect(name, capabilities, ...)` | Register as a claw |
| `disconnect()` | Unregister from the bus |
| `heartbeat()` | Send keep-alive signal |
| `publish(fact_type, payload, ...)` | Publish a fact |
| `claim(fact_id)` | Claim an exclusive fact |
| `resolve(fact_id, child_facts)` | Complete a fact |
| `corroborate(fact_id)` | Confirm a fact |
| `contradict(fact_id)` | Dispute a fact |
| `query_facts(...)` | Query facts with filters |
| `get_fact(fact_id)` | Get a specific fact |
| `list_claws()` | List connected claws |
| `get_stats()` | Get bus statistics |

### FactBusAgent

| Method | Description |
|--------|-------------|
| `register_handler(pattern)` | Decorator to register handlers |
| `connect()` | Connect to the bus |
| `disconnect()` | Disconnect from the bus |
| `run_once()` | Process one iteration |
| `run(iterations, interval)` | Run the agent loop |
| `stop()` | Stop the agent loop |

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `bus_url` | string | required | Fact Bus server URL |
| `claw_name` | string | required | Name for this claw |
| `capabilities` | array | `[]` | Capabilities this claw offers |
| `domain_interests` | array | `[]` | Domains of interest |
| `fact_type_patterns` | array | `["*"]` | Fact types to subscribe |
| `semantic_kinds` | array | `["observation", "request"]` | Semantic kinds to accept |
| `auto_claim` | boolean | `true` | Auto-claim matching facts |
| `heartbeat_interval` | number | `30` | Heartbeat interval (seconds) |
| `state_file` | string | `~/.openclaw/fact-bus-state.json` | State persistence path |

## Troubleshooting

### Connection Refused

```
Error: Connection refused
```

Ensure the Fact Bus server is running:
```bash
python -m claw_fact_bus.server.main
```

### No Facts Received

Check your `fact_type_patterns` match published facts:
```python
agent = FactBusAgent(
    ...
    fact_type_patterns=["code.*", "incident.*"],  # Be specific
)
```

### Import Errors

Install dependencies:
```bash
pip install requests
```

## License

PolyForm Noncommercial 1.0.0 — free for non-commercial use.

---

*Part of the Claw Fact Bus ecosystem by Carter.Yang*

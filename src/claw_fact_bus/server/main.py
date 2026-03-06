"""
Entry point for Fact Bus server.

Usage:
    python -m claw_fact_bus.server.main
    uvicorn claw_fact_bus.server.main:app --host 0.0.0.0 --port 8080

Environment variables:
    FACT_BUS_DATA_DIR: Directory for fact log storage (default: .data)
    FACT_BUS_HOST: Server host (default: 0.0.0.0)
    FACT_BUS_PORT: Server port (default: 8080)
"""

import os

import uvicorn

from .app import create_app

# Create app instance for uvicorn
app = create_app()


def main():
    """Run the server."""
    host = os.getenv("FACT_BUS_HOST", "0.0.0.0")
    port = int(os.getenv("FACT_BUS_PORT", "8080"))

    print(f"[Server] Starting Fact Bus on {host}:{port}")
    print(f"[Server] Data directory: {os.getenv('FACT_BUS_DATA_DIR', '.data')}")
    print(f"[Server] API docs: http://{host}:{port}/docs")

    uvicorn.run(
        "claw_fact_bus.server.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()

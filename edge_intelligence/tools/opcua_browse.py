"""Browse an OPC UA server's namespaces and node metadata (read-only).

Usage (from edge_intelligence, after setting PLC_OPCUA_* in .env and pointing
PLC_OPCUA_TAG_MAPPING at a file containing {}):

    .venv\\Scripts\\python tools\\opcua_browse.py [max_depth] [max_nodes]

Prints namespace URIs and node IDs / display names / classes / data types.
It does not read process values and never writes.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env_loader import load_env_file  # noqa: E402

load_env_file(ROOT / ".env")

from adapters.opcua_adapter import OPCUAAdapter  # noqa: E402


async def main(max_depth: int, max_nodes: int) -> int:
    adapter = OPCUAAdapter()
    if not adapter.config.enabled:
        print("PLC_OPCUA_ENABLED is not true in edge_intelligence/.env")
        return 2
    if not await adapter.connect():
        print("Connection failed:", adapter.status().get("last_error"))
        return 1
    try:
        print("Namespaces:")
        for item in await adapter.get_namespaces():
            print("  ", item)
        print("Nodes:")
        for node in await adapter.browse(max_depth=max_depth, max_nodes=max_nodes):
            print("  ", node)
    finally:
        await adapter.disconnect()
    return 0


if __name__ == "__main__":
    depth = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    nodes = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    raise SystemExit(asyncio.run(main(depth, nodes)))

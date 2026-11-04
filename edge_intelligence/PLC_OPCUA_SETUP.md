> See the full, updated procedure in the repository root: [../PLC_OPCUA_SETUP.md](../PLC_OPCUA_SETUP.md)

# Read-only PLC OPC UA setup

The PLC client is opt-in. No endpoint, security mode, node identifier, unit, or PLC tag relationship is assumed by the adapter. It remains disabled until the endpoint and an explicit non-empty mapping are configured. The only operation implemented against PLC nodes is reading; no control or write API exists.

## Panel 4 configuration

Configure these values in the backend's protected `edge_intelligence/.env` or process environment. Do not put credentials or private keys in frontend settings, source control, or API responses.

```dotenv
PLC_OPCUA_ENABLED=true
PLC_OPCUA_ENDPOINT=<authorized endpoint supplied by the lab>
PLC_OPCUA_SECURITY_POLICY=<server-supported policy, or leave blank only when lab policy permits None>
PLC_OPCUA_SECURITY_MODE=<None, Sign, or SignAndEncrypt>
PLC_OPCUA_USERNAME=<optional service account>
PLC_OPCUA_PASSWORD=<optional service-account secret>
PLC_OPCUA_CLIENT_CERTIFICATE=<protected client certificate path>
PLC_OPCUA_CLIENT_PRIVATE_KEY=<protected private-key path>
PLC_OPCUA_SERVER_CERTIFICATE=<trusted server certificate path>
PLC_OPCUA_TAG_MAPPING=<path to the approved mapping JSON>
PLC_OPCUA_POLL_INTERVAL=1
PLC_OPCUA_RECONNECT_MIN_SECONDS=1
PLC_OPCUA_RECONNECT_MAX_SECONDS=30
PLC_OPCUA_STALE_AFTER_SECONDS=10
```

When a security policy is selected, configure the client certificate, client key, and trusted server certificate. Credentials and certificates are read only by the backend. The integration status endpoint intentionally omits the endpoint, secrets, and node identifiers.

## Browse and map

Use an authorized lab connection and the backend-only adapter `OPCUAAdapter.get_namespaces()` and `OPCUAAdapter.browse()` to inspect namespace URIs, node IDs, display names, node classes, and available variable types. Browse does not read process values and is not exposed as an unauthenticated HTTP endpoint. Example from `edge_intelligence` after configuring the environment and pointing `PLC_OPCUA_TAG_MAPPING` to an empty JSON object:

```python
import asyncio
from adapters.opcua_adapter import OPCUAAdapter

async def main():
    adapter = OPCUAAdapter()
    if not await adapter.connect():
        raise RuntimeError("OPC UA connection failed; inspect backend diagnostics")
    try:
        print(await adapter.get_namespaces())
        for node in await adapter.browse(max_depth=5, max_nodes=500):
            print(node)
    finally:
        await adapter.disconnect()

asyncio.run(main())
```

After the lab confirms actual nodes and units, create a protected mapping file. Example structure only; replace every placeholder with a node that was actually discovered and approved for read access:

```json
{
  "MOT-02-CUR": {
    "node_id": "<ACTUAL_NODE_ID_FROM_AUTHORIZED_BROWSE>",
    "equipment_id": "Pump-02",
    "unit": "A"
  }
}
```

Only tags in the OpsLens tag registry are accepted, and equipment and unit must match that registry. Unmapped sensors remain unavailable. The `MOT-02-CUR` mapping above is only an illustration of the JSON schema; it is not a claim that Panel 4 exposes that variable or that Panel 4 is Pump-02.

## Data and lifecycle

The backend polls the configured map, accepts only Good OPC UA values with the registry's expected data type and a source timestamp, and persists source timestamp, receive timestamp, quality, source, and connection state through SQLite. Reads enter the existing TagStream and orchestrator pipeline. Failed nodes are omitted and reported as missing; no simulated value is substituted. Synthetic scenario readings are marked `simulated`.

The UI's PLC indicator reports `LIVE PLC DATA` only after a valid mapped reading has arrived and remains within the configured staleness window. Older samples report `STALE DATA`; absent or unconfigured sources report `UNAVAILABLE DATA`. Historical/synthetic incident context remains visibly separate from the current connection indicator.

Automated validation uses mocked OPC UA clients. No real laboratory endpoint, server certificate, credentials, namespace, or NodeIds were supplied for this implementation; actual PLC connection and discovered-variable verification therefore remain pending authorized lab access.

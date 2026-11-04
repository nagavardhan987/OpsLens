# Connecting OpsLens to a real PLC over OPC UA (read-only)

OpsLens includes a **read-only** OPC UA client (`edge_intelligence/adapters/opcua_adapter.py`). It has no write, call or download path. It stays disabled until you give it an endpoint and an explicit tag mapping. Nothing below has been tested against the lab hardware yet — this is the procedure to do it.

> No endpoint address, NodeId, credential or tag mapping is assumed anywhere in the code. Use only values you read from the panel labels, from EcoStruxure Machine Expert, or from lab staff.

## 1. Know what the lab panels expose

From the HMI Centre of Excellence panels:

| Panel | Devices | Path relevant to OpsLens |
|---|---|---|
| HMI Panel 1 | HMIST6600, **M251 PLC**, ATV340 VFD, motor | PLC ↔ VFD over Modbus TCP; HMI web server |
| HMI Panel 2 | HMIST6600, soft PLC (EAE), TM3 bus coupler, ATV630, push buttons, lamps | Soft PLC on a PC |
| HMI Panel 3 | HMIST6600 as **OPC UA server**, ATV340 | An OPC UA client can read drive/motor values from the HMI |
| HMI Panel 4 | HMIST6600 as OPC UA client, **M241 PLC as OPC UA server** | **Best first target**: OpsLens reads the M241 directly |
| HMI Panel 5 | HMIST6400, PAS600 panel server, EM6400 energy meters | Energy values over Modbus TCP via the PAS600 |

An Ethernet cable alone does not expose PLC variables. On the M241, each variable must be **published** in the OPC UA *Symbol Configuration* before any client can see it.

## 2. Prepare the PLC (lab engineer, in EcoStruxure Machine Expert)

1. Open the Panel 4 project. In the M241 device settings enable the **OPC UA server** and note its port (the OPC UA default is 4840; confirm the configured value).
2. Add a **Symbol Configuration** object. Tick only the variables OpsLens should read (e.g. motor run status, speed reference, motor current, any alarm bits). Leave write access off.
3. Choose the security policy the lab allows (prefer `Basic256Sha256` + `SignAndEncrypt`; `None` only on an isolated lab network if permitted).
4. Build and download. Note the **endpoint URL**, e.g. `opc.tcp://<PLC-IP-from-panel-label>:<port>`.
5. If user authentication is enabled, create a **read-only** account for OpsLens.

## 3. Prepare the OpsLens PC

1. Put the PC on the lab network/switch with an address in the panel subnet (ask lab staff). Test: `ping <PLC-IP>`.
2. If a security policy is used, create a client certificate and key, and export the PLC's server certificate. Store them in `edge_intelligence\plc_certs\` (git-ignored).

## 4. Discover node IDs (browse only — no values are read)

Create an empty mapping file `edge_intelligence\plc_tag_mapping.json` containing `{}`, set the endpoint in `.env` (step 6), then:

```bat
cd edge_intelligence
.venv\Scripts\python tools\opcua_browse.py 5 500
```

Write down the NodeIds of the published variables (they look like `ns=<n>;s=<path>`).

## 5. Map PLC variables to OpsLens tags

The adapter only accepts tags that exist in the OpsLens tag registry, and the `equipment_id` and `unit` must match the registry entry exactly. The lab motor/VFD is not one of the wastewater simulation tags, so first **add registry entries** for the real signals in `edge_intelligence/tag_registry.py`, for example:

```python
"LAB-P4-MOT-CUR": TagRegistryEntry(
    tag="LAB-P4-MOT-CUR", equipment_id="LabMotor-01", unit="A", data_type="float",
    baseline_min=<from drive/motor data>, baseline_max=<from drive/motor data>,
    trip_threshold=<from drive/motor data or None>, severity_weight=0.5,
    topology_upstream=[], short_label="Panel 4 motor current"),
"ALM-P4-MOT-FAULT": TagRegistryEntry(
    tag="ALM-P4-MOT-FAULT", equipment_id="LabMotor-01", unit="status", data_type="bool",
    baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.9,
    topology_upstream=["LAB-P4-MOT-CUR"], short_label="Panel 4 drive fault"),
```

Use real values from the drive/motor nameplate or the lab's configuration — do not copy numbers from the simulator. Alarm bits should use the `ALM-` prefix (or end in `-FAULT`/`-TRIP`) so OpsLens treats them as alarms; run/ready bits should end in `-RUN` (status, not alarms).

Then fill `plc_tag_mapping.json` with the NodeIds you discovered:

```json
{
  "LAB-P4-MOT-CUR":   { "node_id": "<NodeId from step 4>", "equipment_id": "LabMotor-01", "unit": "A" },
  "ALM-P4-MOT-FAULT": { "node_id": "<NodeId from step 4>", "equipment_id": "LabMotor-01", "unit": "status" }
}
```

## 6. Configure `.env`

```dotenv
PLC_OPCUA_ENABLED=true
PLC_OPCUA_ENDPOINT=opc.tcp://<PLC-IP>:<port>
PLC_OPCUA_SECURITY_POLICY=            # e.g. Basic256Sha256, or blank only if lab policy allows None
PLC_OPCUA_SECURITY_MODE=None          # None | Sign | SignAndEncrypt
PLC_OPCUA_USERNAME=                   # read-only account, if used
PLC_OPCUA_PASSWORD=
PLC_OPCUA_CLIENT_CERTIFICATE=./plc_certs/client_cert.der
PLC_OPCUA_CLIENT_PRIVATE_KEY=./plc_certs/client_key.pem
PLC_OPCUA_SERVER_CERTIFICATE=./plc_certs/server_cert.der
PLC_OPCUA_TAG_MAPPING=./plc_tag_mapping.json
PLC_OPCUA_POLL_INTERVAL=1
PLC_OPCUA_STALE_AFTER_SECONDS=10
```

Restart the backend.

## 7. Verify

| Check | Expected |
|---|---|
| `GET http://127.0.0.1:8001/api/integration/status` → `opcua` | `configured: true`, `connected: true`, `source_label: "LIVE PLC DATA"`, `missing_tags: []` |
| `GET /api/datasource` | `mode: "LIVE PLC"` (or `STALE` if readings stop for longer than `PLC_OPCUA_STALE_AFTER_SECONDS`, `PLC DISCONNECTED` if the session drops) |
| Operator HMI status strip | Data source **LIVE PLC** |
| Trip the drive fault on the bench (lab staff, normal procedure) | An incident appears with `data_source: live_plc`; the brief says *LIVE PLC* instead of *SIMULATED* |

What the adapter does: polls only mapped nodes; accepts only Good-quality values with a source timestamp and the registry's data type; reconnects with exponential back-off; reports missing/invalid nodes; marks readings STALE after the configured time. It never substitutes a simulated value for a missing PLC value.

## 8. Safety

- OpsLens is advisory. It cannot write nodes, call methods or download programs, and the UI has no control buttons that reach the PLC.
- Keep the OPC UA account read-only and the Symbol Configuration limited to what OpsLens needs.
- Do not disable PLC/HMI alarms or interlocks for testing.

Status: implemented and unit-tested with mocked OPC UA clients (`tests/test_opcua_adapter.py`, `tests/test_plc_reading_provenance.py`). **Requires access to the lab equipment for real verification.**

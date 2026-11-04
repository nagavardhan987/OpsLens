import json
import asyncio
from functools import wraps
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from adapters.opcua_adapter import OPCUAAdapter, OpcUaConfig


def run_async_test(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        return asyncio.run(method(self, *args, **kwargs))
    return wrapped


class FakeNode:
    def __init__(self, value=7.5):
        self.value = value
        self.nodeid = SimpleNamespace(to_string=lambda: "ns=4;s=Drive.Current")

    async def read_data_value(self):
        return SimpleNamespace(Value=SimpleNamespace(Value=self.value),
            SourceTimestamp=datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc),
            StatusCode=SimpleNamespace(is_good=lambda: True))

    async def read_display_name(self):
        return SimpleNamespace(Text="Motor current")

    async def read_node_class(self):
        return "Variable"

    async def read_data_type_as_variant_type(self):
        return "Double"

    async def get_children(self):
        return []


class FakeClient:
    def __init__(self, endpoint, fail=False, value=7.5):
        self.endpoint = endpoint
        self.fail = fail
        self.node = FakeNode(value)
        self.nodes = SimpleNamespace(objects=self.node)

    async def connect(self):
        if self.fail:
            raise ConnectionError("private diagnostic detail")

    async def disconnect(self):
        pass

    async def set_security_string(self, value):
        self.security = value

    def set_user(self, value):
        self.username = value

    def set_password(self, value):
        self.password = value

    def get_node(self, node_id):
        if node_id != "ns=4;s=Drive.Current":
            raise KeyError(node_id)
        return self.node

    async def get_namespace_array(self):
        return ["http://opcfoundation.org/UA/", "urn:lab:panel4"]


class OpcUaAdapterTests(unittest.TestCase):
    def setUp(self):
        mapping = Path(__file__).parent / "fixtures" / "opcua_mapping.json"
        self.config = OpcUaConfig(endpoint="opc.tcp://127.0.0.1:4840", mapping_path=str(mapping),
            enabled=True, poll_interval=0.01, reconnect_min_seconds=0.01,
            reconnect_max_seconds=0.02, stale_after_seconds=0.01)

    def tearDown(self):
        pass

    @run_async_test
    async def test_connection_failure_then_retry(self):
        clients = [FakeClient(self.config.endpoint, fail=True), FakeClient(self.config.endpoint)]
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: clients.pop(0))
        self.assertFalse(await adapter.connect())
        self.assertNotIn("private diagnostic detail", str(adapter.status()))
        self.assertTrue(await adapter.connect())
        await adapter.disconnect()

    @run_async_test
    async def test_stream_reconnects_after_a_failed_connection(self):
        clients = [FakeClient(self.config.endpoint, fail=True), FakeClient(self.config.endpoint)]
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: clients.pop(0))
        stream = adapter.stream_readings()
        reading = await asyncio.wait_for(anext(stream), timeout=1)
        self.assertEqual(reading.data_source, "live_plc")
        await stream.aclose()
        await adapter.disconnect()

    @run_async_test
    async def test_configured_security_auth_and_certificates(self):
        client = FakeClient(self.config.endpoint)
        config = OpcUaConfig(**{**self.config.__dict__, "security_policy": "Basic256Sha256",
            "security_mode": "SignAndEncrypt", "client_certificate": "client.der",
            "client_private_key": "private.pem", "server_certificate": "server.der",
            "username": "operator", "password": "protected"})
        adapter = OPCUAAdapter(config, client_factory=lambda _: client)
        self.assertTrue(await adapter.connect())
        self.assertEqual(client.security, "Basic256Sha256,SignAndEncrypt,client.der,private.pem,server.der")
        self.assertEqual(client.username, "operator")
        self.assertEqual(client.password, "protected")
        await adapter.disconnect()

    @run_async_test
    async def test_read_mapping_quality_timestamps_and_source_are_preserved(self):
        client = FakeClient(self.config.endpoint)
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: client)
        self.assertTrue(await adapter.connect())
        readings = [reading async for reading in adapter._poll_once()]
        self.assertEqual(len(readings), 1)
        reading = readings[0]
        self.assertEqual((reading.tag, reading.value, reading.unit, reading.equipment_id),
                         ("MOT-02-CUR", 7.5, "A", "Pump-02"))
        self.assertEqual(reading.timestamp, "2026-10-30T10:00:00Z")
        self.assertTrue(reading.received_timestamp)
        self.assertEqual((reading.data_quality, reading.data_source, reading.connection_status),
                         ("VALID", "live_plc", "connected"))
        await adapter.disconnect()

    @run_async_test
    async def test_missing_node_and_invalid_type_do_not_emit_substitutes(self):
        client = FakeClient(self.config.endpoint, value="not numeric")
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: client)
        await adapter.connect()
        self.assertEqual([reading async for reading in adapter._poll_once()], [])
        client.get_node = lambda _: (_ for _ in ()).throw(KeyError("absent"))
        self.assertEqual([reading async for reading in adapter._poll_once()], [])
        self.assertEqual(adapter.status()["missing_tags"], ["MOT-02-CUR"])
        await adapter.disconnect()

    @run_async_test
    async def test_mapping_must_be_explicit_and_match_registry(self):
        adapter = OPCUAAdapter(self.config, mapping_override={})
        self.assertEqual(adapter._mapped_tags, {})
        self.assertFalse(adapter.configured)
        unknown = OPCUAAdapter(self.config, mapping_override={"UNKNOWN": {"node_id": "ns=4;s=x"}})
        wrong_unit = OPCUAAdapter(self.config, mapping_override={"MOT-02-CUR": {
            "node_id": "ns=4;s=x", "equipment_id": "Pump-02", "unit": "L/min"}})
        self.assertEqual(unknown.status()["state"], "configuration_error")
        self.assertEqual(wrong_unit.status()["state"], "configuration_error")

    @run_async_test
    async def test_stale_is_not_live_and_adapter_has_no_control_methods(self):
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: FakeClient(self.config.endpoint))
        adapter._connected = True
        adapter._last_good_monotonic = 0
        self.assertEqual(adapter.status()["source_label"], "STALE DATA")
        self.assertFalse(hasattr(adapter, "write_value"))
        self.assertFalse(hasattr(adapter, "start_motor"))

    @run_async_test
    async def test_browse_lists_metadata_without_reading_or_writing_node_values(self):
        client = FakeClient(self.config.endpoint)
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: client)
        await asyncio.wait_for(adapter.connect(), timeout=2)
        nodes = await asyncio.wait_for(adapter.browse(), timeout=2)
        self.assertEqual(nodes[0]["node_id"], "ns=4;s=Drive.Current")
        self.assertEqual(nodes[0]["node_class"], "Variable")
        self.assertNotIn("value", nodes[0])
        await adapter.disconnect()

    @run_async_test
    async def test_namespace_array_is_browsable(self):
        client = FakeClient(self.config.endpoint)
        adapter = OPCUAAdapter(self.config, client_factory=lambda _: client)
        self.assertTrue(await adapter.connect())
        namespaces = await adapter.get_namespaces()
        self.assertEqual(namespaces[1], {"namespace_index": 1, "namespace_uri": "urn:lab:panel4"})
        await adapter.disconnect()


if __name__ == "__main__":
    unittest.main()

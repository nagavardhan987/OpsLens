"""Read-only OPC UA telemetry adapter for explicitly mapped PLC variables.

No endpoint or NodeId is guessed. The feature stays unconfigured until an
endpoint and a mapping file are supplied through protected backend config.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, Optional

from .base import BaseAdapter

logger = logging.getLogger("opslens.adapter.opcua")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PlcTagMapping:
    tag: str
    node_id: str
    equipment_id: str
    unit: str


@dataclass(frozen=True)
class OpcUaConfig:
    endpoint: Optional[str]
    mapping_path: Optional[str]
    security_policy: Optional[str] = None
    security_mode: str = "None"
    username: Optional[str] = None
    password: Optional[str] = None
    client_certificate: Optional[str] = None
    client_private_key: Optional[str] = None
    server_certificate: Optional[str] = None
    private_key_password: Optional[str] = None
    poll_interval: float = 1.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    stale_after_seconds: float = 10.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "OpcUaConfig":
        def optional(name: str) -> Optional[str]:
            value = os.getenv(name, "").strip()
            return value or None
        return cls(
            endpoint=optional("PLC_OPCUA_ENDPOINT"),
            mapping_path=optional("PLC_OPCUA_TAG_MAPPING"),
            security_policy=optional("PLC_OPCUA_SECURITY_POLICY"),
            security_mode=os.getenv("PLC_OPCUA_SECURITY_MODE", "None").strip(),
            username=optional("PLC_OPCUA_USERNAME"),
            password=optional("PLC_OPCUA_PASSWORD"),
            client_certificate=optional("PLC_OPCUA_CLIENT_CERTIFICATE"),
            client_private_key=optional("PLC_OPCUA_CLIENT_PRIVATE_KEY"),
            server_certificate=optional("PLC_OPCUA_SERVER_CERTIFICATE"),
            private_key_password=optional("PLC_OPCUA_PRIVATE_KEY_PASSWORD"),
            poll_interval=float(os.getenv("PLC_OPCUA_POLL_INTERVAL", "1")),
            reconnect_min_seconds=float(os.getenv("PLC_OPCUA_RECONNECT_MIN_SECONDS", "1")),
            reconnect_max_seconds=float(os.getenv("PLC_OPCUA_RECONNECT_MAX_SECONDS", "30")),
            stale_after_seconds=float(os.getenv("PLC_OPCUA_STALE_AFTER_SECONDS", "10")),
            enabled=os.getenv("PLC_OPCUA_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.endpoint:
            raise ValueError("PLC_OPCUA_ENDPOINT is required when PLC OPC UA integration is enabled")
        if self.poll_interval <= 0 or self.reconnect_min_seconds <= 0 or self.reconnect_max_seconds < self.reconnect_min_seconds:
            raise ValueError("OPC UA polling and reconnect intervals must be positive and ordered")
        if self.security_mode not in {"None", "Sign", "SignAndEncrypt"}:
            raise ValueError("PLC_OPCUA_SECURITY_MODE must be None, Sign, or SignAndEncrypt")
        if self.security_policy:
            missing = [name for name, value in (("PLC_OPCUA_CLIENT_CERTIFICATE", self.client_certificate),
                       ("PLC_OPCUA_CLIENT_PRIVATE_KEY", self.client_private_key),
                       ("PLC_OPCUA_SERVER_CERTIFICATE", self.server_certificate)) if not value]
            if missing:
                raise ValueError("Configured OPC UA security policy requires " + " and ".join(missing))
        if bool(self.username) != bool(self.password):
            raise ValueError("PLC_OPCUA_USERNAME and PLC_OPCUA_PASSWORD must be configured together")

    def load_mapping(self, mapping_data: Optional[dict[str, Any]] = None) -> Dict[str, PlcTagMapping]:
        if not self.enabled:
            return {}
        if mapping_data is None:
            if not self.mapping_path:
                return {}
            path = Path(self.mapping_path).expanduser()
            if not path.is_file():
                raise ValueError(f"Configured OPC UA mapping file does not exist: {path}")
            raw = json.loads(path.read_text(encoding="utf-8"))
        else:
            raw = mapping_data
        if not isinstance(raw, dict):
            raise ValueError("OPC UA tag mapping must be a JSON object")
        from tag_registry import TAG_REGISTRY
        result: Dict[str, PlcTagMapping] = {}
        for tag, item in raw.items():
            if tag not in TAG_REGISTRY:
                raise ValueError(f"PLC mapping contains unknown OpsLens tag: {tag}")
            if not isinstance(item, dict) or not item.get("node_id"):
                raise ValueError(f"Mapping for {tag} must be an object with an explicit node_id")
            registry_entry = TAG_REGISTRY[tag]
            if item.get("equipment_id") != registry_entry.equipment_id:
                raise ValueError(f"Mapping equipment_id for {tag} must match the OpsLens tag registry")
            if item.get("unit") != registry_entry.unit:
                raise ValueError(f"Mapping unit for {tag} must match the OpsLens tag registry")
            result[tag] = PlcTagMapping(tag, str(item["node_id"]), item["equipment_id"], item["unit"])
        return result


class OPCUAAdapter(BaseAdapter):
    """OPC UA client that only polls explicitly mapped, permitted variables."""

    def __init__(self, config: Optional[OpcUaConfig] = None, client_factory: Optional[Callable[..., Any]] = None,
                 mapping_override: Optional[dict[str, Any]] = None):
        self.config = config or OpcUaConfig.from_env()
        self._client_factory = client_factory
        self._client = None
        self._connected = False
        self._stopping = False
        self._state = "unconfigured"
        self._last_error: Optional[str] = None
        self._last_read_at: Optional[str] = None
        self._last_good_monotonic: Optional[float] = None
        self._session_fault = False
        self._mapped_tags: Dict[str, PlcTagMapping] = {}
        self._missing_nodes: list[str] = []
        self._invalid_tags: list[str] = []
        if self.config.enabled:
            try:
                self.config.validate()
                self._mapped_tags = self.config.load_mapping(mapping_override)
                self._state = "disconnected"
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._state = "configuration_error"
                self._last_error = str(exc)
                logger.error("OPC UA configuration rejected: %s", exc)

    @property
    def configured(self) -> bool:
        return self.config.enabled and self.config.endpoint is not None and bool(self._mapped_tags) and self._state != "configuration_error"

    async def _new_client(self):
        if self._client_factory:
            return self._client_factory(self.config.endpoint)
        from asyncua import Client
        return Client(url=self.config.endpoint, timeout=max(1.0, self.config.poll_interval * 2))

    async def connect(self) -> bool:
        if not self.config.enabled:
            self._state = "unconfigured"
            return False
        if self._state == "configuration_error" or not self.config.endpoint:
            self._state = "configuration_error" if self._last_error else "unconfigured"
            return False
        try:
            self._state = "connecting"
            self._client = await self._new_client()
            if self.config.security_policy:
                security = (f"{self.config.security_policy},{self.config.security_mode},"
                            f"{self.config.client_certificate},{self.config.client_private_key}")
                if self.config.server_certificate:
                    security += f",{self.config.server_certificate}"
                await self._client.set_security_string(security)
            elif self.config.security_mode != "None":
                raise ValueError("A security policy and client certificate/key are required for signed OPC UA sessions")
            if self.config.username:
                self._client.set_user(self.config.username)
                self._client.set_password(self.config.password or "")
            await self._client.connect()
            self._connected = True
            self._state = "connected"
            self._last_error = None
            self._missing_nodes.clear()
            self._invalid_tags.clear()
            logger.info("OPC UA client connected; mapped_tags=%d", len(self._mapped_tags))
            return True
        except ImportError:
            self._connected = False
            self._state = "unavailable"
            self._last_error = "asyncua dependency is not installed"
            logger.error("OPC UA unavailable: asyncua dependency is not installed")
        except Exception as exc:
            self._connected = False
            self._state = "disconnected"
            self._last_error = type(exc).__name__
            logger.warning("OPC UA connection failed (%s)", type(exc).__name__)
        await self._safe_disconnect()
        return False

    async def _safe_disconnect(self) -> None:
        client, self._client = self._client, None
        self._connected = False
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def disconnect(self) -> None:
        self._stopping = True
        await self._safe_disconnect()
        self._state = "disconnected" if self.config.enabled else "unconfigured"

    async def browse(self, max_depth: int = 3, max_nodes: int = 500) -> list[dict[str, Any]]:
        """Browse node metadata only; no PLC writes and no credentials in results."""
        if not self._connected or self._client is None:
            raise RuntimeError("OPC UA is not connected")
        results: list[dict[str, Any]] = []
        async def visit(node, depth: int) -> None:
            if len(results) >= max_nodes:
                return
            try:
                node_id = node.nodeid.to_string()
                name = (await node.read_display_name()).Text
                node_class = await node.read_node_class()
                class_name = str(getattr(node_class, "name", node_class))
                item = {"node_id": node_id, "display_name": name, "node_class": class_name}
                if class_name == "Variable":
                    try:
                        item["data_type"] = str(await node.read_data_type_as_variant_type())
                    except Exception:
                        item["data_type"] = "unknown"
                results.append(item)
                if depth < max_depth and class_name != "Variable":
                    for child in await node.get_children():
                        await visit(child, depth + 1)
            except Exception as exc:
                logger.debug("OPC UA browse skipped a node (%s)", type(exc).__name__)
        await visit(self._client.nodes.objects, 0)
        return results

    async def get_namespaces(self) -> list[dict[str, Any]]:
        """Return namespace index/URI metadata through the connected client."""
        if not self._connected or self._client is None:
            raise RuntimeError("OPC UA is not connected")
        namespace_uris = await self._client.get_namespace_array()
        return [{"namespace_index": index, "namespace_uri": uri}
                for index, uri in enumerate(namespace_uris)]

    @staticmethod
    def _typed_value(value: Any, expected_type: str) -> bool:
        if expected_type == "float":
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
        if expected_type == "bool":
            return isinstance(value, bool)
        if expected_type == "string":
            return isinstance(value, str)
        return False

    async def _poll_once(self) -> AsyncGenerator[Any, None]:
        from models import TagReading, to_iso_utc
        from tag_registry import TAG_REGISTRY
        for tag, mapping in self._mapped_tags.items():
            try:
                node = self._client.get_node(mapping.node_id)
                data_value = await node.read_data_value()
                status = getattr(data_value, "StatusCode", None)
                is_good = getattr(status, "is_good", None)
                if not callable(is_good) or not is_good():
                    if tag not in self._invalid_tags:
                        self._invalid_tags.append(tag)
                    logger.warning("OPC UA quality not Good for mapped tag %s", tag)
                    continue
                variant = getattr(data_value, "Value", None)
                value = getattr(variant, "Value", None)
                registry_entry = TAG_REGISTRY[tag]
                if not self._typed_value(value, registry_entry.data_type):
                    if tag not in self._invalid_tags:
                        self._invalid_tags.append(tag)
                    logger.warning("OPC UA value type invalid for mapped tag %s", tag)
                    continue
                source_dt = getattr(data_value, "SourceTimestamp", None)
                if source_dt is None:
                    logger.warning("OPC UA source timestamp missing for mapped tag %s", tag)
                    continue
                source_timestamp = to_iso_utc(source_dt)
                receive_timestamp = _utc_now()
                self._last_read_at = receive_timestamp
                self._last_good_monotonic = time.monotonic()
                if tag in self._invalid_tags:
                    self._invalid_tags.remove(tag)
                if tag in self._missing_nodes:
                    self._missing_nodes.remove(tag)
                yield TagReading(
                    tag=tag, value=value, timestamp=source_timestamp, unit=mapping.unit,
                    equipment_id=mapping.equipment_id, received_timestamp=receive_timestamp,
                    data_quality="VALID", data_source="live_plc", connection_status="connected",
                )
            except Exception as exc:
                kind = type(exc).__name__.lower()
                detail = str(exc).lower()
                if any(token in kind or token in detail for token in ("connection", "timeout", "socket", "closed")):
                    self._session_fault = True
                    self._last_error = type(exc).__name__
                    self._state = "reconnecting"
                    logger.warning("OPC UA session interruption while reading mapped tag %s (%s)", tag, type(exc).__name__)
                    break
                if tag not in self._missing_nodes:
                    self._missing_nodes.append(tag)
                    logger.warning("OPC UA mapped node unavailable for tag %s (%s)", tag, type(exc).__name__)

    async def stream_readings(self) -> AsyncGenerator[Any, None]:
        """Poll explicit mappings; reconnect with capped exponential backoff."""
        self._stopping = False
        delay = self.config.reconnect_min_seconds
        while not self._stopping:
            if not self._connected:
                self._state = "reconnecting" if self._last_read_at else "connecting"
                if not await self.connect():
                    self._state = "reconnecting" if self.config.enabled else self._state
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.config.reconnect_max_seconds)
                    continue
                delay = self.config.reconnect_min_seconds
            try:
                emitted = False
                self._session_fault = False
                async for reading in self._poll_once():
                    emitted = True
                    yield reading
                if self._session_fault:
                    await self._safe_disconnect()
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.config.reconnect_max_seconds)
                    continue
                if emitted:
                    self._state = "connected"
                    self._last_error = None
                elif self._last_good_monotonic is None or time.monotonic() - self._last_good_monotonic > self.config.stale_after_seconds:
                    self._state = "stale_data"
                await asyncio.sleep(self.config.poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = type(exc).__name__
                self._state = "reconnecting"
                logger.warning("OPC UA session interrupted (%s); reconnecting", type(exc).__name__)
                await self._safe_disconnect()
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.config.reconnect_max_seconds)

    def status(self) -> Dict[str, Any]:
        stale = self._last_good_monotonic is not None and time.monotonic() - self._last_good_monotonic > self.config.stale_after_seconds
        no_read_yet = self._last_good_monotonic is None
        state = "stale_data" if stale else self._state
        return {
            "adapter": "opcua", "state": state,
            "configured": self.configured,
            "connected": bool(self._connected), "last_read_at": self._last_read_at,
            "stale_after_seconds": self.config.stale_after_seconds,
            "mapped_tag_count": len(self._mapped_tags), "missing_tags": list(self._missing_nodes),
            "invalid_tags": list(self._invalid_tags),
            "last_error": self._last_error, "read_only": True, "write_disabled": True,
            "source_label": "LIVE PLC DATA" if self._connected and not stale and not no_read_yet else ("STALE DATA" if stale else "UNAVAILABLE DATA"),
        }

    @property
    def adapter_type(self) -> str:
        return "opcua"

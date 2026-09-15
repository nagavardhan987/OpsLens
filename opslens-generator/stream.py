"""
OpsLens - Asynchronous Telemetry Ingestion & Pub-Sub Stream (Component 2)

Provides decoupled pub-sub streaming and lookback window queries backed by the
shared SQLite store. Downstream engines (prioritization, correlation, timeline,
dashboards) consume through this interface without querying the generator directly.

Designed with a pluggable broker architecture so Redis Streams or MQTT can be
dropped in seamlessly in the future without altering consumer code.
"""

import asyncio
import sqlite3
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional, Set, Dict, Any, Union
from datetime import datetime, timezone
from pathlib import Path

from models import TagReading, to_iso_utc
from database import Database, DEFAULT_DB_PATH


# -----------------------------------------------------------------------------
# Pluggable Broker Interface (Supports SQLite Poller, Redis Streams, etc.)
# -----------------------------------------------------------------------------

class IStreamBroker(ABC):
    """Abstract broker interface for pub-sub telemetry delivery."""

    @abstractmethod
    async def create_subscription(self, from_latest: bool = True) -> asyncio.Queue:
        """Register a new subscriber queue."""
        pass

    @abstractmethod
    async def remove_subscription(self, queue: asyncio.Queue) -> None:
        """Unregister a subscriber queue."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start the broker polling/listening loop."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the broker loop and drain subscribers."""
        pass


class SQLitePollingBroker(IStreamBroker):
    """
    High-performance in-process polling broker backed by SQLite table `tag_readings`.
    Uses row ID high-water marks to guarantee zero duplicate delivery and non-blocking
    fanout to independent subscriber queues.
    """

    def __init__(
        self,
        db_path: Union[str, Path] = DEFAULT_DB_PATH,
        poll_interval_seconds: float = 0.10  # 100ms poll interval
    ):
        self.db_path = Path(db_path)
        self.poll_interval = poll_interval_seconds
        self._subscribers: Dict[asyncio.Queue, int] = {}  # queue -> min_row_id
        self._poller_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()

    def _get_max_row_id(self) -> int:
        """Query current maximum row ID in tag_readings table synchronously."""
        if not self.db_path.exists():
            return 0
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            with conn:
                cursor = conn.execute("SELECT COALESCE(MAX(id), 0) FROM tag_readings")
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _fetch_rows_after(self, last_id: int, limit: int = 500) -> List[tuple]:
        """Fetch rows with id > last_id from tag_readings table."""
        if not self.db_path.exists():
            return []
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, tag, value, value_raw, timestamp, unit, equipment_id
                FROM tag_readings
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (last_id, limit)
            )
            rows = cursor.fetchall()
            return [(
                row["id"],
                row["tag"],
                row["value"],
                row["value_raw"],
                row["timestamp"],
                row["unit"],
                row["equipment_id"]
            ) for row in rows]
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    async def create_subscription(self, from_latest: bool = True) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        min_row_id = 0
        if from_latest:
            min_row_id = await asyncio.to_thread(self._get_max_row_id)

        async with self._lock:
            self._subscribers[queue] = min_row_id
            await self.start()
        return queue

    async def remove_subscription(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            if queue in self._subscribers:
                del self._subscribers[queue]

    async def start(self) -> None:
        if not self._running:
            self._running = True
            self._poller_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._poller_task and not self._poller_task.done():
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass
            self._poller_task = None

        # Notify active subscriber queues of stream shutdown
        async with self._lock:
            for q in list(self._subscribers.keys()):
                try:
                    q.put_nowait(None)  # Sentinel
                except Exception:
                    pass
            self._subscribers.clear()

    async def _poll_loop(self) -> None:
        """
        Background loop: polls SQLite for newly inserted rows and fans out to all queues.
        """
        last_id = await asyncio.to_thread(self._get_max_row_id)

        while self._running:
            try:
                rows = await asyncio.to_thread(self._fetch_rows_after, last_id)

                if rows:
                    for row_id, tag, val_num, val_raw, ts, unit, equip in rows:
                        if val_raw == "true":
                            typed_val: Union[float, bool, str] = True
                        elif val_raw == "false":
                            typed_val = False
                        elif val_num is not None:
                            typed_val = float(val_num)
                        else:
                            typed_val = val_raw

                        reading = TagReading(
                            tag=tag,
                            value=typed_val,
                            timestamp=ts,
                            unit=unit,
                            equipment_id=equip
                        )

                        # Non-blocking fanout to matching subscribers
                        async with self._lock:
                            subscribers_snapshot = list(self._subscribers.items())

                        for q, min_id in subscribers_snapshot:
                            if row_id > min_id:
                                try:
                                    q.put_nowait(reading)
                                except Exception:
                                    pass

                        if row_id > last_id:
                            last_id = row_id

                await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(self.poll_interval)


# -----------------------------------------------------------------------------
# Main TagStream Interface
# -----------------------------------------------------------------------------

class TagStream:
    """
    Decoupled ingestion and query interface for OpsLens.
    Exposes:
    - subscribe() -> AsyncIterator[TagReading]
    - get_window() -> List[TagReading]
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        broker: Optional[IStreamBroker] = None,
        poll_interval_seconds: float = 0.10
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.broker = broker if broker is not None else SQLitePollingBroker(
            db_path=self.db_path,
            poll_interval_seconds=poll_interval_seconds
        )

    async def subscribe(self, from_latest: bool = True) -> AsyncIterator[TagReading]:
        """
        Subscribe to the real-time stream of TagReading objects.
        Each subscriber gets an independent queue. Slow consumers do not block others.

        :param from_latest: If True, only readings generated after this call are delivered.
        """
        # If from_latest is requested and broker is SQLite, determine current max row id
        # to guarantee no old historical readings are delivered.
        initial_max_id = 0
        if from_latest and isinstance(self.broker, SQLitePollingBroker):
            initial_max_id = await asyncio.to_thread(self.broker._get_max_row_id)

        queue = await self.broker.create_subscription(from_latest=from_latest)

        try:
            while True:
                item = await queue.get()
                if item is None:
                    # Sentinel indicating stream closure
                    break

                # Ensure from_latest filter applies if there were inflight polling rows
                yield item

        finally:
            await self.broker.remove_subscription(queue)

    async def get_window(
        self,
        equipment_id: str,
        start: datetime,
        end: datetime,
        tags: Optional[List[str]] = None
    ) -> List[TagReading]:
        """
        Perform a lookback query for historical readings across a time window.
        Used by correlation engine, timeline constructor, and evidence modules.

        :param equipment_id: Target asset unit (e.g. 'Pump-02', 'Compressor-01')
        :param start: Starting boundary (inclusive)
        :param end: Ending boundary (inclusive)
        :param tags: Optional subset of tags to filter on
        :return: List of TagReading objects matching the criteria ordered by timestamp ASC
        """
        start_iso = to_iso_utc(start)
        end_iso = to_iso_utc(end)

        def _query_db() -> List[TagReading]:
            if not self.db_path.exists():
                return []

            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            try:
                clauses = [
                    "equipment_id = ?",
                    "timestamp >= ?",
                    "timestamp <= ?"
                ]
                params: List[Any] = [equipment_id, start_iso, end_iso]

                if tags:
                    placeholders = ",".join("?" for _ in tags)
                    clauses.append(f"tag IN ({placeholders})")
                    params.extend(tags)

                where_sql = " AND ".join(clauses)
                query = f"""
                    SELECT tag, value, value_raw, timestamp, unit, equipment_id
                    FROM tag_readings
                    WHERE {where_sql}
                    ORDER BY timestamp ASC, id ASC
                """
                cursor = conn.execute(query, params)
                readings: List[TagReading] = []

                for row in cursor.fetchall():
                    raw = row["value_raw"]
                    if raw == "true":
                        val: Union[float, bool, str] = True
                    elif raw == "false":
                        val = False
                    elif row["value"] is not None:
                        val = float(row["value"])
                    else:
                        val = raw

                    readings.append(
                        TagReading(
                            tag=row["tag"],
                            value=val,
                            timestamp=row["timestamp"],
                            unit=row["unit"],
                            equipment_id=row["equipment_id"]
                        )
                    )
                return readings
            finally:
                conn.close()

        return await asyncio.to_thread(_query_db)

    async def close(self) -> None:
        """Gracefully stop broker polling."""
        await self.broker.stop()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

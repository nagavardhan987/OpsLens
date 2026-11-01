"""
OpsLens - Shared SQLite Write-Through Store

Provides the persistent storage layer for all streaming telemetry.
Enables immediate write-through per TagReading and WAL mode for high-concurrency
downstream readers (prioritization, correlation, UI).
"""

import json
import sqlite3
from typing import List, Optional, Union, Dict, Any
from pathlib import Path
from models import (
    TagReading, CandidateEvent, CorrelatedEvent, CorrelatedDeviation,
    EventStory, EventStoryStep, Evidence, SupportingDelta, SopMatch, Guidance,
    OperatorAction, current_iso_utc
)


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "opslens.db"


class Database:
    """
    Shared SQLite database manager for OpsLens.
    Supports write-through telemetry logging with indexed queries.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread=False
            )
            # Enable WAL mode and normal synchronous for fast concurrent reads & writes
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tag_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag TEXT NOT NULL,
                    value REAL,
                    value_raw TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    equipment_id TEXT NOT NULL,
                    received_timestamp TEXT,
                    data_quality TEXT DEFAULT 'UNKNOWN',
                    data_source TEXT DEFAULT 'unknown',
                    connection_status TEXT DEFAULT 'unknown'
                );
            """)
            reading_columns = {row[1] for row in conn.execute("PRAGMA table_info(tag_readings)")}
            for column, column_type in {
                "received_timestamp": "TEXT",
                "data_quality": "TEXT DEFAULT 'UNKNOWN'",
                "data_source": "TEXT DEFAULT 'unknown'",
                "connection_status": "TEXT DEFAULT 'unknown'",
            }.items():
                if column not in reading_columns:
                    conn.execute(f"ALTER TABLE tag_readings ADD COLUMN {column} {column_type}")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tag_readings_tag_ts
                ON tag_readings(tag, timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tag_readings_ts
                ON tag_readings(timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tag_readings_equip
                ON tag_readings(equipment_id, timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tag_readings_equip_tag_ts
                ON tag_readings(equipment_id, tag, timestamp);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candidate_events (
                    event_id TEXT PRIMARY KEY,
                    primary_tag TEXT NOT NULL,
                    primary_alarm INTEGER NOT NULL,
                    trigger_timestamp TEXT NOT NULL,
                    raw_deviation_pct REAL NOT NULL,
                    clustered_tags TEXT NOT NULL,
                    equipment_id TEXT NOT NULL,
                    alarm_severity TEXT,
                    status TEXT DEFAULT 'OPEN',
                    updated_at TEXT NOT NULL
                );
            """)
            candidate_columns = {row[1] for row in conn.execute("PRAGMA table_info(candidate_events)")}
            if "alarm_severity" not in candidate_columns:
                conn.execute("ALTER TABLE candidate_events ADD COLUMN alarm_severity TEXT")
            # Phase 2: Additive urgency & lifecycle columns (backward-compatible migration)
            _urgency_cols = {
                "source_priority": "TEXT",
                "urgency_score": "REAL",
                "urgency_band": "TEXT DEFAULT 'UNKNOWN'",
                "urgency_reasons": "TEXT",
                "triggered_rules": "TEXT",
                "data_quality": "TEXT DEFAULT 'VALID'",
                "time_to_limit_seconds": "REAL",
                "repeat_count": "INTEGER DEFAULT 1",
                "lifecycle_state": "TEXT DEFAULT 'ACTIVE'",
                "first_seen_timestamp": "TEXT",
                "last_seen_timestamp": "TEXT",
                "scoring_breakdown": "TEXT",
                "ttl_unavailable_reason": "TEXT",
            }
            for col, col_type in _urgency_cols.items():
                if col not in candidate_columns:
                    conn.execute(f"ALTER TABLE candidate_events ADD COLUMN {col} {col_type}")
            # Individual alarms table for Layer 3 non-destructive preservation
            conn.execute("""
                CREATE TABLE IF NOT EXISTS individual_alarms (
                    alarm_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    equipment_id TEXT NOT NULL,
                    alarm_type TEXT NOT NULL DEFAULT 'EXCURSION',
                    value TEXT NOT NULL,
                    threshold REAL,
                    source_priority TEXT,
                    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
                    repeat_count INTEGER NOT NULL DEFAULT 1,
                    first_seen_timestamp TEXT NOT NULL,
                    last_seen_timestamp TEXT NOT NULL,
                    cleared_timestamp TEXT,
                    acknowledged_timestamp TEXT,
                    fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_individual_alarms_incident
                ON individual_alarms(incident_id);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_individual_alarms_fingerprint
                ON individual_alarms(fingerprint);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candidate_events_equip
                ON candidate_events(equipment_id, trigger_timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candidate_events_ts
                ON candidate_events(trigger_timestamp);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS correlated_events (
                    event_id TEXT PRIMARY KEY,
                    primary_tag TEXT NOT NULL,
                    primary_alarm INTEGER NOT NULL,
                    trigger_timestamp TEXT NOT NULL,
                    raw_deviation_pct REAL NOT NULL,
                    clustered_tags TEXT NOT NULL,
                    correlated_deviations TEXT NOT NULL,
                    equipment_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_correlated_events_ts
                ON correlated_events(trigger_timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_correlated_events_equip
                ON correlated_events(equipment_id, trigger_timestamp);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS event_stories (
                    event_id TEXT PRIMARY KEY,
                    steps TEXT NOT NULL,
                    causal_label TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    event_id TEXT PRIMARY KEY,
                    likely_contributor_tag TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    confidence_label TEXT NOT NULL,
                    supporting_deltas TEXT NOT NULL,
                    scoring_breakdown TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sop_matches (
                    event_id TEXT PRIMARY KEY,
                    sop_id TEXT NOT NULL,
                    sop_title TEXT NOT NULL,
                    match_score REAL NOT NULL,
                    steps TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            # Additive migration for Qdrant RAG trace fields. Existing edge
            # installations keep their SOP records while gaining the new data.
            sop_columns = {row[1] for row in conn.execute("PRAGMA table_info(sop_matches)")}
            for column, sql_type in (
                ("revision", "TEXT"),
                ("semantic_similarity", "REAL"),
                ("retrieval_method", "TEXT"),
                ("embedding_model", "TEXT"),
                ("query_context", "TEXT"),
                ("why_retrieved", "TEXT"),
                ("retrieved_chunks", "TEXT"),
                ("rag_trace", "TEXT"),
                ("retrieval_status", "TEXT DEFAULT 'match_found'"),
                ("retrieval_error", "TEXT"),
            ):
                if column not in sop_columns:
                    conn.execute(f"ALTER TABLE sop_matches ADD COLUMN {column} {sql_type}")
            conn.execute("""
                UPDATE sop_matches SET retrieval_status = 'no_match'
                WHERE sop_id IN ('NONE', 'SOP-NONE', 'UNKNOWN-SOP')
                  AND COALESCE(retrieved_chunks, '[]') = '[]'
                  AND retrieval_status = 'match_found'
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guidance (
                    event_id TEXT PRIMARY KEY,
                    explanation_text TEXT NOT NULL,
                    next_best_actions TEXT NOT NULL,
                    cited_sop_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_guidance_event
                ON guidance(event_id);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS operator_actions (
                    action_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (event_id) REFERENCES event_stories(event_id)
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_operator_actions_event
                ON operator_actions(event_id);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_operator_actions_ts
                ON operator_actions(timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_operator_actions_event_ts
                ON operator_actions(event_id, timestamp);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assistant_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_assistant_messages_convo
                ON assistant_messages(conversation_id, event_id, id);
            """)

    def insert_reading(self, reading: TagReading) -> int:
        """
        Write-through insert of a single TagReading into SQLite.
        Immediately committed so downstream pollers observe new state.
        """
        conn = self._get_connection()

        # Determine numeric value for SQL REAL and raw text representation
        if isinstance(reading.value, bool):
            num_val = 1.0 if reading.value else 0.0
            raw_val = "true" if reading.value else "false"
        elif isinstance(reading.value, (int, float)):
            num_val = float(reading.value)
            raw_val = str(reading.value)
        else:
            num_val = None
            raw_val = str(reading.value)

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO tag_readings (tag, value, value_raw, timestamp, unit, equipment_id,
                    received_timestamp, data_quality, data_source, connection_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reading.tag,
                    num_val,
                    raw_val,
                    reading.timestamp,
                    reading.unit,
                    reading.equipment_id,
                    reading.received_timestamp,
                    reading.data_quality,
                    reading.data_source,
                    reading.connection_status,
                )
            )
            return cursor.lastrowid

    def insert_readings_batch(self, readings: List[TagReading]) -> None:
        """Batch insert multiple TagReadings within a single transaction."""
        if not readings:
            return
        conn = self._get_connection()
        rows = []
        for r in readings:
            if isinstance(r.value, bool):
                num_val = 1.0 if r.value else 0.0
                raw_val = "true" if r.value else "false"
            elif isinstance(r.value, (int, float)):
                num_val = float(r.value)
                raw_val = str(r.value)
            else:
                num_val = None
                raw_val = str(r.value)
            rows.append((r.tag, num_val, raw_val, r.timestamp, r.unit, r.equipment_id,
                         r.received_timestamp, r.data_quality, r.data_source, r.connection_status))

        with conn:
            conn.executemany(
                """
                INSERT INTO tag_readings (tag, value, value_raw, timestamp, unit, equipment_id,
                    received_timestamp, data_quality, data_source, connection_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows
            )

    def get_readings(
        self,
        tag: Optional[str] = None,
        equipment_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: Optional[int] = None,
        order_desc: bool = False
    ) -> List[TagReading]:
        """Query tag readings with flexible filters."""
        conn = self._get_connection()
        clauses = []
        params: List[Any] = []

        if tag:
            clauses.append("tag = ?")
            params.append(tag)
        if equipment_id:
            clauses.append("equipment_id = ?")
            params.append(equipment_id)
        if start_time:
            clauses.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("timestamp <= ?")
            params.append(end_time)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_dir = "DESC" if order_desc else "ASC"
        limit_sql = f"LIMIT {int(limit)}" if limit else ""

        query = f"""
            SELECT tag, value, value_raw, timestamp, unit, equipment_id,
                   received_timestamp, data_quality, data_source, connection_status
            FROM tag_readings
            {where_sql}
            ORDER BY timestamp {order_dir}, id {order_dir}
            {limit_sql}
        """

        cursor = conn.execute(query, params)
        readings: List[TagReading] = []
        for row in cursor.fetchall():
            raw = row["value_raw"]
            # Reconstruct typed value
            if raw == "true":
                typed_val: Union[float, bool, str] = True
            elif raw == "false":
                typed_val = False
            elif row["value"] is not None:
                typed_val = float(row["value"])
            else:
                typed_val = raw

            readings.append(
                TagReading(
                    tag=row["tag"],
                    value=typed_val,
                    timestamp=row["timestamp"],
                    unit=row["unit"],
                    equipment_id=row["equipment_id"],
                    received_timestamp=row["received_timestamp"] or row["timestamp"],
                    data_quality=row["data_quality"] or "UNKNOWN",
                    data_source=row["data_source"] or "unknown",
                    connection_status=row["connection_status"] or "unknown",
                )
            )
        return readings

    @staticmethod
    def _context_query_bounds(start_time: str, end_time: str) -> tuple[str, str]:
        """Wide indexed bounds; exact UTC filtering happens in ContextBuilder."""
        from datetime import datetime, timedelta, timezone

        def parse(value: str) -> datetime:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        lower = (parse(start_time) - timedelta(days=2)).date().isoformat() + "T00:00:00"
        upper = (parse(end_time) + timedelta(days=2)).date().isoformat() + "T23:59:59.999999"
        return lower, upper

    def get_context_readings(self, equipment_id: str, tags: List[str], start_time: str,
                             end_time: str) -> List[Dict[str, Any]]:
        """Read candidate context measurements through indexed equipment/time columns."""
        if not tags:
            return []
        lower, upper = self._context_query_bounds(start_time, end_time)
        placeholders = ",".join("?" for _ in tags)
        rows = self._get_connection().execute(
            f"""SELECT id, tag, value, value_raw, timestamp, unit, equipment_id,
                       received_timestamp, data_quality, data_source, connection_status
                FROM tag_readings
                WHERE equipment_id = ? AND tag IN ({placeholders})
                  AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC, id ASC""",
            (equipment_id, *tags, lower, upper),
        ).fetchall()
        results = []
        for row in rows:
            raw = row["value_raw"]
            if raw == "true":
                value: Union[float, bool, str] = True
            elif raw == "false":
                value = False
            elif row["value"] is not None:
                value = float(row["value"])
            else:
                value = raw
            results.append({"record_id": row["id"], "tag": row["tag"], "value": value,
                            "timestamp": row["timestamp"], "unit": row["unit"],
                            "equipment_id": row["equipment_id"],
                            "received_timestamp": row["received_timestamp"] or row["timestamp"],
                            "data_quality": row["data_quality"] or "UNKNOWN",
                            "data_source": row["data_source"] or "unknown",
                            "connection_status": row["connection_status"] or "unknown"})
        return results

    def get_context_events(self, equipment_id: str, start_time: str, end_time: str,
                           include_event_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Read related alarm/event metadata with status derived from audit actions."""
        lower, upper = self._context_query_bounds(start_time, end_time)
        clauses = ["(ce.equipment_id = ? AND ce.trigger_timestamp >= ? AND ce.trigger_timestamp <= ?)"]
        params: List[Any] = [equipment_id, lower, upper]
        if include_event_id:
            clauses.append("ce.event_id = ?")
            params.append(include_event_id)
        rows = self._get_connection().execute(
            f"""SELECT ce.event_id, ce.primary_tag, ce.primary_alarm,
                       ce.trigger_timestamp, ce.raw_deviation_pct, ce.clustered_tags,
                       ce.equipment_id, ce.alarm_severity,
                       CASE (SELECT UPPER(oa.action_type) FROM operator_actions oa
                             WHERE oa.event_id = ce.event_id
                               AND UPPER(oa.action_type) IN ('RESOLVE', 'RESOLVED', 'ACKNOWLEDGE', 'ACKNOWLEDGED', 'MARK_UNRESOLVED')
                             ORDER BY julianday(oa.timestamp) DESC, oa.timestamp DESC, oa.created_at DESC, oa.rowid DESC LIMIT 1)
                         WHEN 'RESOLVE' THEN 'RESOLVED'
                         WHEN 'RESOLVED' THEN 'RESOLVED'
                         WHEN 'ACKNOWLEDGE' THEN 'ACKNOWLEDGED'
                         WHEN 'ACKNOWLEDGED' THEN 'ACKNOWLEDGED'
                         WHEN 'MARK_UNRESOLVED' THEN 'UNRESOLVED'
                         ELSE 'OPEN'
                       END AS status
                FROM candidate_events ce WHERE {' OR '.join(clauses)}
                ORDER BY ce.trigger_timestamp ASC, ce.event_id ASC""",
            params,
        ).fetchall()
        return [{"event_id": row["event_id"], "alarm_id": row["primary_tag"],
                 "primary_alarm": bool(row["primary_alarm"]), "timestamp": row["trigger_timestamp"],
                 "raw_deviation_pct": row["raw_deviation_pct"], "tags": json.loads(row["clustered_tags"]),
                 "equipment_id": row["equipment_id"], "configured_severity": row["alarm_severity"],
                 "status": row["status"]} for row in rows]

    def get_context_actions(self, event_ids: List[str], start_time: str,
                            end_time: str) -> List[Dict[str, Any]]:
        """Read time-windowed actions for selected/related events via the timestamp index."""
        if not event_ids:
            return []
        lower, upper = self._context_query_bounds(start_time, end_time)
        placeholders = ",".join("?" for _ in event_ids)
        rows = self._get_connection().execute(
            f"""SELECT action_id, event_id, operator, action_type, timestamp, notes
                FROM operator_actions WHERE event_id IN ({placeholders})
                  AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC, action_id ASC""",
            (*event_ids, lower, upper),
        ).fetchall()
        return [{"action_id": row["action_id"], "event_id": row["event_id"],
                 "operator": row["operator"], "action_type": row["action_type"],
                 "timestamp": row["timestamp"], "notes": row["notes"]} for row in rows]

    def get_latest_reading(self, tag: str) -> Optional[TagReading]:
        """Fetch the chronologically latest reading, including ISO timezone offsets."""
        conn = self._get_connection()
        row = conn.execute(
            """SELECT tag, value, value_raw, timestamp, unit, equipment_id,
                      received_timestamp, data_quality, data_source, connection_status
               FROM tag_readings WHERE tag = ?
               ORDER BY julianday(timestamp) DESC, timestamp DESC, id DESC LIMIT 1""",
            (tag,),
        ).fetchone()
        if row is None:
            return None
        raw = row["value_raw"]
        if raw == "true":
            typed_value: Union[float, bool, str] = True
        elif raw == "false":
            typed_value = False
        else:
            try:
                typed_value = float(raw)
            except (TypeError, ValueError):
                typed_value = raw
        return TagReading(
            tag=row["tag"], value=typed_value, timestamp=row["timestamp"],
            unit=row["unit"], equipment_id=row["equipment_id"],
            received_timestamp=row["received_timestamp"] or row["timestamp"],
            data_quality=row["data_quality"] or "UNKNOWN",
            data_source=row["data_source"] or "unknown",
            connection_status=row["connection_status"] or "unknown",
        )

    def get_count(self, tag: Optional[str] = None) -> int:
        """Get total rows in tag_readings table."""
        conn = self._get_connection()
        if tag:
            cur = conn.execute("SELECT COUNT(*) FROM tag_readings WHERE tag = ?", (tag,))
        else:
            cur = conn.execute("SELECT COUNT(*) FROM tag_readings")
        return cur.fetchone()[0]

    def clear_readings(self) -> None:
        """Wipe all readings from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM tag_readings")

    def save_candidate_event(self, event: CandidateEvent, equipment_id: str) -> None:
        """
        Upsert a CandidateEvent record in candidate_events table.
        Writes urgency assessment, lifecycle state, and repeat count when present.
        """
        conn = self._get_connection()
        clustered_json = json.dumps(event.clustered_tags)
        alarm_int = 1 if event.primary_alarm else 0
        updated_ts = event.trigger_timestamp

        # Extract urgency fields from assessment object if present
        urgency = event.urgency
        urgency_score = None
        urgency_band = "UNKNOWN"
        urgency_reasons_json = None
        triggered_rules_json = None
        data_quality = "VALID"
        time_to_limit_seconds = None
        if urgency is not None:
            urgency_score = urgency.urgency_score
            urgency_band = urgency.urgency_band
            urgency_reasons_json = json.dumps(urgency.urgency_reasons)
            triggered_rules_json = json.dumps(urgency.triggered_rules)
            data_quality = urgency.data_quality
            if urgency.time_to_limit and urgency.time_to_limit.time_to_limit_seconds is not None:
                time_to_limit_seconds = urgency.time_to_limit.time_to_limit_seconds

        first_seen = event.first_seen_timestamp or event.trigger_timestamp
        last_seen = event.last_seen_timestamp or event.trigger_timestamp
        scoring_breakdown_json = json.dumps(urgency.scoring_breakdown) if urgency and urgency.scoring_breakdown else None
        ttl_unavailable_reason = urgency.ttl_unavailable_reason if urgency else None

        with conn:
            conn.execute(
                """
                INSERT INTO candidate_events (
                    event_id, primary_tag, primary_alarm, trigger_timestamp,
                    raw_deviation_pct, clustered_tags, equipment_id, alarm_severity, status, updated_at,
                    source_priority, urgency_score, urgency_band, urgency_reasons, triggered_rules,
                    data_quality, time_to_limit_seconds, repeat_count, lifecycle_state,
                    first_seen_timestamp, last_seen_timestamp, scoring_breakdown, ttl_unavailable_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    primary_tag = excluded.primary_tag,
                    primary_alarm = excluded.primary_alarm,
                    trigger_timestamp = excluded.trigger_timestamp,
                    raw_deviation_pct = excluded.raw_deviation_pct,
                    clustered_tags = excluded.clustered_tags,
                    alarm_severity = excluded.alarm_severity,
                    updated_at = excluded.updated_at,
                    source_priority = excluded.source_priority,
                    urgency_score = excluded.urgency_score,
                    urgency_band = excluded.urgency_band,
                    urgency_reasons = excluded.urgency_reasons,
                    triggered_rules = excluded.triggered_rules,
                    data_quality = excluded.data_quality,
                    time_to_limit_seconds = excluded.time_to_limit_seconds,
                    repeat_count = excluded.repeat_count,
                    lifecycle_state = excluded.lifecycle_state,
                    last_seen_timestamp = excluded.last_seen_timestamp,
                    scoring_breakdown = excluded.scoring_breakdown,
                    ttl_unavailable_reason = excluded.ttl_unavailable_reason
                """,
                (
                    event.event_id,
                    event.primary_tag,
                    alarm_int,
                    event.trigger_timestamp,
                    event.raw_deviation_pct,
                    clustered_json,
                    equipment_id,
                    event.alarm_severity,
                    updated_ts,
                    event.source_priority,
                    urgency_score,
                    urgency_band,
                    urgency_reasons_json,
                    triggered_rules_json,
                    data_quality,
                    time_to_limit_seconds,
                    event.repeat_count,
                    event.lifecycle_state,
                    first_seen,
                    last_seen,
                    scoring_breakdown_json,
                    ttl_unavailable_reason,
                )
            )

    def save_individual_alarm(self, incident_id: str, record) -> None:
        """Persist an IndividualAlarmRecord into the individual_alarms table."""
        from models import current_iso_utc
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO individual_alarms (
                    alarm_id, incident_id, tag, equipment_id, alarm_type,
                    value, threshold, source_priority, lifecycle_state, repeat_count,
                    first_seen_timestamp, last_seen_timestamp, cleared_timestamp,
                    acknowledged_timestamp, fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alarm_id) DO UPDATE SET
                    repeat_count = excluded.repeat_count,
                    lifecycle_state = excluded.lifecycle_state,
                    last_seen_timestamp = excluded.last_seen_timestamp,
                    cleared_timestamp = excluded.cleared_timestamp,
                    acknowledged_timestamp = excluded.acknowledged_timestamp,
                    value = excluded.value
                """,
                (
                    record.alarm_id,
                    incident_id,
                    record.tag,
                    record.equipment_id,
                    record.alarm_type,
                    str(record.value),
                    record.threshold,
                    record.source_priority,
                    record.lifecycle_state,
                    record.repeat_count,
                    record.first_seen_timestamp,
                    record.last_seen_timestamp,
                    record.cleared_timestamp,
                    record.acknowledged_timestamp,
                    record.fingerprint,
                    current_iso_utc(),
                )
            )

    def get_individual_alarms(self, incident_id: str) -> List[dict]:
        """Retrieve all individual alarm records for an incident."""
        conn = self._get_connection()
        cursor = conn.execute(
            """SELECT alarm_id, incident_id, tag, equipment_id, alarm_type,
                      value, threshold, source_priority, lifecycle_state, repeat_count,
                      first_seen_timestamp, last_seen_timestamp, cleared_timestamp,
                      acknowledged_timestamp, fingerprint, created_at
               FROM individual_alarms WHERE incident_id = ?
               ORDER BY first_seen_timestamp ASC""",
            (incident_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_candidate_events(
        self,
        equipment_id: Optional[str] = None,
        event_id: Optional[str] = None
    ) -> List[CandidateEvent]:
        """Fetch CandidateEvent records from SQLite."""
        conn = self._get_connection()
        clauses = []
        params = []
        if equipment_id:
            clauses.append("equipment_id = ?")
            params.append(equipment_id)
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT event_id, primary_tag, primary_alarm, trigger_timestamp,
                   raw_deviation_pct, clustered_tags, equipment_id, alarm_severity,
                   source_priority, urgency_score, urgency_band, urgency_reasons,
                   triggered_rules, data_quality, time_to_limit_seconds,
                   repeat_count, lifecycle_state, first_seen_timestamp, last_seen_timestamp,
                   scoring_breakdown, ttl_unavailable_reason
            FROM candidate_events
            {where_sql}
            ORDER BY trigger_timestamp ASC
        """
        cursor = conn.execute(query, params)
        results: List[CandidateEvent] = []
        for row in cursor.fetchall():
            clustered = json.loads(row["clustered_tags"])
            # Reconstruct urgency assessment if columns present
            urgency = None
            try:
                from models import UrgencyAssessment
                row_keys = row.keys()
                if row["urgency_band"] or row["urgency_score"] is not None:
                    breakdown = {}
                    if "scoring_breakdown" in row_keys and row["scoring_breakdown"]:
                        try:
                            breakdown = json.loads(row["scoring_breakdown"])
                        except Exception:
                            pass
                    ttl_reason = row["ttl_unavailable_reason"] if "ttl_unavailable_reason" in row_keys else None
                    urgency = UrgencyAssessment(
                        source_priority=row["source_priority"],
                        urgency_score=row["urgency_score"],
                        urgency_band=row["urgency_band"] or "UNKNOWN",
                        urgency_reasons=json.loads(row["urgency_reasons"]) if row["urgency_reasons"] else [],
                        triggered_rules=json.loads(row["triggered_rules"]) if row["triggered_rules"] else [],
                        data_quality=row["data_quality"] or "VALID",
                        ttl_unavailable_reason=ttl_reason,
                        scoring_breakdown=breakdown,
                    )
            except Exception:
                pass
            results.append(
                CandidateEvent(
                    event_id=row["event_id"],
                    primary_tag=row["primary_tag"],
                    primary_alarm=bool(row["primary_alarm"]),
                    trigger_timestamp=row["trigger_timestamp"],
                    raw_deviation_pct=float(row["raw_deviation_pct"]),
                    clustered_tags=clustered,
                    alarm_severity=row["alarm_severity"],
                    source_priority=row["source_priority"],
                    urgency=urgency,
                    repeat_count=row["repeat_count"] or 1,
                    lifecycle_state=row["lifecycle_state"] or "ACTIVE",
                    first_seen_timestamp=row["first_seen_timestamp"],
                    last_seen_timestamp=row["last_seen_timestamp"],
                )
            )
        return results

    def get_candidate_event_count(self) -> int:
        """Get total rows in candidate_events table."""
        conn = self._get_connection()
        cur = conn.execute("SELECT COUNT(*) FROM candidate_events")
        return cur.fetchone()[0]

    def get_recent_event_ids(self, limit: int = 10) -> List[str]:
        """Return recent persisted event IDs ordered by source trigger time."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT event_id FROM candidate_events
            ORDER BY trigger_timestamp DESC, updated_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 100)),)
        )
        return [row["event_id"] for row in cursor.fetchall()]

    def clear_candidate_events(self) -> None:
        """Wipe all candidate_events from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM candidate_events")

    def save_correlated_event(self, event: CorrelatedEvent, equipment_id: str) -> None:
        """Upsert a CorrelatedEvent into correlated_events table."""
        conn = self._get_connection()
        clustered_json = json.dumps(event.clustered_tags)
        correlated_json = json.dumps([d.model_dump() if hasattr(d, "model_dump") else d.dict() for d in event.correlated_deviations])
        alarm_int = 1 if event.primary_alarm else 0
        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        with conn:
            conn.execute(
                """
                INSERT INTO correlated_events (
                    event_id, primary_tag, primary_alarm, trigger_timestamp,
                    raw_deviation_pct, clustered_tags, correlated_deviations,
                    equipment_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    primary_tag = excluded.primary_tag,
                    primary_alarm = excluded.primary_alarm,
                    raw_deviation_pct = excluded.raw_deviation_pct,
                    clustered_tags = excluded.clustered_tags,
                    correlated_deviations = excluded.correlated_deviations,
                    created_at = excluded.created_at
                """,
                (
                    event.event_id,
                    event.primary_tag,
                    alarm_int,
                    event.trigger_timestamp,
                    event.raw_deviation_pct,
                    clustered_json,
                    correlated_json,
                    equipment_id,
                    now_ts
                )
            )

    def get_correlated_events(
        self,
        equipment_id: Optional[str] = None,
        event_id: Optional[str] = None
    ) -> List[CorrelatedEvent]:
        """Fetch CorrelatedEvent records from SQLite."""
        conn = self._get_connection()
        clauses = []
        params = []
        if equipment_id:
            clauses.append("equipment_id = ?")
            params.append(equipment_id)
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT event_id, primary_tag, primary_alarm, trigger_timestamp,
                   raw_deviation_pct, clustered_tags, correlated_deviations, equipment_id
            FROM correlated_events
            {where_sql}
            ORDER BY trigger_timestamp ASC
        """
        cursor = conn.execute(query, params)
        results: List[CorrelatedEvent] = []
        for row in cursor.fetchall():
            clustered = json.loads(row["clustered_tags"])
            devs_data = json.loads(row["correlated_deviations"])
            deviations = [CorrelatedDeviation(**d) for d in devs_data]
            results.append(
                CorrelatedEvent(
                    event_id=row["event_id"],
                    primary_tag=row["primary_tag"],
                    primary_alarm=bool(row["primary_alarm"]),
                    trigger_timestamp=row["trigger_timestamp"],
                    raw_deviation_pct=float(row["raw_deviation_pct"]),
                    clustered_tags=clustered,
                    correlated_deviations=deviations
                )
            )
        return results

    def clear_correlated_events(self) -> None:
        """Wipe all correlated_events from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM correlated_events")

    def save_event_story(self, story: EventStory) -> None:
        """Persist or update an EventStory in SQLite."""
        conn = self._get_connection()
        steps_json = json.dumps([s.model_dump() for s in story.steps])
        now_ts = current_iso_utc()
        with conn:
            conn.execute(
                """
                INSERT INTO event_stories (
                    event_id, steps, causal_label, created_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    steps = excluded.steps,
                    causal_label = excluded.causal_label,
                    created_at = excluded.created_at
                """,
                (
                    story.event_id,
                    steps_json,
                    story.causal_label,
                    now_ts
                )
            )

    def get_event_stories(self, event_id: Optional[str] = None) -> List[EventStory]:
        """Fetch EventStory records from SQLite."""
        conn = self._get_connection()
        clauses = []
        params = []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT event_id, steps, causal_label, created_at
            FROM event_stories
            {where_sql}
            ORDER BY created_at ASC
        """
        cursor = conn.execute(query, params)
        results: List[EventStory] = []
        for row in cursor.fetchall():
            steps_data = json.loads(row["steps"])
            steps = [EventStoryStep(**s) for s in steps_data]
            results.append(
                EventStory(
                    event_id=row["event_id"],
                    steps=steps,
                    causal_label=row["causal_label"]
                )
            )
        return results

    def clear_event_stories(self) -> None:
        """Wipe all event_stories from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM event_stories")

    def save_evidence(
        self,
        evidence: Evidence,
        breakdown: Optional[Dict[str, Any]] = None
    ) -> None:
        """Persist or update an Evidence record in SQLite with full audit breakdown."""
        conn = self._get_connection()
        deltas_json = json.dumps([d.model_dump() for d in evidence.supporting_deltas])
        breakdown_json = json.dumps(breakdown or {})
        now_ts = current_iso_utc()
        with conn:
            conn.execute(
                """
                INSERT INTO evidence (
                    event_id, likely_contributor_tag, confidence_score,
                    confidence_label, supporting_deltas, scoring_breakdown, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    likely_contributor_tag = excluded.likely_contributor_tag,
                    confidence_score = excluded.confidence_score,
                    confidence_label = excluded.confidence_label,
                    supporting_deltas = excluded.supporting_deltas,
                    scoring_breakdown = excluded.scoring_breakdown,
                    created_at = excluded.created_at
                """,
                (
                    evidence.event_id,
                    evidence.likely_contributor_tag,
                    float(evidence.confidence_score),
                    evidence.confidence_label,
                    deltas_json,
                    breakdown_json,
                    now_ts
                )
            )

    def get_evidence(self, event_id: Optional[str] = None) -> List[Evidence]:
        """Fetch Evidence records from SQLite."""
        conn = self._get_connection()
        clauses = []
        params = []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT event_id, likely_contributor_tag, confidence_score,
                   confidence_label, supporting_deltas
            FROM evidence
            {where_sql}
            ORDER BY created_at ASC
        """
        cursor = conn.execute(query, params)
        results: List[Evidence] = []
        for row in cursor.fetchall():
            deltas_data = json.loads(row["supporting_deltas"])
            deltas = [SupportingDelta(**d) for d in deltas_data]
            results.append(
                Evidence(
                    event_id=row["event_id"],
                    likely_contributor_tag=row["likely_contributor_tag"],
                    confidence_score=float(row["confidence_score"]),
                    confidence_label=row["confidence_label"],
                    supporting_deltas=deltas
                )
            )
        return results

    def get_evidence_audit(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch full evidence audit record including raw scoring breakdown."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT event_id, likely_contributor_tag, confidence_score,
                   confidence_label, supporting_deltas, scoring_breakdown, created_at
            FROM evidence
            WHERE event_id = ?
            """,
            (event_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "event_id": row["event_id"],
            "likely_contributor_tag": row["likely_contributor_tag"],
            "confidence_score": float(row["confidence_score"]),
            "confidence_label": row["confidence_label"],
            "supporting_deltas": json.loads(row["supporting_deltas"]),
            "scoring_breakdown": json.loads(row["scoring_breakdown"]),
            "created_at": row["created_at"]
        }

    def clear_evidence(self) -> None:
        """Wipe all evidence from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM evidence")

    def save_sop_match(self, match: SopMatch) -> None:
        """Persist or update a SopMatch record in SQLite."""
        conn = self._get_connection()
        steps_json = json.dumps(match.steps)
        now_ts = current_iso_utc()
        with conn:
            conn.execute(
                """
                INSERT INTO sop_matches (
                    event_id, sop_id, sop_title, match_score, steps, source, created_at,
                    revision, semantic_similarity, retrieval_method, embedding_model,
                    query_context, why_retrieved, retrieved_chunks
                    , rag_trace, retrieval_status, retrieval_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    sop_id = excluded.sop_id,
                    sop_title = excluded.sop_title,
                    match_score = excluded.match_score,
                    steps = excluded.steps,
                    source = excluded.source,
                    created_at = excluded.created_at,
                    revision = excluded.revision,
                    semantic_similarity = excluded.semantic_similarity,
                    retrieval_method = excluded.retrieval_method,
                    embedding_model = excluded.embedding_model,
                    query_context = excluded.query_context,
                    why_retrieved = excluded.why_retrieved,
                    retrieved_chunks = excluded.retrieved_chunks,
                    rag_trace = excluded.rag_trace,
                    retrieval_status = excluded.retrieval_status,
                    retrieval_error = excluded.retrieval_error
                """,
                (
                    match.event_id,
                    match.sop_id,
                    match.sop_title,
                    float(match.match_score),
                    steps_json,
                    match.source,
                    now_ts,
                    match.revision,
                    match.semantic_similarity,
                    match.retrieval_method,
                    match.embedding_model,
                    match.query_context,
                    json.dumps(match.why_retrieved or {}),
                    json.dumps(match.retrieved_chunks or []),
                    json.dumps(match.rag_trace or {}),
                    match.retrieval_status,
                    match.retrieval_error,
                )
            )

    def get_sop_matches(self, event_id: Optional[str] = None) -> List[SopMatch]:
        """Fetch SopMatch records from SQLite."""
        conn = self._get_connection()
        clauses = []
        params = []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT event_id, sop_id, sop_title, match_score, steps, source, created_at,
                   revision, semantic_similarity, retrieval_method, embedding_model,
                   query_context, why_retrieved, retrieved_chunks, rag_trace,
                   retrieval_status, retrieval_error
            FROM sop_matches
            {where_sql}
            ORDER BY created_at ASC
        """
        cursor = conn.execute(query, params)
        results: List[SopMatch] = []
        for row in cursor.fetchall():
            steps = json.loads(row["steps"])
            results.append(
                SopMatch(
                    event_id=row["event_id"],
                    sop_id=row["sop_id"],
                    sop_title=row["sop_title"],
                    match_score=float(row["match_score"]),
                    steps=steps,
                    source=row["source"],
                    revision=row["revision"] or "",
                    semantic_similarity=row["semantic_similarity"],
                    retrieval_method=row["retrieval_method"] or "embedding",
                    embedding_model=row["embedding_model"] or "all-MiniLM-L6-v2",
                    query_context=row["query_context"],
                    why_retrieved=json.loads(row["why_retrieved"] or "{}"),
                    retrieved_chunks=json.loads(row["retrieved_chunks"] or "[]"),
                    chunks=json.loads(row["retrieved_chunks"] or "[]"),
                    rag_trace=json.loads(row["rag_trace"] or "{}"),
                    retrieval_status=row["retrieval_status"] or "match_found",
                    retrieval_error=row["retrieval_error"],
                )
            )
        return results

    def clear_sop_matches(self) -> None:
        """Wipe all sop_matches from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM sop_matches")

    def save_guidance(self, guidance: Guidance, source: str = "llm") -> None:
        """
        Persist Guidance contract to SQLite table `guidance`.
        """
        conn = self._get_connection()
        actions_json = json.dumps(guidance.next_best_actions)
        now_ts = current_iso_utc()
        with conn:
            conn.execute(
                """
                INSERT INTO guidance (
                    event_id, explanation_text, next_best_actions, cited_sop_id, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    explanation_text = excluded.explanation_text,
                    next_best_actions = excluded.next_best_actions,
                    cited_sop_id = excluded.cited_sop_id,
                    source = excluded.source,
                    created_at = excluded.created_at
                """,
                (
                    guidance.event_id,
                    guidance.explanation_text,
                    actions_json,
                    guidance.cited_sop_id,
                    source,
                    now_ts
                )
            )

    def get_guidance(self, event_id: Optional[str] = None) -> List[Guidance]:
        """Fetch Guidance records from SQLite."""
        conn = self._get_connection()
        clauses = []
        params = []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT event_id, explanation_text, next_best_actions, cited_sop_id, source, created_at
            FROM guidance
            {where_sql}
            ORDER BY created_at ASC
        """
        cursor = conn.execute(query, params)
        results: List[Guidance] = []
        for row in cursor.fetchall():
            actions = json.loads(row["next_best_actions"])
            results.append(
                Guidance(
                    event_id=row["event_id"],
                    explanation_text=row["explanation_text"],
                    next_best_actions=actions,
                    cited_sop_id=row["cited_sop_id"]
                )
            )
        return results

    def clear_guidance(self) -> None:
        """Wipe all guidance from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM guidance")

    def event_story_exists(self, event_id: str) -> bool:
        """Check if an event_id exists in the event_stories table."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT 1 FROM event_stories WHERE event_id = ? LIMIT 1", (event_id,))
        return cursor.fetchone() is not None

    def save_operator_action(self, action: OperatorAction) -> None:
        """Persist an OperatorAction record to SQLite table `operator_actions`."""
        conn = self._get_connection()
        now_ts = current_iso_utc()
        with conn:
            conn.execute(
                """
                INSERT INTO operator_actions (
                    action_id, event_id, operator, action_type, timestamp, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    event_id = excluded.event_id,
                    operator = excluded.operator,
                    action_type = excluded.action_type,
                    timestamp = excluded.timestamp,
                    notes = excluded.notes,
                    created_at = excluded.created_at
                """,
                (
                    action.action_id,
                    action.event_id,
                    action.operator,
                    action.action_type,
                    action.timestamp,
                    action.notes,
                    now_ts
                )
            )

    def get_operator_actions(self, event_id: Optional[str] = None) -> List[OperatorAction]:
        """Fetch OperatorAction records from SQLite, optionally filtered by event_id."""
        conn = self._get_connection()
        clauses = []
        params = []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT action_id, event_id, operator, action_type, timestamp, notes, created_at
            FROM operator_actions
            {where_sql}
            ORDER BY timestamp ASC
        """
        cursor = conn.execute(query, params)
        results: List[OperatorAction] = []
        for row in cursor.fetchall():
            results.append(
                OperatorAction(
                    action_id=row["action_id"],
                    event_id=row["event_id"],
                    operator=row["operator"],
                    action_type=row["action_type"],
                    timestamp=row["timestamp"],
                    notes=row["notes"]
                )
            )
        return results

    def get_event_status(self, event_id: str) -> str:
        """Return incident lifecycle status from its latest audited transition."""
        row = self._get_connection().execute(
            """
            SELECT UPPER(action_type) AS action_type
            FROM operator_actions
            WHERE event_id = ?
              AND UPPER(action_type) IN ('RESOLVE', 'RESOLVED', 'ACKNOWLEDGE', 'ACKNOWLEDGED', 'MARK_UNRESOLVED')
            ORDER BY julianday(timestamp) DESC, timestamp DESC, created_at DESC, rowid DESC
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()
        action_type = row["action_type"] if row else None
        return {
            "RESOLVE": "RESOLVED",
            "RESOLVED": "RESOLVED",
            "ACKNOWLEDGE": "ACKNOWLEDGED",
            "ACKNOWLEDGED": "ACKNOWLEDGED",
            "MARK_UNRESOLVED": "UNRESOLVED",
        }.get(action_type, "OPEN")

    def get_open_event_ids(self) -> List[str]:
        """
        Fetch event_ids whose latest audited lifecycle transition is not
        RESOLVE or ACKNOWLEDGE. MARK_UNRESOLVED explicitly reopens the event.
        """
        conn = self._get_connection()
        query = """
            SELECT event_id
            FROM event_stories
            WHERE COALESCE((
                SELECT UPPER(oa.action_type)
                FROM operator_actions oa
                WHERE oa.event_id = event_stories.event_id
                  AND UPPER(oa.action_type) IN ('RESOLVED', 'RESOLVE', 'ACKNOWLEDGED', 'ACKNOWLEDGE', 'MARK_UNRESOLVED')
                ORDER BY julianday(oa.timestamp) DESC, oa.timestamp DESC, oa.created_at DESC, oa.rowid DESC
                LIMIT 1
            ), '') NOT IN ('RESOLVED', 'RESOLVE', 'ACKNOWLEDGED', 'ACKNOWLEDGE')
            ORDER BY created_at ASC
        """
        cursor = conn.execute(query)
        return [row["event_id"] for row in cursor.fetchall()]

    def clear_operator_actions(self) -> None:
        """Wipe all operator_actions from SQLite database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM operator_actions")

    def get_events_in_window(self, start_ts: str, end_ts: str) -> List[str]:
        """
        Fetch list of event_ids from event_stories whose trigger_timestamp
        or event timestamp is within [start_ts, end_ts].
        """
        conn = self._get_connection()
        query = """
            SELECT es.event_id, es.steps, es.created_at,
                   COALESCE(ce.trigger_timestamp, core.trigger_timestamp) AS trig_ts
            FROM event_stories es
            LEFT JOIN candidate_events ce ON es.event_id = ce.event_id
            LEFT JOIN correlated_events core ON es.event_id = core.event_id
        """
        cursor = conn.execute(query)
        matching_event_ids: List[str] = []
        for row in cursor.fetchall():
            eid = row["event_id"]
            ts = row["trig_ts"]
            if not ts:
                try:
                    steps = json.loads(row["steps"])
                    if steps and isinstance(steps, list) and "timestamp" in steps[0]:
                        ts = steps[0]["timestamp"]
                except Exception:
                    pass
            if not ts:
                ts = row["created_at"]

            if ts and start_ts <= ts <= end_ts:
                matching_event_ids.append(eid)

        return matching_event_ids

    def get_actions_in_window(self, start_ts: str, end_ts: str) -> List[OperatorAction]:
        """Fetch OperatorAction records with timestamp in [start_ts, end_ts]."""
        conn = self._get_connection()
        query = """
            SELECT action_id, event_id, operator, action_type, timestamp, notes, created_at
            FROM operator_actions
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        cursor = conn.execute(query, (start_ts, end_ts))
        results: List[OperatorAction] = []
        for row in cursor.fetchall():
            results.append(
                OperatorAction(
                    action_id=row["action_id"],
                    event_id=row["event_id"],
                    operator=row["operator"],
                    action_type=row["action_type"],
                    timestamp=row["timestamp"],
                    notes=row["notes"]
                )
            )
        return results

    def is_event_resolved(self, event_id: str) -> bool:
        """
        Check whether an event has been resolved by an action of type RESOLVE or RESOLVED.
        """
        return self.get_event_status(event_id) == "RESOLVED"

    def get_conversation_event_id(self, conversation_id: str) -> Optional[str]:
        conn = self._get_connection()
        row = conn.execute(
            "SELECT event_id FROM assistant_messages WHERE conversation_id = ? LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return row["event_id"] if row else None

    def get_assistant_messages(self, conversation_id: str, event_id: str, limit: int = 8) -> List[Dict[str, str]]:
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT role, content, created_at FROM assistant_messages
            WHERE conversation_id = ? AND event_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, event_id, max(1, min(int(limit), 40))),
        ).fetchall()
        messages = [{"role": row["role"], "content": row["content"], "created_at": row["created_at"]} for row in rows]
        messages.reverse()
        return messages

    def save_assistant_message(self, conversation_id: str, event_id: str, role: str, content: str, created_at: Optional[str] = None) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO assistant_messages (conversation_id, event_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, event_id, role, content[:4000], created_at or current_iso_utc()),
            )

    def get_similar_incidents(
        self,
        equipment_id: str,
        primary_tag: Optional[str],
        day_start: str,
        before_timestamp: str,
        exclude_event_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        params: List[Any] = [equipment_id, day_start, before_timestamp]
        clauses = ["equipment_id = ?", "trigger_timestamp >= ?", "trigger_timestamp <= ?"]
        if primary_tag:
            clauses.append("primary_tag = ?")
            params.append(primary_tag)
        if exclude_event_id:
            clauses.append("event_id != ?")
            params.append(exclude_event_id)
        params.append(max(1, min(int(limit), 20)))
        rows = conn.execute(
            f"""
            SELECT event_id, primary_tag, trigger_timestamp, alarm_severity
            FROM candidate_events
            WHERE {' AND '.join(clauses)}
            ORDER BY trigger_timestamp DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [{
            "event_id": row["event_id"],
            "primary_tag": row["primary_tag"],
            "timestamp": row["trigger_timestamp"],
            "configured_severity": row["alarm_severity"],
        } for row in rows]

    def close(self) -> None:
        """Close SQLite connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

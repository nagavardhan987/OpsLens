"""
OpsLens - Event Story Constructor (Component 5)

Consumes CorrelatedEvent objects from Component 4 and formats them into
human-facing EventStory timelines.
Strictly formatting/ordering layer: does NOT alter or recompute values from
Component 4.
Uses purely generic templating driven by TagRegistryEntry metadata, with
zero scenario-specific if/else branches.
"""

from typing import Optional, List, Union
from models import CorrelatedEvent, EventStory, EventStoryStep, TagRegistryEntry
from tag_registry import get_tag_entry
from database import Database, DEFAULT_DB_PATH


class EventStoryConstructor:
    """
    Constructs structured, human-readable EventStory timelines from CorrelatedEvents.
    All labels and descriptions are generated dynamically via generic templating
    and registry metadata.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db

    def construct_story(self, correlated_event: CorrelatedEvent, persist: bool = True) -> EventStory:
        """
        Produce an EventStory from a CorrelatedEvent:
        1. Sort correlated_deviations chronologically by timestamp.
        2. Create an EventStoryStep for each correlated deviation using generic templating.
        3. Append a final EventStoryStep for the primary alarm/tag itself.
        4. Build causal_label as an arrow-chain (" -> ") from short_labels in temporal order.
        5. Persist to SQLite table `event_stories` (if persist is True and db is provided).
        """
        # Sort correlated_deviations by timestamp ASC
        sorted_devs = sorted(
            correlated_event.correlated_deviations,
            key=lambda d: d.timestamp
        )

        steps: List[EventStoryStep] = []
        step_number = 1

        for dev in sorted_devs:
            entry = get_tag_entry(dev.tag)
            tag_label = entry.short_label if entry.short_label else dev.tag

            # Direction and percentage formatting
            if dev.deviation_pct >= 0:
                direction = "increased"
            else:
                direction = "decreased"
            abs_delta = abs(dev.deviation_pct)

            # Prefer the observed onset reading. Legacy events with no stored
            # sample retain their estimate but label it as baseline-derived.
            if dev.value_after is not None:
                val_before = dev.value_before
                val_after = dev.value_after
                if entry.data_type == "bool":
                    desc = f"{tag_label} ({dev.tag}) annunciated" if val_after else f"{tag_label} ({dev.tag}) cleared"
                elif entry.data_type == "string":
                    desc = f"{tag_label} ({dev.tag}): {val_after}"
                else:
                    desc = f"{tag_label} ({dev.tag}) reading recorded"
                unit = dev.unit or entry.unit
                data_source = dev.data_source or "recorded"
                data_quality = dev.data_quality or "UNKNOWN"
                connection_status = dev.connection_status or "unknown"
            elif entry.data_type == "bool":
                val_before = 0.0
                val_after = 1.0 if dev.deviation_pct > 0 else 0.0
                desc = f"{tag_label} ({dev.tag}) annunciated"
                unit = entry.unit
                data_source = "calculated_from_configured_baseline"
                data_quality = "UNKNOWN"
                connection_status = "unknown"
            else:
                val_before = round((entry.baseline_min + entry.baseline_max) / 2.0, 2)
                val_after = round(val_before * (1.0 + dev.deviation_pct / 100.0), 2)
                desc = f"{tag_label} ({dev.tag}) {direction} by {abs_delta:.1f}%"
                unit = entry.unit
                data_source = "calculated_from_configured_baseline"
                data_quality = "UNKNOWN"
                connection_status = "unknown"

            steps.append(
                EventStoryStep(
                    step_number=step_number,
                    tag=dev.tag,
                    timestamp=dev.timestamp,
                    description=desc,
                    value_before=val_before,
                    value_after=val_after,
                    unit=unit,
                    data_source=data_source,
                    data_quality=data_quality,
                    connection_status=connection_status,
                )
            )
            step_number += 1

        # Final step: Primary alarm / trigger
        primary_entry = get_tag_entry(correlated_event.primary_tag)
        primary_label = primary_entry.short_label if primary_entry.short_label else correlated_event.primary_tag

        telemetry_rows = (correlated_event.temporal_context or {}).get("telemetry") or []
        primary_reading = next((item for item in telemetry_rows if item.get("tag") == correlated_event.primary_tag), {})
        primary_val_before = None
        primary_val_after = primary_reading.get("value")
        primary_unit = primary_reading.get("unit") or primary_entry.unit
        primary_source = primary_reading.get("data_source") or primary_reading.get("source") or "recorded"
        primary_quality = primary_reading.get("data_quality") or primary_reading.get("quality") or "UNKNOWN"
        primary_connection = primary_reading.get("connection_status") or "unknown"

        if primary_entry.data_type == "bool" or correlated_event.primary_alarm:
            if primary_val_after is None:
                primary_val_after = True
                primary_source = "alarm_record"
            primary_desc = f"{primary_label} ({correlated_event.primary_tag}) annunciated (Trip Alarm Active)"
        elif primary_val_after is None:
            primary_val_before = round((primary_entry.baseline_min + primary_entry.baseline_max) / 2.0, 2)
            primary_val_after = round(primary_val_before * (1.0 + correlated_event.raw_deviation_pct / 100.0), 2)
            direction = "increased" if correlated_event.raw_deviation_pct >= 0 else "decreased"
            abs_delta = abs(correlated_event.raw_deviation_pct)
            primary_desc = f"{primary_label} ({correlated_event.primary_tag}) {direction} by {abs_delta:.1f}%"
            primary_source = "calculated_from_configured_baseline"
            primary_quality = "UNKNOWN"

        steps.append(
            EventStoryStep(
                step_number=step_number,
                tag=correlated_event.primary_tag,
                timestamp=primary_reading.get("timestamp") or correlated_event.trigger_timestamp,
                description=primary_desc,
                value_before=primary_val_before,
                value_after=primary_val_after,
                unit=primary_unit,
                data_source=primary_source,
                data_quality=primary_quality,
                connection_status=primary_connection,
            )
        )

        # This legacy field now records chronology, not physical causation.
        chain_labels: List[str] = []
        for step in steps:
            step_entry = get_tag_entry(step.tag)
            label = step_entry.short_label if step_entry.short_label else step.tag
            chain_labels.append(label)

        causal_label = "Recorded chronological sequence (not causal proof): " + " -> ".join(chain_labels)

        story = EventStory(
            event_id=correlated_event.event_id,
            steps=steps,
            causal_label=causal_label
        )

        if persist and self.db:
            self.db.save_event_story(story)

        return story

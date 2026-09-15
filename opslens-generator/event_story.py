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

            # Baseline midpoint as value_before, computed excursion as value_after
            if entry.data_type == "bool":
                val_before = 0.0
                val_after = 1.0 if dev.deviation_pct > 0 else 0.0
                desc = f"{tag_label} ({dev.tag}) annunciated"
            else:
                val_before = round((entry.baseline_min + entry.baseline_max) / 2.0, 2)
                val_after = round(val_before * (1.0 + dev.deviation_pct / 100.0), 2)
                desc = f"{tag_label} ({dev.tag}) {direction} by {abs_delta:.1f}%"

            steps.append(
                EventStoryStep(
                    step_number=step_number,
                    tag=dev.tag,
                    timestamp=dev.timestamp,
                    description=desc,
                    value_before=val_before,
                    value_after=val_after
                )
            )
            step_number += 1

        # Final step: Primary alarm / trigger
        primary_entry = get_tag_entry(correlated_event.primary_tag)
        primary_label = primary_entry.short_label if primary_entry.short_label else correlated_event.primary_tag

        if primary_entry.data_type == "bool" or correlated_event.primary_alarm:
            primary_val_before = 0.0
            primary_val_after = 1.0
            primary_desc = f"{primary_label} ({correlated_event.primary_tag}) annunciated (Trip Alarm Active)"
        else:
            primary_val_before = round((primary_entry.baseline_min + primary_entry.baseline_max) / 2.0, 2)
            primary_val_after = round(primary_val_before * (1.0 + correlated_event.raw_deviation_pct / 100.0), 2)
            direction = "increased" if correlated_event.raw_deviation_pct >= 0 else "decreased"
            abs_delta = abs(correlated_event.raw_deviation_pct)
            primary_desc = f"{primary_label} ({correlated_event.primary_tag}) {direction} by {abs_delta:.1f}%"

        steps.append(
            EventStoryStep(
                step_number=step_number,
                tag=correlated_event.primary_tag,
                timestamp=correlated_event.trigger_timestamp,
                description=primary_desc,
                value_before=primary_val_before,
                value_after=primary_val_after
            )
        )

        # Build causal_label arrow chain from short_labels in step order
        chain_labels: List[str] = []
        for step in steps:
            step_entry = get_tag_entry(step.tag)
            label = step_entry.short_label if step_entry.short_label else step.tag
            chain_labels.append(label)

        causal_label = " -> ".join(chain_labels)

        story = EventStory(
            event_id=correlated_event.event_id,
            steps=steps,
            causal_label=causal_label
        )

        if persist and self.db:
            self.db.save_event_story(story)

        return story

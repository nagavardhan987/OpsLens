"""
OpsLens - Tag Registry Loader

Provides a decoupled interface for downstream engines to inspect tag metadata,
baselines, trip limits, severity weights, and causal topologies without
hardcoding knowledge of component 1.
"""

from typing import Dict, List, Optional, Tuple, Any
from models import TagRegistryEntry
from tag_registry import (
    TAG_REGISTRY,
    get_tag_entry,
    get_all_tags,
    get_equipment_tags,
    get_all_equipment_ids,
    get_upstream_tags,
    get_downstream_tags,
    get_topology_distance,
    to_registry_dict,
)


class RegistryLoader:
    """
    Registry lookup and topology discovery service for downstream analytics engines.
    """

    def __init__(self, registry_source: Optional[Dict[str, TagRegistryEntry]] = None):
        self._registry: Dict[str, TagRegistryEntry] = (
            dict(registry_source) if registry_source is not None else dict(TAG_REGISTRY)
        )

    def get_tag(self, tag: str) -> TagRegistryEntry:
        """Fetch tag registry entry or raise KeyError."""
        if tag not in self._registry:
            raise KeyError(f"Tag '{tag}' not found in registry.")
        return self._registry[tag]

    def get_equipment_tags(self, equipment_id: str) -> List[TagRegistryEntry]:
        """Fetch all tag entries for a given equipment ID."""
        return [entry for entry in self._registry.values() if entry.equipment_id == equipment_id]

    def get_equipment_tag_names(self, equipment_id: str) -> List[str]:
        """Fetch tag names for a given equipment ID."""
        return [entry.tag for entry in self._registry.values() if entry.equipment_id == equipment_id]

    def get_upstream(self, tag: str, recursive: bool = True) -> List[str]:
        """Get upstream tags that causally influence this tag."""
        return get_upstream_tags(tag, recursive=recursive)

    def get_downstream(self, tag: str, recursive: bool = True) -> List[str]:
        """Get downstream tags influenced by this tag."""
        return get_downstream_tags(tag, recursive=recursive)

    def get_topology_distance(self, source_tag: str, target_tag: str) -> Optional[int]:
        """Get directed causal DAG distance from source to target."""
        return get_topology_distance(source_tag, target_tag)

    def get_baseline_range(self, tag: str) -> Tuple[float, float]:
        """Return (baseline_min, baseline_max) for continuous tags."""
        entry = self.get_tag(tag)
        return (entry.baseline_min, entry.baseline_max)

    def get_trip_threshold(self, tag: str) -> Optional[float]:
        """Return trip threshold if defined."""
        return self.get_tag(tag).trip_threshold

    def get_severity_weight(self, tag: str) -> float:
        """Return severity weight (0.0 to 1.0)."""
        return self.get_tag(tag).severity_weight

    def all_tags(self) -> List[str]:
        """Return all registered tag names."""
        return list(self._registry.keys())

    def all_equipment(self) -> List[str]:
        """Return all distinct equipment unit identifiers."""
        return sorted(list({entry.equipment_id for entry in self._registry.values()}))

    def to_dict(self) -> Dict[str, Dict[str, Any]]:
        """Return serialized dictionary representation of registry."""
        return {tag: entry.to_dict() for tag, entry in self._registry.items()}


# Global singleton helper
_DEFAULT_LOADER: Optional[RegistryLoader] = None


def get_registry_loader() -> RegistryLoader:
    """Return shared RegistryLoader instance."""
    global _DEFAULT_LOADER
    if _DEFAULT_LOADER is None:
        _DEFAULT_LOADER = RegistryLoader()
    return _DEFAULT_LOADER

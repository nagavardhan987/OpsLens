"""
OpsLens - Tag Registry & Causal Topology Graph

Defines all plant telemetry tags across equipment units matching the exact
TagRegistryEntry schema. Includes topology links and graph traversal helpers.
"""

from typing import Dict, List, Optional, Any, Set
from collections import deque
from models import TagRegistryEntry

# -----------------------------------------------------------------------------
# Master Tag Registry Definitions (11 tags across 3 units)
# -----------------------------------------------------------------------------

TAG_REGISTRY: Dict[str, TagRegistryEntry] = {
    # -------------------------------------------------------------------------
    # Unit 1: Pump-02 (Feed Water Injection Pump)
    # -------------------------------------------------------------------------
    "VLV-04-POS": TagRegistryEntry(
        tag="VLV-04-POS",
        equipment_id="Pump-02",
        unit="%",
        data_type="float",
        baseline_min=70.0,
        baseline_max=85.0,
        trip_threshold=None,
        severity_weight=0.95,
        topology_upstream=[],
        short_label="Valve restriction",
    ),
    "FIT-02-FLW": TagRegistryEntry(
        tag="FIT-02-FLW",
        equipment_id="Pump-02",
        unit="L/min",
        data_type="float",
        baseline_min=75.0,
        baseline_max=90.0,
        trip_threshold=50.0,  # Low flow alarm threshold
        severity_weight=0.20,
        topology_upstream=["VLV-04-POS"],
        short_label="Flow reduction",
    ),
    "MOT-02-CUR": TagRegistryEntry(
        tag="MOT-02-CUR",
        equipment_id="Pump-02",
        unit="A",
        data_type="float",
        baseline_min=7.0,
        baseline_max=8.2,
        trip_threshold=9.5,  # High motor current trip
        severity_weight=0.15,
        topology_upstream=["FIT-02-FLW"],
        short_label="Motor current surge",
    ),
    "PIT-02-PRS": TagRegistryEntry(
        tag="PIT-02-PRS",
        equipment_id="Pump-02",
        unit="bar",
        data_type="float",
        baseline_min=4.2,
        baseline_max=5.2,
        trip_threshold=6.5,  # High pressure trip
        severity_weight=0.15,
        topology_upstream=["FIT-02-FLW", "MOT-02-CUR"],
        short_label="Pressure surge",
    ),
    "ALM-P02-HP": TagRegistryEntry(
        tag="ALM-P02-HP",
        equipment_id="Pump-02",
        unit="status",
        data_type="bool",
        baseline_min=0.0,
        baseline_max=0.0,
        trip_threshold=1.0,  # Trips at 1.0 (True)
        severity_weight=1.00,
        topology_upstream=["PIT-02-PRS"],
        short_label="High pressure alarm",
    ),

    # -------------------------------------------------------------------------
    # Unit 2: Compressor-01 (Gas Booster Compressor)
    # -------------------------------------------------------------------------
    "CMP-01-SPD": TagRegistryEntry(
        tag="CMP-01-SPD",
        equipment_id="Compressor-01",
        unit="RPM",
        data_type="float",
        baseline_min=2920.0,
        baseline_max=3020.0,
        trip_threshold=3300.0,
        severity_weight=0.40,
        topology_upstream=[],
        short_label="Compressor speed excursion",
    ),
    "CMP-01-VIB": TagRegistryEntry(
        tag="CMP-01-VIB",
        equipment_id="Compressor-01",
        unit="mm/s",
        data_type="float",
        baseline_min=1.2,
        baseline_max=2.8,
        trip_threshold=7.0,  # High vibration limit
        severity_weight=0.95,
        topology_upstream=["CMP-01-SPD"],
        short_label="Bearing vibration",
    ),
    "CMP-01-CUR": TagRegistryEntry(
        tag="CMP-01-CUR",
        equipment_id="Compressor-01",
        unit="A",
        data_type="float",
        baseline_min=46.0,
        baseline_max=52.0,
        trip_threshold=64.0,  # Overload current
        severity_weight=0.25,
        topology_upstream=["CMP-01-SPD", "CMP-01-VIB"],
        short_label="Stator current rise",
    ),
    "CMP-01-TMP": TagRegistryEntry(
        tag="CMP-01-TMP",
        equipment_id="Compressor-01",
        unit="°C",
        data_type="float",
        baseline_min=58.0,
        baseline_max=68.0,
        trip_threshold=85.0,  # Bearing over-temperature limit
        severity_weight=0.25,
        topology_upstream=["CMP-01-VIB"],
        short_label="Bearing temperature rise",
    ),
    "ALM-C01-VB": TagRegistryEntry(
        tag="ALM-C01-VB",
        equipment_id="Compressor-01",
        unit="status",
        data_type="bool",
        baseline_min=0.0,
        baseline_max=0.0,
        trip_threshold=1.0,
        severity_weight=1.00,
        topology_upstream=["CMP-01-VIB", "CMP-01-TMP"],
        short_label="High vibration alarm",
    ),

    # -------------------------------------------------------------------------
    # Unit 3: Tank-01 (Suction Buffer Surge Tank)
    # -------------------------------------------------------------------------
    "TNK-01-LVL": TagRegistryEntry(
        tag="TNK-01-LVL",
        equipment_id="Tank-01",
        unit="%",
        data_type="float",
        baseline_min=55.0,
        baseline_max=65.0,
        trip_threshold=88.0,
        severity_weight=0.50,
        topology_upstream=[],
        short_label="Tank level change",
    ),
}


# -----------------------------------------------------------------------------
# Topology & Registry Helper Functions
# -----------------------------------------------------------------------------

def get_tag_entry(tag: str) -> TagRegistryEntry:
    """Retrieve entry for a tag or raise KeyError."""
    if tag not in TAG_REGISTRY:
        raise KeyError(f"Unknown tag: '{tag}'")
    return TAG_REGISTRY[tag]


def get_all_tags() -> List[str]:
    """List of all registered tag names."""
    return list(TAG_REGISTRY.keys())


def get_equipment_tags(equipment_id: str) -> List[TagRegistryEntry]:
    """Return all tag entries associated with a specific equipment unit."""
    return [entry for entry in TAG_REGISTRY.values() if entry.equipment_id == equipment_id]


def get_all_equipment_ids() -> List[str]:
    """Return distinct equipment IDs."""
    return sorted(list({entry.equipment_id for entry in TAG_REGISTRY.values()}))


def get_upstream_tags(tag: str, recursive: bool = True) -> List[str]:
    """
    Return list of upstream causal tags that directly or indirectly influence this tag.
    """
    if tag not in TAG_REGISTRY:
        return []
    
    if not recursive:
        return list(TAG_REGISTRY[tag].topology_upstream)
    
    visited: Set[str] = set()
    queue = deque(TAG_REGISTRY[tag].topology_upstream)
    ordered_upstream: List[str] = []
    
    while queue:
        curr = queue.popleft()
        if curr not in visited and curr in TAG_REGISTRY:
            visited.add(curr)
            ordered_upstream.append(curr)
            for up in TAG_REGISTRY[curr].topology_upstream:
                if up not in visited:
                    queue.append(up)
                    
    return ordered_upstream


def get_downstream_tags(tag: str, recursive: bool = True) -> List[str]:
    """
    Return list of downstream tags causally influenced by this tag.
    """
    if tag not in TAG_REGISTRY:
        return []

    # Build reverse adjacency map
    reverse_map: Dict[str, List[str]] = {t: [] for t in TAG_REGISTRY}
    for t_name, entry in TAG_REGISTRY.items():
        for up in entry.topology_upstream:
            if up in reverse_map:
                reverse_map[up].append(t_name)

    if not recursive:
        return list(reverse_map.get(tag, []))

    visited: Set[str] = set()
    queue = deque(reverse_map.get(tag, []))
    ordered_downstream: List[str] = []

    while queue:
        curr = queue.popleft()
        if curr not in visited and curr in TAG_REGISTRY:
            visited.add(curr)
            ordered_downstream.append(curr)
            for down in reverse_map.get(curr, []):
                if down not in visited:
                    queue.append(down)

    return ordered_downstream


def get_topology_distance(source_tag: str, target_tag: str) -> Optional[int]:
    """
    Calculate shortest causal directed distance from source_tag to target_tag in the DAG.
    Returns None if target is unreachable from source.
    """
    if source_tag == target_tag:
        return 0
    if source_tag not in TAG_REGISTRY or target_tag not in TAG_REGISTRY:
        return None

    # Adjacency map: upstream -> downstream
    adj: Dict[str, List[str]] = {t: [] for t in TAG_REGISTRY}
    for t_name, entry in TAG_REGISTRY.items():
        for up in entry.topology_upstream:
            if up in adj:
                adj[up].append(t_name)

    queue = deque([(source_tag, 0)])
    visited: Set[str] = {source_tag}

    while queue:
        curr, dist = queue.popleft()
        if curr == target_tag:
            return dist
        for neighbor in adj.get(curr, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))

    return None


def to_registry_dict() -> Dict[str, Dict[str, Any]]:
    """Serialize entire registry to dictionary representation conforming to schema."""
    return {tag: entry.to_dict() for tag, entry in TAG_REGISTRY.items()}

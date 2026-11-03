"""
OpsLens - Tag Registry & Causal Topology Graph

Defines all plant telemetry tags across equipment units matching the exact
TagRegistryEntry schema. Includes topology links and graph traversal helpers.
"""

from typing import Dict, List, Optional, Any, Set
from collections import deque
from models import TagRegistryEntry

# -----------------------------------------------------------------------------
# Master Tag Registry Definitions. Wastewater values below are synthetic
# reference ranges for demonstrations, not approved plant operating limits.
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
    "CMP-01-RUN": TagRegistryEntry(
        tag="CMP-01-RUN", equipment_id="Compressor-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=None, severity_weight=0.3,
        topology_upstream=[], short_label="Compressor operating status",
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

    # -------------------------------------------------------------------------
    # Wastewater reference plant (illustrative 50 MLD conventional process)
    # Flow rates are expressed in m³/h (50 MLD averages about 2,083 m³/h).
    # All ranges and trips are demo configuration and must be replaced with
    # site design, permits, and approved alarm rationalization before use.
    # -------------------------------------------------------------------------
    "LIT-101-WWL": TagRegistryEntry(
        tag="LIT-101-WWL", equipment_id="LiftStation-01", unit="m",
        data_type="float", baseline_min=1.0, baseline_max=2.4,
        trip_threshold=3.6, severity_weight=0.88,
        topology_upstream=["FIT-101-DIS"], short_label="Wet-well level rise",
    ),
    "FIT-101-DIS": TagRegistryEntry(
        tag="FIT-101-DIS", equipment_id="LiftStation-01", unit="m³/h",
        data_type="float", baseline_min=1700.0, baseline_max=2350.0,
        trip_threshold=1200.0, severity_weight=0.64,
        topology_upstream=["PIT-101-DIS", "MOT-101-CUR"],
        short_label="Lift discharge flow reduction",
    ),
    "PIT-101-DIS": TagRegistryEntry(
        tag="PIT-101-DIS", equipment_id="LiftStation-01", unit="bar",
        data_type="float", baseline_min=1.8, baseline_max=3.0,
        trip_threshold=4.2, severity_weight=0.40,
        topology_upstream=[], short_label="Lift discharge pressure",
    ),
    "MOT-101-CUR": TagRegistryEntry(
        tag="MOT-101-CUR", equipment_id="LiftStation-01", unit="A",
        data_type="float", baseline_min=28.0, baseline_max=34.0,
        trip_threshold=42.0, severity_weight=0.38,
        topology_upstream=[], short_label="Lift pump motor current",
    ),
    "ALM-WW-101-HH": TagRegistryEntry(
        tag="ALM-WW-101-HH", equipment_id="LiftStation-01", unit="status",
        data_type="bool", baseline_min=0.0, baseline_max=0.0,
        trip_threshold=1.0, severity_weight=1.0,
        topology_upstream=["LIT-101-WWL"], short_label="Wet-well high-high level",
    ),
    "P101-RUN": TagRegistryEntry(
        tag="P101-RUN", equipment_id="LiftStation-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=None, severity_weight=0.35,
        topology_upstream=[], short_label="Lift pump P-101 running",
    ),
    "P101-FAULT": TagRegistryEntry(
        tag="P101-FAULT", equipment_id="LiftStation-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.85,
        topology_upstream=[], short_label="Lift pump P-101 fault",
    ),
    "FIT-101-P1-FLW": TagRegistryEntry(
        tag="FIT-101-P1-FLW", equipment_id="LiftStation-01", unit="m³/h", data_type="float",
        baseline_min=350.0, baseline_max=450.0, trip_threshold=300.0, severity_weight=0.78,
        topology_upstream=["P101-RUN"], short_label="Lift pump P-101 flow",
    ),
    "FIT-110-IN": TagRegistryEntry(
        tag="FIT-110-IN", equipment_id="InletWorks-01", unit="m³/h",
        data_type="float", baseline_min=1700.0, baseline_max=2350.0,
        trip_threshold=3200.0, severity_weight=0.34,
        topology_upstream=[], short_label="Influent flow",
    ),
    "DPT-110-SCR": TagRegistryEntry(
        tag="DPT-110-SCR", equipment_id="InletWorks-01", unit="kPa",
        data_type="float", baseline_min=0.5, baseline_max=1.5,
        trip_threshold=4.0, severity_weight=0.70,
        topology_upstream=["FIT-110-IN"], short_label="Screen differential pressure",
    ),
    "ALM-SCR-110-DP": TagRegistryEntry(
        tag="ALM-SCR-110-DP", equipment_id="InletWorks-01", unit="status",
        data_type="bool", baseline_min=0.0, baseline_max=0.0,
        trip_threshold=1.0, severity_weight=0.88,
        topology_upstream=["DPT-110-SCR"], short_label="Coarse screen differential pressure high",
    ),
    "SCR-110-RAKE-RUN": TagRegistryEntry(
        tag="SCR-110-RAKE-RUN", equipment_id="InletWorks-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=None, severity_weight=0.4,
        topology_upstream=[], short_label="Screen rake running",
    ),
    "SCR-110-MOT-CUR": TagRegistryEntry(
        tag="SCR-110-MOT-CUR", equipment_id="InletWorks-01", unit="A", data_type="float",
        baseline_min=6.0, baseline_max=9.0, trip_threshold=14.0, severity_weight=0.6,
        topology_upstream=["SCR-110-RAKE-RUN"], short_label="Screen rake motor current",
    ),
    "AIT-201-DO": TagRegistryEntry(
        tag="AIT-201-DO", equipment_id="AerationBasin-01", unit="mg/L",
        data_type="float", baseline_min=1.5, baseline_max=2.5,
        trip_threshold=1.0, severity_weight=0.82,
        topology_upstream=[], short_label="Aeration dissolved oxygen low",
    ),
    "AIT-201-NH4": TagRegistryEntry(
        tag="AIT-201-NH4", equipment_id="AerationBasin-01", unit="mg/L",
        data_type="float", baseline_min=1.0, baseline_max=3.0,
        trip_threshold=8.0, severity_weight=0.70,
        topology_upstream=["AIT-201-DO"], short_label="Ammonia concentration rise",
    ),
    "ALM-AER-201-DO": TagRegistryEntry(
        tag="ALM-AER-201-DO", equipment_id="AerationBasin-01", unit="status",
        data_type="bool", baseline_min=0.0, baseline_max=0.0,
        trip_threshold=1.0, severity_weight=0.88,
        topology_upstream=["AIT-201-DO"], short_label="Aeration dissolved oxygen low alarm",
    ),
    "ALM-AER-201-NH4": TagRegistryEntry(
        tag="ALM-AER-201-NH4", equipment_id="AerationBasin-01", unit="status",
        data_type="bool", baseline_min=0.0, baseline_max=0.0,
        trip_threshold=1.0, severity_weight=0.90,
        topology_upstream=["AIT-201-NH4"], short_label="Ammonia high alarm",
    ),
    "RAS-P1-RUN": TagRegistryEntry(
        tag="RAS-P1-RUN", equipment_id="RASSystem-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=None, severity_weight=0.5,
        topology_upstream=[], short_label="RAS pump P1 running",
    ),
    "RAS-FLOW": TagRegistryEntry(
        tag="RAS-FLOW", equipment_id="RASSystem-01", unit="m³/h", data_type="float",
        baseline_min=700.0, baseline_max=840.0, trip_threshold=550.0, severity_weight=0.82,
        topology_upstream=["RAS-P1-RUN"], short_label="Total return activated sludge flow",
    ),
    "RAS-P1-CUR": TagRegistryEntry(
        tag="RAS-P1-CUR", equipment_id="RASSystem-01", unit="A", data_type="float",
        baseline_min=18.0, baseline_max=26.0, trip_threshold=0.5, severity_weight=0.62,
        topology_upstream=["RAS-P1-RUN"], short_label="RAS pump P1 motor current",
    ),
    "SLB-201-DEPTH": TagRegistryEntry(
        tag="SLB-201-DEPTH", equipment_id="SecondaryClarifier-01", unit="m", data_type="float",
        baseline_min=0.3, baseline_max=0.8, trip_threshold=1.5, severity_weight=0.86,
        topology_upstream=["RAS-FLOW"], short_label="Sludge blanket depth",
    ),
    "ALM-RAS-P1-FAIL": TagRegistryEntry(
        tag="ALM-RAS-P1-FAIL", equipment_id="RASSystem-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.9,
        topology_upstream=["RAS-P1-RUN", "RAS-P1-CUR"], short_label="RAS pump P1 failure alarm",
    ),
    "ALM-SLB-201-HIGH": TagRegistryEntry(
        tag="ALM-SLB-201-HIGH", equipment_id="SecondaryClarifier-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.95,
        topology_upstream=["SLB-201-DEPTH"], short_label="Sludge blanket high alarm",
    ),
    "FLT-401-PRI-NTU": TagRegistryEntry(
        tag="FLT-401-PRI-NTU", equipment_id="Filter-01", unit="NTU", data_type="float",
        baseline_min=0.5, baseline_max=2.0, trip_threshold=5.0, severity_weight=0.7,
        topology_upstream=[], short_label="Filter primary turbidity sensor",
    ),
    "FLT-401-RED-NTU": TagRegistryEntry(
        tag="FLT-401-RED-NTU", equipment_id="Filter-01", unit="NTU", data_type="float",
        baseline_min=0.5, baseline_max=2.0, trip_threshold=None, severity_weight=0.35,
        topology_upstream=["FLT-401-PRI-NTU"], short_label="Filter redundant turbidity sensor",
    ),
    "FLT-401-PRI-QUALITY": TagRegistryEntry(
        tag="FLT-401-PRI-QUALITY", equipment_id="Filter-01", unit="status", data_type="string",
        baseline_min=0.0, baseline_max=0.0, baseline_status="GOOD", trip_threshold=None,
        severity_weight=0.5, topology_upstream=["FLT-401-PRI-NTU"], short_label="Primary sensor signal quality",
    ),
    "FLT-401-PRI-COMMS": TagRegistryEntry(
        tag="FLT-401-PRI-COMMS", equipment_id="Filter-01", unit="status", data_type="string",
        baseline_min=0.0, baseline_max=0.0, baseline_status="CONNECTED", trip_threshold=None,
        severity_weight=0.5, topology_upstream=["FLT-401-PRI-NTU"], short_label="Primary sensor communication status",
    ),
    "ALM-FLT-401-SENSOR": TagRegistryEntry(
        tag="ALM-FLT-401-SENSOR", equipment_id="Filter-01", unit="status", data_type="bool",
        baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.75,
        topology_upstream=["FLT-401-PRI-NTU", "FLT-401-RED-NTU", "FLT-401-PRI-QUALITY", "FLT-401-PRI-COMMS"],
        short_label="Filter primary sensor fault alarm",
    ),
    # Scenario 7 tertiary filtration / UV data. These are illustrative demo
    # ranges, not configured site limits; all generator outputs are simulated.
    "BWP-1-TRIP": TagRegistryEntry(
        tag="BWP-1-TRIP", equipment_id="TertiaryTreatment-01", unit="status",
        data_type="string", baseline_min=0.0, baseline_max=0.0, baseline_status="NORMAL",
        trip_threshold=None, severity_weight=0.65,
        topology_upstream=[], short_label="BWP-1 trip status",
    ),
    "BWP-2-SEL-OFF": TagRegistryEntry(
        tag="BWP-2-SEL-OFF", equipment_id="TertiaryTreatment-01", unit="status",
        data_type="string", baseline_min=0.0, baseline_max=0.0, baseline_status="NORMAL",
        trip_threshold=None, severity_weight=0.55,
        topology_upstream=[], short_label="BWP-2 selector OFF status",
    ),
    "FLT-401-BW-HOURS": TagRegistryEntry(
        tag="FLT-401-BW-HOURS", equipment_id="TertiaryTreatment-01", unit="h",
        data_type="float", baseline_min=0.0, baseline_max=24.0,
        trip_threshold=None, severity_weight=0.70,
        topology_upstream=["BWP-1-TRIP", "BWP-2-SEL-OFF"], short_label="Filter run time since backwash",
    ),
    "FLT-401-HL": TagRegistryEntry(
        tag="FLT-401-HL", equipment_id="TertiaryTreatment-01", unit="m",
        data_type="float", baseline_min=0.8, baseline_max=1.5,
        trip_threshold=None, severity_weight=0.82,
        topology_upstream=["FLT-401-BW-HOURS"], short_label="Filter head loss",
    ),
    "FLT-401-TURB": TagRegistryEntry(
        tag="FLT-401-TURB", equipment_id="TertiaryTreatment-01", unit="NTU",
        data_type="float", baseline_min=0.5, baseline_max=2.0,
        trip_threshold=None, severity_weight=0.88,
        topology_upstream=["FLT-401-HL"], short_label="Filter outlet turbidity",
    ),
    "UV-501-UVT": TagRegistryEntry(
        tag="UV-501-UVT", equipment_id="TertiaryTreatment-01", unit="%",
        data_type="float", baseline_min=65.0, baseline_max=75.0,
        trip_threshold=None, severity_weight=0.90,
        topology_upstream=["FLT-401-TURB"], short_label="UV transmittance",
    ),
    "UV-501-LAMPS-ON": TagRegistryEntry(
        tag="UV-501-LAMPS-ON", equipment_id="TertiaryTreatment-01", unit="lamps",
        data_type="float", baseline_min=24.0, baseline_max=24.0,
        trip_threshold=None, severity_weight=0.84,
        topology_upstream=[], short_label="UV lamps in service",
    ),
    "UV-501-INTENSITY": TagRegistryEntry(
        tag="UV-501-INTENSITY", equipment_id="TertiaryTreatment-01", unit="mW/cm²",
        data_type="float", baseline_min=14.0, baseline_max=18.0,
        trip_threshold=None, severity_weight=0.82,
        topology_upstream=[], short_label="UV intensity",
    ),
    "UV-501-DOSE": TagRegistryEntry(
        tag="UV-501-DOSE", equipment_id="TertiaryTreatment-01", unit="mJ/cm²",
        data_type="float", baseline_min=30.0, baseline_max=40.0,
        trip_threshold=None, severity_weight=0.98,
        topology_upstream=["FLT-401-HL", "FLT-401-TURB", "UV-501-UVT", "UV-501-LAMPS-ON", "UV-501-INTENSITY"],
        short_label="UV dose delivered",
    ),
    "ALM-UV-501-DOSE-LOW": TagRegistryEntry(
        tag="ALM-UV-501-DOSE-LOW", equipment_id="TertiaryTreatment-01", unit="status",
        data_type="bool", baseline_min=0.0, baseline_max=0.0,
        trip_threshold=1.0, severity_weight=1.0,
        topology_upstream=["UV-501-DOSE", "BWP-1-TRIP", "BWP-2-SEL-OFF", "FLT-401-BW-HOURS"],
        short_label="UV dose low alarm",
    ),
    "RLV-501-CLOSED": TagRegistryEntry(
        tag="RLV-501-CLOSED", equipment_id="TertiaryTreatment-01", unit="status",
        data_type="string", baseline_min=0.0, baseline_max=0.0, baseline_status="NORMAL",
        trip_threshold=None, severity_weight=0.5,
        topology_upstream=["ALM-UV-501-DOSE-LOW"], short_label="Reuse-line closed status",
    ),
    "CHL-501-BACKUP-STATUS": TagRegistryEntry(
        tag="CHL-501-BACKUP-STATUS", equipment_id="TertiaryTreatment-01", unit="status",
        data_type="string", baseline_min=0.0, baseline_max=0.0, baseline_status="NORMAL",
        trip_threshold=None, severity_weight=0.45,
        topology_upstream=["ALM-UV-501-DOSE-LOW"], short_label="Backup-disinfection status",
    ),
    "CHL-501-RESIDUAL": TagRegistryEntry(
        tag="CHL-501-RESIDUAL", equipment_id="TertiaryTreatment-01", unit="mg/L",
        data_type="float", baseline_min=0.0, baseline_max=0.0,
        trip_threshold=None, severity_weight=0.35,
        topology_upstream=["CHL-501-BACKUP-STATUS"], short_label="Residual-disinfectant reading",
    ),
    "LAB-501-COLIFORM": TagRegistryEntry(
        tag="LAB-501-COLIFORM", equipment_id="TertiaryTreatment-01", unit="MPN/100 mL",
        data_type="float", baseline_min=0.0, baseline_max=10.0,
        trip_threshold=None, severity_weight=0.55,
        topology_upstream=["UV-501-DOSE"], short_label="Simulated lab coliform result",
    ),
    "AER-201-FOAM-DEPTH": TagRegistryEntry(tag="AER-201-FOAM-DEPTH", equipment_id="AerationBasin-01", unit="cm", data_type="float", baseline_min=0.0, baseline_max=5.0, trip_threshold=15.0, severity_weight=0.9, topology_upstream=[], short_label="Aeration foam depth"),
    "AER-201-MLSS": TagRegistryEntry(tag="AER-201-MLSS", equipment_id="AerationBasin-01", unit="mg/L", data_type="float", baseline_min=2500.0, baseline_max=3500.0, trip_threshold=None, severity_weight=0.45, topology_upstream=[], short_label="Mixed liquor suspended solids"),
    "AER-201-SLUDGE-AGE": TagRegistryEntry(tag="AER-201-SLUDGE-AGE", equipment_id="AerationBasin-01", unit="days", data_type="float", baseline_min=8.0, baseline_max=15.0, trip_threshold=None, severity_weight=0.4, topology_upstream=["AER-201-MLSS"], short_label="Sludge age"),
    "AER-201-WAS-FLOW": TagRegistryEntry(tag="AER-201-WAS-FLOW", equipment_id="AerationBasin-01", unit="m³/h", data_type="float", baseline_min=25.0, baseline_max=35.0, trip_threshold=None, severity_weight=0.35, topology_upstream=["AER-201-MLSS"], short_label="Waste activated sludge flow"),
    "AER-201-EFF-TURB": TagRegistryEntry(tag="AER-201-EFF-TURB", equipment_id="AerationBasin-01", unit="NTU", data_type="float", baseline_min=1.0, baseline_max=4.0, trip_threshold=8.0, severity_weight=0.65, topology_upstream=["AER-201-FOAM-DEPTH"], short_label="Effluent turbidity"),
    "ALM-AER-201-FOAM": TagRegistryEntry(tag="ALM-AER-201-FOAM", equipment_id="AerationBasin-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=1.0, topology_upstream=["AER-201-FOAM-DEPTH"], short_label="Biological foam high alarm"),
    "GAS-601-PRESS": TagRegistryEntry(tag="GAS-601-PRESS", equipment_id="BiogasSystem-01", unit="mbar", data_type="float", baseline_min=15.0, baseline_max=25.0, trip_threshold=35.0, severity_weight=0.95, topology_upstream=[], short_label="Biogas holder pressure"),
    "GAS-601-FILL": TagRegistryEntry(tag="GAS-601-FILL", equipment_id="BiogasSystem-01", unit="%", data_type="float", baseline_min=30.0, baseline_max=70.0, trip_threshold=90.0, severity_weight=0.7, topology_upstream=["GAS-601-PRESS"], short_label="Biogas holder fill level"),
    "CHP-601-RUN": TagRegistryEntry(tag="CHP-601-RUN", equipment_id="BiogasSystem-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=1.0, trip_threshold=None, severity_weight=0.65, topology_upstream=[], short_label="CHP operating state"),
    "FLR-601-RUN": TagRegistryEntry(tag="FLR-601-RUN", equipment_id="BiogasSystem-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=1.0, trip_threshold=None, severity_weight=0.65, topology_upstream=["GAS-601-PRESS"], short_label="Flare status"),
    "GAS-601-H2S": TagRegistryEntry(tag="GAS-601-H2S", equipment_id="BiogasSystem-01", unit="ppm", data_type="float", baseline_min=0.0, baseline_max=5.0, trip_threshold=10.0, severity_weight=0.9, topology_upstream=[], short_label="Biogas area gas detector"),
    "GAS-601-FLOW": TagRegistryEntry(tag="GAS-601-FLOW", equipment_id="BiogasSystem-01", unit="Nm³/h", data_type="float", baseline_min=250.0, baseline_max=350.0, trip_threshold=None, severity_weight=0.45, topology_upstream=["CHP-601-RUN"], short_label="Biogas flow"),
    "ALM-GAS-601-HIGH": TagRegistryEntry(tag="ALM-GAS-601-HIGH", equipment_id="BiogasSystem-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=1.0, topology_upstream=["GAS-601-PRESS", "GAS-601-FILL"], short_label="Biogas holder high pressure alarm"),
    "SLD-701-BOWL-RPM": TagRegistryEntry(tag="SLD-701-BOWL-RPM", equipment_id="DewateringCentrifuge-01", unit="rpm", data_type="float", baseline_min=3150.0, baseline_max=3250.0, trip_threshold=None, severity_weight=0.4, topology_upstream=[], short_label="Centrifuge bowl speed"),
    "SLD-701-POLYMER": TagRegistryEntry(tag="SLD-701-POLYMER", equipment_id="DewateringCentrifuge-01", unit="L/h", data_type="float", baseline_min=35.0, baseline_max=45.0, trip_threshold=None, severity_weight=0.4, topology_upstream=[], short_label="Polymer dose"),
    "SLD-701-CAPTURE": TagRegistryEntry(tag="SLD-701-CAPTURE", equipment_id="DewateringCentrifuge-01", unit="%", data_type="float", baseline_min=90.0, baseline_max=97.0, trip_threshold=80.0, severity_weight=0.9, topology_upstream=["SLD-701-BOWL-RPM", "SLD-701-POLYMER"], short_label="Solids capture"),
    "SLD-701-CAKE-DRY": TagRegistryEntry(tag="SLD-701-CAKE-DRY", equipment_id="DewateringCentrifuge-01", unit="%", data_type="float", baseline_min=20.0, baseline_max=25.0, trip_threshold=None, severity_weight=0.55, topology_upstream=["SLD-701-CAPTURE"], short_label="Cake dryness"),
    "SLD-701-CENTRATE-NH4": TagRegistryEntry(tag="SLD-701-CENTRATE-NH4", equipment_id="DewateringCentrifuge-01", unit="mg/L", data_type="float", baseline_min=20.0, baseline_max=50.0, trip_threshold=100.0, severity_weight=0.7, topology_upstream=["SLD-701-CAPTURE"], short_label="Centrate ammonia"),
    "SLD-701-INLET-NH4": TagRegistryEntry(tag="SLD-701-INLET-NH4", equipment_id="DewateringCentrifuge-01", unit="mg/L", data_type="float", baseline_min=20.0, baseline_max=50.0, trip_threshold=None, severity_weight=0.35, topology_upstream=[], short_label="Plant inlet ammonia"),
    "ALM-SLD-701-CAPTURE": TagRegistryEntry(tag="ALM-SLD-701-CAPTURE", equipment_id="DewateringCentrifuge-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=1.0, topology_upstream=["SLD-701-CAPTURE", "SLD-701-CENTRATE-NH4"], short_label="Centrifuge low capture alarm"),
    "LAB-901-SAMPLE-DUE": TagRegistryEntry(tag="LAB-901-SAMPLE-DUE", equipment_id="ProcessMonitoring-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.8, topology_upstream=[], short_label="Process sample overdue flag"),
    "LAB-901-RESULT-PENDING": TagRegistryEntry(tag="LAB-901-RESULT-PENDING", equipment_id="ProcessMonitoring-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.6, topology_upstream=["LAB-901-SAMPLE-DUE"], short_label="Laboratory result pending"),
    "LAB-901-CAL-DUE": TagRegistryEntry(tag="LAB-901-CAL-DUE", equipment_id="ProcessMonitoring-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.7, topology_upstream=[], short_label="Online instrument calibration due"),
    "LAB-901-MEAS-QUALITY": TagRegistryEntry(tag="LAB-901-MEAS-QUALITY", equipment_id="ProcessMonitoring-01", unit="status", data_type="string", baseline_min=0.0, baseline_max=0.0, baseline_status="GOOD", trip_threshold=None, severity_weight=0.55, topology_upstream=["LAB-901-CAL-DUE"], short_label="Instrument measurement quality"),
    "ALM-LAB-901-DUE": TagRegistryEntry(tag="ALM-LAB-901-DUE", equipment_id="ProcessMonitoring-01", unit="status", data_type="bool", baseline_min=0.0, baseline_max=0.0, trip_threshold=1.0, severity_weight=0.9, topology_upstream=["LAB-901-SAMPLE-DUE", "LAB-901-RESULT-PENDING", "LAB-901-CAL-DUE"], short_label="Sampling and calibration monitoring due alarm"),
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

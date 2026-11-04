"""
OpsLens - Incident catalog: the six Scenario Lab incidents.

Single source of truth for the six simulated wastewater incidents shown in
the Scenario Lab. Every "normal", "limit", "incident" and "after fix" value is
copied from the supplied incident map ("Wastewater plant: six incidents on one
map"), whose numbers match SOP-MAN-000. The tag registry, the generator, the
SOP mapping and the Scenario Lab all read from here, so a tag can only belong
to one equipment unit and one plant area.

Everything generated from this catalog is SIMULATED telemetry
(data_source="simulated"); it is never presented as live PLC data.

Plant overview is a monitoring view of these areas, not an incident.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SOURCE_DOCUMENT = "Wastewater plant: six incidents on one map (supplied incident map); limits per SOP-MAN-000"
SCENARIO_DURATION_S = 120.0
RECOVERY_DURATION_S = 40.0


@dataclass(frozen=True)
class Limit:
    value: float
    direction: str                 # "high" | "low"
    label: str                     # exact wording from the incident map / SOP
    alarm_tag: Optional[str] = None  # simulated PLC alarm input raised at this limit
    alarm_label: Optional[str] = None


@dataclass(frozen=True)
class Signal:
    tag: str
    equipment_id: str
    label: str
    unit: str
    normal: Tuple[Optional[float], Optional[float]]
    normal_text: str
    incident: float
    incident_text: str
    after: float
    after_text: str
    status: str                    # map status column: c=beyond limit, w=outside normal, n=unchanged
    ramp: Tuple[float, float]      # seconds into the scenario
    limits: Tuple[Limit, ...] = ()
    noise_band: Optional[Tuple[float, float]] = None  # registry band when "normal" is a single value
    upstream: Tuple[str, ...] = ()
    severity: float = 0.6
    peak_then_zero_on: Optional[str] = None  # value drops to 0 on the sample after this trip latches
    step_on: Optional[str] = None            # value steps to the incident value when this trip latches


@dataclass(frozen=True)
class StatusSignal:
    tag: str
    equipment_id: str
    label: str
    normal: bool
    incident: bool
    after: bool
    kind: str                      # "status" (evidence only) | "fault" (alarm input)
    change_at: Optional[float] = None       # fixed time, or
    change_when: Optional[str] = None       # trip id from Trip below
    text: str = ""
    upstream: Tuple[str, ...] = ()
    severity: float = 0.6


@dataclass(frozen=True)
class Trip:
    trip_id: str
    tag: str          # measurement whose limit causes the trip
    threshold: float
    direction: str


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    number: int
    name: str
    who: str
    summary: str
    equipment_id: str
    primary_alarm: str
    root: Dict[str, str]
    knock_on: Dict[str, str]
    signals: Tuple[Signal, ...]
    statuses: Tuple[StatusSignal, ...]
    trips: Tuple[Trip, ...]
    sop_id: str
    sop_title: str
    sop_coverage: str              # "full" | "partial"
    sop_coverage_notes: Tuple[str, ...]
    severity: str
    priority_note: str
    expected_outcome: str


def L(value, direction, label, alarm_tag=None, alarm_label=None) -> Limit:
    return Limit(value, direction, label, alarm_tag, alarm_label)


# --------------------------------------------------------------------------
# 1 · Rags jam the bar screen  (InletWorks-01, SOP-INL-001)
# --------------------------------------------------------------------------
S1 = Scenario(
    scenario_id="screen_differential_pressure", number=1,
    name="Rags jam the bar screen",
    who="Meera, night operator, 2:10 AM",
    summary=("A storm flushes rags into the plant while Screen 1 is out for repair. Screen 2 jams and the "
             "channel level climbs toward the overflow weir."),
    equipment_id="InletWorks-01", primary_alarm="ALM-SCR-110-DL",
    root={"Inlet screens (BS-1/BS-2)": "Bar screen BS-2 rake jammed with rags; motor overload tripped"},
    knock_on={"Lift station": "Pumps push against a rising channel level (higher discharge head)",
              "Grit removal": "Rags can slip past the bypass rack and foul the grit equipment",
              "Flow measurement": "Backwater from the blocked screen distorts the flume reading"},
    signals=(
        Signal("FIT-110-IN", "InletWorks-01", "Inlet flow vs one-screen capacity", "m³/h", (900, 1200), "900–1,200 m³/h",
               2150, "2,150 m³/h", 1480, "1,480 m³/h (throttled)", "c", (10, 40),
               (L(1500, "high", "1,500 m³/h"),), severity=0.45),
        Signal("LDT-110-SCR", "InletWorks-01", "Differential level across BS-2", "cm", (5, 15), "5–15 cm",
               52, "52 cm", 9, "9 cm", "c", (20, 60),
               (L(30, "high", "30 cm (high alarm)", "ALM-SCR-110-DL", "Screen BS-2 differential level high"),),
               upstream=("FIT-110-IN",), severity=0.9),
        Signal("SCR-110-MOT-CUR", "InletWorks-01", "Rake motor current", "A", (6, 9), "6–9 A",
               15.2, "15.2 A (tripped)", 7.5, "7.5 A", "c", (24, 54),
               (L(14, "high", "14 A (overload trip)"),), upstream=("LDT-110-SCR",), severity=0.7,
               peak_then_zero_on="rake_overload"),
        Signal("LIT-110-CH", "InletWorks-01", "Upstream channel level", "m", (0.8, 1.2), "0.8–1.2 m",
               1.65, "1.65 m", 1.0, "1.0 m", "w", (40, 85),
               (L(1.8, "high", "1.8 m (overflow weir)", "ALM-INL-110-CH-HH", "Inlet channel at overflow weir"),),
               upstream=("LDT-110-SCR",), severity=0.8),
        Signal("SCR-110-SCREENINGS", "InletWorks-01", "Screenings removed", "m³/h", (0.1, 0.3), "0.1–0.3 m³/h",
               0.9, "0.9 m³/h, then 0 as rake stops", 0.3, "0.3 m³/h", "w", (18, 40),
               upstream=("SCR-110-RAKE-RUN",), severity=0.4, peak_then_zero_on="rake_overload"),
    ),
    statuses=(
        StatusSignal("SCR-110-RAKE-RUN", "InletWorks-01", "BS-2 rake running", True, False, True, "status",
                     change_when="rake_overload", text="Rake stopped by motor overload", severity=0.5),
        StatusSignal("SCR-110-RAKE-TRIP", "InletWorks-01", "BS-2 rake motor overload trip", False, True, False, "fault",
                     change_when="rake_overload", text="Motor overload tripped",
                     upstream=("SCR-110-MOT-CUR",), severity=0.95),
        StatusSignal("SCR-110-BYPASS-OPEN", "InletWorks-01", "Bypass rack gate open", False, True, False, "status",
                     change_at=90.0, text="Closed → Open (manual)", upstream=("LIT-110-CH",), severity=0.5),
    ),
    trips=(Trip("rake_overload", "SCR-110-MOT-CUR", 15.2, "high"),),
    sop_id="SOP-INL-001", sop_title="Bar Screen Operation and Blockage Response",
    sop_coverage="full",
    sop_coverage_notes=(
        "Covered: differential level 30 cm, channel level 1.5 m action / 1.8 m weir, rake current 14 A trip, "
        "1,500 m³/h single-screen capacity, bypass rack use, lockout before clearing (pages 11–12).",
        "Gap: the SOP gives no normal range for the screenings removal rate (0.1–0.3 m³/h is incident-map data); "
        "it only says to record screenings volume each shift (p.11).",
    ),
    severity="High", priority_note="P1 if the channel reaches the 1.8 m weir (SOP-INL-001 §8, p.12); the incident peaks at 1.65 m.",
    expected_outcome="Isolate and clear BS-2, open bypass at 1.5 m, return channel below 1.2 m and differential below 15 cm.",
)

# --------------------------------------------------------------------------
# 2 · The lift station pumps clog  (LiftStation-01, SOP-LFT-001)
# --------------------------------------------------------------------------
S2 = Scenario(
    scenario_id="wet_well_high_level", number=2,
    name="The lift station pumps clog",
    who="Arjun, maintenance technician, 11:45 PM",
    summary=("Rain raises the inflow while a wad of cloth chokes both pumps. The wet well rises toward the level "
             "where sewage backs up into homes."),
    equipment_id="LiftStation-01", primary_alarm="ALM-WW-101-HH",
    root={"Lift station (P-101/P-102)": "P-101 tripped on thermal overload; P-102 impeller wrapped in cloth"},
    knock_on={"Sewers": "Sewage backs up toward basements and manholes",
              "Inlet screens": "Surge of flow arrives when the pumps are restored"},
    signals=(
        Signal("FIT-101-IN", "LiftStation-01", "Inflow to wet well", "m³/h", (380, 450), "380–450 m³/h",
               610, "610 m³/h (rain)", 480, "480 m³/h", "w", (5, 35), severity=0.5),
        Signal("FIT-102-FLW", "LiftStation-01", "P-102 flow", "m³/h", (380, 450), "380–450 m³/h",
               90, "90 m³/h", 420, "420 m³/h", "c", (15, 45),
               (L(300, "low", "300 m³/h (low alarm)", "ALM-P102-FLW-LO", "P-102 flow low"),), severity=0.8),
        Signal("PIT-102-DIS", "LiftStation-01", "P-102 discharge pressure", "bar", (2.8, 3.4), "2.8–3.4 bar",
               1.1, "1.1 bar", 3.1, "3.1 bar", "c", (15, 45),
               (L(2.0, "low", "2.0 bar (low alarm)", "ALM-P102-DIS-LO", "P-102 discharge pressure low"),),
               upstream=("FIT-102-FLW",), severity=0.7),
        Signal("MOT-102-CUR", "LiftStation-01", "P-102 motor current", "A", (28, 34), "28–34 A",
               19, "19 A (spinning, not pumping)", 32, "32 A", "c", (15, 45),
               (L(24, "low", "24 A (low-load alarm)", "ALM-P102-CUR-LO", "P-102 motor low load"),),
               upstream=("FIT-102-FLW",), severity=0.7),
        Signal("TIT-101-WDG", "LiftStation-01", "P-101 winding temperature", "°C", (55, 75), "55–75 °C",
               118, "118 °C (tripped)", 68, "68 °C", "c", (20, 60),
               (L(105, "high", "105 °C (thermal trip)"),), severity=0.85),
        Signal("MOT-101-CUR", "LiftStation-01", "P-101 motor current", "A", (28, 34), "28–34 A",
               0, "0 A (tripped)", 31, "31 A", "c", (0, 0),
               (L(42, "high", "42 A (overload)"),), upstream=("P101-RUN",), severity=0.6,
               peak_then_zero_on="p101_thermal"),
        Signal("LIT-101-WWL", "LiftStation-01", "Wet well level", "m", (1.0, 2.4), "1.0–2.4 m",
               3.85, "3.85 m (spills at 4.0 m)", 1.6, "1.6 m", "c", (30, 105),
               (L(3.2, "high", "3.2 m high", "ALM-WW-101-H", "Wet well level high"),
                L(3.6, "high", "3.6 m high-high", "ALM-WW-101-HH", "Wet well level high-high")),
               upstream=("FIT-101-IN", "FIT-102-FLW", "P101-RUN"), severity=0.95),
    ),
    statuses=(
        StatusSignal("P101-FAULT", "LiftStation-01", "P-101 thermal overload trip", False, True, False, "fault",
                     change_when="p101_thermal", text="P-101 tripped on thermal overload",
                     upstream=("TIT-101-WDG",), severity=0.95),
        StatusSignal("P101-RUN", "LiftStation-01", "P-101 running", True, False, True, "status",
                     change_when="p101_thermal", text="P-101 stopped by its trip", upstream=("P101-FAULT",), severity=0.5),
        StatusSignal("P102-RUN", "LiftStation-01", "P-102 running", True, True, True, "status",
                     text="P-102 keeps running (impeller wrapped, not pumping)", severity=0.4),
    ),
    trips=(Trip("p101_thermal", "TIT-101-WDG", 105.0, "high"),),
    sop_id="SOP-LFT-001", sop_title="Lift Station High-High Level and Pump Clog Response",
    sop_coverage="full",
    sop_coverage_notes=(
        "Covered: wet well 3.2/3.6/4.0 m and P1 at 3.85 m, motor current 42 A / 24 A, winding 105 °C trip, "
        "discharge pressure 2.0 bar, pump flow 300 m³/h, tanker, isolation and restart checks (pages 14–15).",
        "Gap: the SOP sets no limit for wet-well inflow (610 m³/h); step 5 only says to reduce inflow where the "
        "network allows (p.14).",
    ),
    severity="Critical", priority_note="P1: wet well reaches 3.85 m (SOP-LFT-001 §7, p.15).",
    expected_outcome="Tanker at 3.6 m, clear P-102, cool and reset P-101 after cause identified, level back below 2.4 m.",
)

# --------------------------------------------------------------------------
# 3 · Nocardia foam on the aeration tank  (AerationBasin-01, SOP-BIO-001)
# --------------------------------------------------------------------------
S3 = Scenario(
    scenario_id="biological_foam", number=3,
    name="Nocardia foam on the aeration tank",
    who="Priya, process engineer, 6:30 AM",
    summary=("Two weeks of too little sludge wasting let sludge age climb. Greasy brown foam builds on Tank 3 "
             "and spills into the clarifier."),
    equipment_id="AerationBasin-01", primary_alarm="ALM-AER-201-FOAM",
    root={"Aeration tanks": "Tank 3 foaming; sludge age far above target"},
    knock_on={"Secondary clarifiers": "Foam carries flocs over the weirs",
              "Effluent": "Turbidity close to the permit limit"},
    signals=(
        Signal("AER-201-WAS-FLOW", "AerationBasin-01", "WAS (wasting) rate", "m³/d", (180, 250), "180–250 m³/d",
               70, "70 m³/d", 260, "260 m³/d", "c", (5, 35),
               (L(120, "low", "< 120 m³/d", "ALM-AER-201-WAS-LO", "WAS rate low"),), severity=0.75),
        Signal("AER-201-SLUDGE-AGE", "AerationBasin-01", "Sludge age (SRT)", "days", (5, 10), "5–10 days",
               21, "21 days", 11, "11 days (recovers over ~3 weeks)", "c", (15, 60),
               (L(15, "high", "15 days", "ALM-AER-201-SRT-HI", "Sludge age high"),),
               upstream=("AER-201-WAS-FLOW",), severity=0.8),
        Signal("AER-201-MLSS", "AerationBasin-01", "MLSS", "mg/L", (2500, 3500), "2,500–3,500 mg/L",
               5100, "5,100 mg/L", 3300, "3,300 mg/L", "c", (20, 65),
               (L(4500, "high", "4,500 mg/L", "ALM-AER-201-MLSS-HI", "MLSS high"),),
               upstream=("AER-201-WAS-FLOW", "RAS-FLOW"), severity=0.6),
        Signal("AER-201-FM", "AerationBasin-01", "F/M ratio", "ratio", (0.2, 0.4), "0.2–0.4",
               0.09, "0.09", 0.28, "0.28", "c", (20, 65),
               (L(0.15, "low", "< 0.15", "ALM-AER-201-FM-LO", "F/M ratio low"),),
               upstream=("AER-201-MLSS",), severity=0.6),
        Signal("AIT-201-DO", "AerationBasin-01", "Dissolved oxygen", "mg/L", (1.5, 3.0), "1.5–3.0 mg/L",
               2.4, "2.4 mg/L", 2.2, "2.2 mg/L", "n", (20, 60),
               (L(1.0, "low", "< 1.0 mg/L", "ALM-AER-201-DO", "Dissolved oxygen low"),), severity=0.5),
        Signal("AER-201-FOAM-DEPTH", "AerationBasin-01", "Foam depth on surface", "cm", (0, 2), "< 2 cm",
               45, "45 cm", 4, "< 5 cm (3–5 days)", "c", (40, 95),
               (L(10, "high", "10 cm", "ALM-AER-201-FOAM", "Biological foam high"),),
               upstream=("AER-201-SLUDGE-AGE",), severity=0.95),
        Signal("EFF-301-TURB", "Effluent-01", "Effluent turbidity", "NTU", (2, 5), "2–5 NTU",
               8.8, "8.8 NTU, rising", 3.5, "3.5 NTU", "w", (60, 110),
               (L(10, "high", "10 NTU (permit)", "ALM-EFF-301-TURB-HI", "Effluent turbidity at permit"),),
               upstream=("AER-201-FOAM-DEPTH",), severity=0.6),
        Signal("EFF-301-TSS", "Effluent-01", "Effluent TSS", "mg/L", (8, 15), "8–15 mg/L",
               26, "26 mg/L", 11, "11 mg/L", "w", (60, 110),
               (L(30, "high", "30 mg/L (permit)", "ALM-EFF-301-TSS-HI", "Effluent TSS at permit"),),
               upstream=("AER-201-FOAM-DEPTH", "SLB-201-DEPTH"), severity=0.6),
    ),
    statuses=(),
    trips=(),
    sop_id="SOP-BIO-001", sop_title="Activated Sludge Foam Control",
    sop_coverage="full",
    sop_coverage_notes=(
        "Covered: SRT 15 days, WAS below 120 m³/d, MLSS 4,500 mg/L, F/M below 0.15, DO below 1.0 mg/L, foam 10 cm, "
        "turbidity 10 NTU, microscopy before changing control, 25 % per day SRT change limit (pages 17–18).",
        "Gap: effluent TSS normal range and the 30 mg/L permit are in SOP-BIO-002 (p.19), not SOP-BIO-001; "
        "SOP-BIO-001 only gives the 25 mg/L escalation (p.18).",
    ),
    severity="Medium", priority_note="Escalate to the Plant Manager at effluent TSS 25 mg/L or turbidity 10 NTU (p.18).",
    expected_outcome="Raise WAS stepwise (≤25 %/day SRT change), foam below 5 cm for 3 days, SRT back to ~11 days.",
)

# --------------------------------------------------------------------------
# 4 · RAS pump fails, sludge blanket rises  (RASSystem-01, SOP-BIO-002)
# --------------------------------------------------------------------------
S4 = Scenario(
    scenario_id="ras_pump_failure", number=4,
    name="RAS pump fails, sludge blanket rises",
    who="Rohan, night operator, 3:20 AM",
    summary=("RAS-P1 trips on a hot motor. RAS-P2 alone cannot return enough sludge, so the clarifier fills while "
             "the aeration tank is starved of bacteria."),
    equipment_id="RASSystem-01", primary_alarm="ALM-SLB-201-HIGH",
    root={"RAS pumps": "RAS-P1 motor overheated and tripped; RAS-P2 at full speed"},
    knock_on={"Secondary clarifiers": "Sludge blanket climbs toward the overflow weirs",
              "Aeration tanks": "MLSS falls because returned sludge is short",
              "Effluent": "Solids start to carry over into the discharge"},
    signals=(
        Signal("TIT-RAS-P1-WDG", "RASSystem-01", "RAS-P1 winding temperature", "°C", (60, 80), "60–80 °C",
               142, "142 °C", 72, "72 °C", "c", (5, 35),
               (L(130, "high", "130 °C (trip)"),), severity=0.85),
        Signal("RAS-P1-FLOW", "RASSystem-01", "RAS-P1 flow", "m³/h", (350, 420), "350–420 m³/h",
               0, "0 m³/h (tripped)", 390, "390 m³/h", "c", (0, 0),
               upstream=("RAS-P1-RUN",), severity=0.7, peak_then_zero_on="ras_p1_thermal"),
        Signal("RAS-FLOW", "RASSystem-01", "Total RAS flow", "m³/h", (700, 840), "700–840 m³/h",
               410, "410 m³/h", 760, "760 m³/h", "c", (28, 36),
               (L(550, "low", "550 m³/h (low alarm)", "ALM-RAS-201-FLOW-LO", "Total RAS flow low"),),
               upstream=("RAS-P1-FLOW",), severity=0.85),
        Signal("SLB-201-DEPTH", "SecondaryClarifier-01", "Sludge blanket depth", "m", (0.3, 0.8), "0.3–0.8 m",
               2.1, "2.1 m (weirs at ~2.5 m)", 0.6, "0.6 m", "c", (35, 110),
               (L(1.5, "high", "1.5 m (high alarm)", "ALM-SLB-201-HIGH", "Sludge blanket high"),),
               upstream=("RAS-FLOW",), severity=0.95),
        Signal("CLR-201-SLR", "SecondaryClarifier-01", "Clarifier solids loading", "kg/m²/h", (3, 5), "3–5 kg/m²/h",
               7.4, "7.4 kg/m²/h", 4.2, "4.2 kg/m²/h", "c", (35, 80),
               (L(6.5, "high", "6.5 kg/m²/h", "ALM-CLR-201-SLR-HI", "Clarifier solids loading high"),),
               upstream=("SLB-201-DEPTH",), severity=0.7),
        Signal("AER-201-MLSS", "AerationBasin-01", "Aeration MLSS", "mg/L", (2500, 3500), "2,500–3,500 mg/L",
               1900, "1,900 mg/L, falling", 3000, "3,000 mg/L", "c", (40, 110),
               (L(2000, "low", "2,000 mg/L (low)", "ALM-AER-201-MLSS-LO", "Aeration MLSS low"),),
               upstream=("AER-201-WAS-FLOW", "RAS-FLOW"), severity=0.6),
        Signal("EFF-301-TSS", "Effluent-01", "Effluent TSS", "mg/L", (8, 15), "8–15 mg/L",
               24, "24 mg/L, rising", 12, "12 mg/L", "w", (60, 115),
               (L(30, "high", "30 mg/L (permit)", "ALM-EFF-301-TSS-HI", "Effluent TSS at permit"),),
               upstream=("AER-201-FOAM-DEPTH", "SLB-201-DEPTH"), severity=0.6),
    ),
    statuses=(
        StatusSignal("ALM-RAS-P1-FAIL", "RASSystem-01", "RAS-P1 thermal trip", False, True, False, "fault",
                     change_when="ras_p1_thermal", text="RAS-P1 motor overheated and tripped",
                     upstream=("TIT-RAS-P1-WDG",), severity=0.95),
        StatusSignal("RAS-P1-RUN", "RASSystem-01", "RAS-P1 running", True, False, True, "status",
                     change_when="ras_p1_thermal", text="RAS-P1 stopped by its trip",
                     upstream=("ALM-RAS-P1-FAIL",), severity=0.5),
    ),
    trips=(Trip("ras_p1_thermal", "TIT-RAS-P1-WDG", 130.0, "high"),),
    sop_id="SOP-BIO-002", sop_title="RAS Pump Failure and Sludge Blanket Control",
    sop_coverage="full",
    sop_coverage_notes=(
        "Covered: total RAS 550 m³/h, per-pump flow 350–420 m³/h, winding 130 °C trip, blanket 1.5 m alarm / 2.0 m WAS "
        "action / 2.5 m weir, solids loading 6.5 kg/m²/h, aeration MLSS 2,000 mg/L, effluent TSS 30 mg/L (pages 19–20).",
        "Gap: none for the incident readings. Availability of the portable standby pump (step 4) is a site fact OpsLens "
        "cannot observe.",
    ),
    severity="High", priority_note="P1 if blanket reaches 2.5 m or effluent TSS 30 mg/L (p.20); incident peaks at 2.1 m / 24 mg/L.",
    expected_outcome="Max RAS-P2, portable pump, reduce inflow, repair RAS-P1, blanket below 0.8 m in 4–8 h.",
)

# --------------------------------------------------------------------------
# 5 · CHP engine trips, gas holder fills  (BiogasSystem-01, SOP-GAS-001)
# --------------------------------------------------------------------------
S5 = Scenario(
    scenario_id="biogas_holder_pressure", number=5,
    name="CHP engine trips, gas holder fills",
    who="Kavita, shift supervisor, 1:00 AM",
    summary=("A sensor fault stops the CHP engine. The digester keeps making biogas and the holder roof rises toward "
             "its limit until the flare takes over."),
    equipment_id="BiogasSystem-01", primary_alarm="ALM-GAS-601-HIGH",
    root={"CHP engine / boiler": "Engine tripped on a faulty spark plug sensor"},
    knock_on={"Gas holder": "Filling to the roof limit; relief valve is the last defence",
              "Flare": "Opens automatically and burns the surplus gas",
              "Anaerobic digester": "Keeps producing gas, so back-pressure builds"},
    signals=(
        Signal("CHP-601-GAS", "BiogasSystem-01", "CHP gas consumption", "m³/h", (150, 190), "150–190 m³/h",
               0, "0 m³/h", 170, "170 m³/h", "c", (20, 24),
               (L(100, "low", "100 m³/h (low-use alarm)", "ALM-CHP-601-GAS-LO", "CHP gas consumption low"),),
               upstream=("CHP-601-RUN",), severity=0.7),
        Signal("CHP-601-KWE", "BiogasSystem-01", "CHP electrical output", "kWe", (380, 420), "380–420 kWe",
               0, "0 kWe (tripped)", 400, "400 kWe", "c", (20, 24), upstream=("CHP-601-RUN",), severity=0.6),
        Signal("GAS-601-PROD", "BiogasSystem-01", "Biogas production", "m³/h", (160, 200), "160–200 m³/h",
               185, "185 m³/h (unchanged)", 180, "180 m³/h", "n", (20, 40), severity=0.3),
        Signal("GAS-601-PRESS", "BiogasSystem-01", "Holder pressure", "mbar", (15, 25), "15–25 mbar",
               36, "36 mbar", 22, "22 mbar", "c", (22, 75),
               (L(32, "high", "32 mbar alarm", "ALM-GAS-601-HIGH", "Gas holder pressure high"),
                L(38, "high", "38 mbar relief opens")),
               upstream=("CHP-601-GAS",), severity=0.95),
        Signal("GAS-601-FILL", "BiogasSystem-01", "Holder fill level", "%", (40, 70), "40–70 %",
               96, "96 %", 60, "60 %", "c", (22, 85),
               (L(90, "high", "90 %", "ALM-GAS-601-FILL-HI", "Gas holder fill high"),),
               upstream=("GAS-601-PRESS",), severity=0.8),
        Signal("FLR-601-FLOW", "BiogasSystem-01", "Flare gas flow", "m³/h", (0, 0), "0 m³/h (standby)",
               185, "185 m³/h (burning)", 0, "0 m³/h", "w", (0, 0), noise_band=(0.0, 2.0),
               upstream=("FLR-601-RUN",), severity=0.5, step_on="holder_pressure_high"),
        Signal("GAS-601-LEL", "BiogasSystem-01", "Methane near holder vent", "% LEL", (0, 0), "0 % LEL",
               4, "4 % LEL", 0, "0 % LEL", "w", (50, 90),
               (L(10, "high", "10 % LEL (alarm)", "ALM-GAS-601-LEL-HI", "Methane near holder vent"),),
               noise_band=(0.0, 0.5), upstream=("GAS-601-PRESS",), severity=0.8),
    ),
    statuses=(
        StatusSignal("CHP-601-TRIP", "BiogasSystem-01", "CHP engine trip", False, True, False, "fault",
                     change_at=20.0, text="Engine tripped on a faulty spark plug sensor", severity=0.9),
        StatusSignal("CHP-601-RUN", "BiogasSystem-01", "CHP engine running", True, False, True, "status",
                     change_at=20.0, text="CHP stopped", upstream=("CHP-601-TRIP",), severity=0.6),
        StatusSignal("FLR-601-RUN", "BiogasSystem-01", "Flare burning", False, True, False, "status",
                     change_when="holder_pressure_high", text="Flare opens automatically at high holder pressure",
                     upstream=("GAS-601-PRESS",), severity=0.6),
    ),
    trips=(Trip("holder_pressure_high", "GAS-601-PRESS", 32.0, "high"),),
    sop_id="SOP-GAS-001", sop_title="Biogas Holder High Pressure, CHP Trip and Flare Operation",
    sop_coverage="full",
    sop_coverage_notes=(
        "Covered: holder 32 mbar alarm / 38 mbar relief, fill 90 %, production, CHP consumption 100 m³/h, output "
        "380–420 kWe, flare verification (~185 m³/h), 10 % LEL evacuation, no hot work (pages 21–23).",
        "Gap: no CHP engine fault-diagnosis procedure for the spark plug sensor; steps 8–9 defer to the CHP "
        "technician and the manufacturer's start sequence (p.23).",
    ),
    severity="High", priority_note="P1 at 10 % LEL, or at 38 mbar if the flare is not burning (pp.22–23); incident: 36 mbar, 4 % LEL.",
    expected_outcome="Flare verified burning, exclusion zone, technician repairs sensor, CHP restarted, holder back to 15–25 mbar.",
)

# --------------------------------------------------------------------------
# 6 · Centrate poisons the plant inlet  (DewateringCentrifuge-01, SOP-SLD-001)
# --------------------------------------------------------------------------
S6 = Scenario(
    scenario_id="centrifuge_capture", number=6,
    name="Centrate poisons the plant inlet",
    who="Nikhil, lab technician, 9:15 AM",
    summary=("After a repair the centrifuge runs at the wrong settings. Wet cake and ammonia-rich centrate flow back "
             "to the inlet and overload the aeration tanks."),
    equipment_id="DewateringCentrifuge-01", primary_alarm="ALM-SLD-701-CAPTURE",
    root={"Dewatering": "Centrifuge bowl speed and polymer dose set wrongly after repair"},
    knock_on={"Inlet screens": "Centrate re-enters the plant at the inlet works",
              "Aeration tanks": "Ammonia shock load; blowers near maximum",
              "Effluent": "Effluent ammonia creeping toward the permit"},
    signals=(
        Signal("SLD-701-BOWL-RPM", "DewateringCentrifuge-01", "Centrifuge bowl speed", "rpm", (3200, 3200), "3,200 rpm",
               2400, "2,400 rpm", 3200, "3,200 rpm", "c", (10, 20),
               (L(2900, "low", "2,900 rpm (low alarm)", "ALM-SLD-701-BOWL-LO", "Centrifuge bowl speed low"),),
               noise_band=(3180.0, 3220.0), severity=0.8),
        Signal("SLD-701-POLYMER", "DewateringCentrifuge-01", "Polymer dose", "kg/t DS", (8, 12), "8–12 kg/t DS",
               4, "4 kg/t DS", 10, "10 kg/t DS", "c", (10, 20),
               (L(6, "low", "6 kg/t DS (low)", "ALM-SLD-701-POLY-LO", "Polymer dose low"),), severity=0.75),
        Signal("SLD-701-CAPTURE", "DewateringCentrifuge-01", "Solids capture", "%", (92, 97), "92–97 %",
               74, "74 %", 94, "94 %", "c", (20, 50),
               (L(88, "low", "88 %", "ALM-SLD-701-CAPTURE", "Centrifuge solids capture low"),),
               upstream=("SLD-701-BOWL-RPM", "SLD-701-POLYMER"), severity=0.95),
        Signal("SLD-701-CAKE-DRY", "DewateringCentrifuge-01", "Cake dryness", "% DS", (22, 26), "22–26 % DS",
               16, "16 % DS", 24, "24 % DS", "c", (20, 50),
               (L(20, "low", "20 % DS", "ALM-SLD-701-CAKE-LO", "Cake dryness low"),),
               upstream=("SLD-701-CAPTURE",), severity=0.6),
        Signal("SLD-701-CENTRATE-NH4", "DewateringCentrifuge-01", "Centrate ammonia (NH₄-N)", "mg/L", (800, 1100),
               "800–1,100 mg/L", 1650, "1,650 mg/L", 950, "950 mg/L (bled slowly)", "c", (30, 65),
               (L(1400, "high", "1,400 mg/L", "ALM-SLD-701-NH4-HI", "Centrate ammonia high"),),
               upstream=("SLD-701-CAPTURE",), severity=0.8),
        Signal("INL-110-NH4", "InletWorks-01", "Plant inlet ammonia", "mg/L", (35, 42), "35–42 mg/L",
               56, "56 mg/L (+40 %)", 41, "41 mg/L", "c", (50, 85),
               (L(50, "high", "50 mg/L", "ALM-INL-110-NH4-HI", "Plant inlet ammonia high"),),
               upstream=("SLD-701-CENTRATE-NH4",), severity=0.8),
        Signal("AER-201-AIRFLOW", "AerationBasin-01", "Blower airflow", "Nm³/h", (2800, 3400), "2,800–3,400 Nm³/h",
               4050, "4,050 Nm³/h", 3300, "3,300 Nm³/h", "w", (60, 100),
               (L(4200, "high", "4,200 Nm³/h (max)", "ALM-AER-201-AIR-HI", "Blower airflow at maximum"),),
               upstream=("INL-110-NH4",), severity=0.6),
        Signal("EFF-301-NH4", "Effluent-01", "Effluent ammonia", "mg/L", (0.5, 2), "0.5–2 mg/L",
               3.8, "3.8 mg/L, rising", 1.2, "1.2 mg/L", "w", (70, 118),
               (L(5, "high", "5 mg/L (permit)", "ALM-EFF-301-NH4-HI", "Effluent ammonia at permit"),),
               upstream=("INL-110-NH4", "AER-201-AIRFLOW"), severity=0.7),
    ),
    statuses=(),
    trips=(),
    sop_id="SOP-SLD-001", sop_title="Dewatering Centrifuge Operation and Centrate Recycle Control",
    sop_coverage="partial",
    sop_coverage_notes=(
        "Covered: bowl speed 2,900 rpm, polymer 6 kg/t DS, capture 88 %, cake 20 % DS, centrate ammonia 1,400 mg/L, "
        "inlet ammonia 50 mg/L, blower 4,200 Nm³/h, restore approved setpoints after repair, slow the centrate return "
        "over 24 h, 4-hourly effluent ammonia sampling (pages 24–26).",
        "Gap: SOP-SLD-001 treats the centrate as an ammonia LOAD only. It does not cover inhibitory or toxic centrate: "
        "no nitrification-inhibition or toxicity test, and no aeration-tank response beyond pausing centrate return near "
        "4,200 Nm³/h (p.26). The words 'toxic', 'inhibit' and 'nitrification' do not appear in the procedure.",
        "Gap: effluent ammonia 5 mg/L says only 'Escalate' (p.25); the route is SOP-GEN-004 (pp.9–10).",
    ),
    severity="High", priority_note="Effluent ammonia 5 mg/L is a permit limit (p.25); incident reaches 3.8 mg/L, rising.",
    expected_outcome="Restore approved bowl speed and polymer dose, hold centrate and bleed back over 24 h, inlet ammonia below 42 mg/L.",
)

SCENARIOS: Tuple[Scenario, ...] = (S1, S2, S3, S4, S5, S6)
SCENARIO_BY_ID: Dict[str, Scenario] = {s.scenario_id: s for s in SCENARIOS}

PLANT_EQUIPMENT: Dict[str, str] = {
    "InletWorks-01": "Inlet works (screens BS-1/BS-2)",
    "LiftStation-01": "Lift station (wet well, P-101/P-102)",
    "AerationBasin-01": "Aeration tanks (blowers, diffusers)",
    "SecondaryClarifier-01": "Secondary clarifiers (blanket probe)",
    "RASSystem-01": "RAS pumps (RAS-P1/RAS-P2)",
    "BiogasSystem-01": "Gas holder, CHP engine, flare",
    "DewateringCentrifuge-01": "Dewatering centrifuge",
    "Effluent-01": "Final effluent",
}


def _merge_limits(existing: Tuple[Limit, ...], new: Tuple[Limit, ...]) -> Tuple[Limit, ...]:
    seen = {(l.value, l.direction) for l in existing}
    return existing + tuple(l for l in new if (l.value, l.direction) not in seen)


def plant_signals() -> Dict[str, Signal]:
    """Every measurement once. A tag shared by two incidents (e.g. AER-201-MLSS,
    EFF-301-TSS) keeps one equipment owner and the union of its limits."""
    result: Dict[str, Signal] = {}
    for scenario in SCENARIOS:
        for sig in scenario.signals:
            if sig.tag in result:
                prev = result[sig.tag]
                if prev.equipment_id != sig.equipment_id or prev.unit != sig.unit:
                    raise ValueError(f"{sig.tag} is defined with two owners/units")
                result[sig.tag] = Signal(**{**prev.__dict__,
                                            "limits": _merge_limits(prev.limits, sig.limits),
                                            "upstream": tuple(dict.fromkeys(prev.upstream + sig.upstream))})
            else:
                result[sig.tag] = sig
    return result


def plant_statuses() -> Dict[str, StatusSignal]:
    return {st.tag: st for scenario in SCENARIOS for st in scenario.statuses}


def alarm_inputs() -> Dict[str, Dict[str, Any]]:
    """Simulated PLC alarm inputs derived from limits, plus fault/trip bits."""
    alarms: Dict[str, Dict[str, Any]] = {}
    for tag, sig in plant_signals().items():
        for lim in sig.limits:
            if lim.alarm_tag:
                alarms[lim.alarm_tag] = {"tag": lim.alarm_tag, "equipment_id": sig.equipment_id,
                                         "label": lim.alarm_label or lim.label, "source_tag": tag,
                                         "threshold": lim.value, "direction": lim.direction}
    for tag, st in plant_statuses().items():
        if st.kind == "fault":
            alarms[tag] = {"tag": tag, "equipment_id": st.equipment_id, "label": st.label,
                           "source_tag": (st.upstream or (None,))[0], "threshold": None, "direction": None}
    return alarms


def scenario_tags(scenario: Scenario) -> List[str]:
    """Measurements, status bits and alarm inputs that belong to one incident."""
    tags = [s.tag for s in scenario.signals] + [s.tag for s in scenario.statuses]
    for sig in scenario.signals:
        tags += [l.alarm_tag for l in sig.limits if l.alarm_tag]
    return list(dict.fromkeys(tags))


def scenario_for_tag(tag: str) -> List[str]:
    return [s.scenario_id for s in SCENARIOS if tag in scenario_tags(s)]


def sop_for_tag(tag: str) -> Optional[str]:
    """SOP of the incident that owns this tag. A tag shared by several
    incidents (EFF-301-TSS, AER-201-MLSS) has no single SOP by tag alone."""
    owners = {s.sop_id for s in SCENARIOS if tag in scenario_tags(s)}
    return owners.pop() if len(owners) == 1 else None


def scenario_table(scenario: Scenario) -> List[Dict[str, Any]]:
    """The incident map's 'Normal vs incident vs recovery' table, verbatim."""
    rows = []
    for sig in scenario.signals:
        rows.append({
            "tag": sig.tag, "equipment_id": sig.equipment_id, "parameter": sig.label, "unit": sig.unit,
            "normal": sig.normal_text,
            "limit": " · ".join(l.label for l in sig.limits) or "—",
            "incident": sig.incident_text, "after_fix": sig.after_text,
            "status": {"c": "Beyond limit", "w": "Outside normal", "n": "Unchanged"}[sig.status],
        })
    return rows


def scenario_summary(scenario: Scenario) -> Dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "number": scenario.number,
        "name": scenario.name,
        "who": scenario.who,
        "description": scenario.summary,
        "summary": scenario.summary,
        "equipment_id": scenario.equipment_id,
        "target_equipment": scenario.equipment_id,
        "alarm_id": scenario.primary_alarm,
        "root_cause": scenario.root,
        "knock_on": scenario.knock_on,
        "severity": scenario.severity,
        "priority_note": scenario.priority_note,
        "expected_outcome": scenario.expected_outcome,
        "duration_seconds": SCENARIO_DURATION_S,
        "recovery_supported": True,
        "sop_id": scenario.sop_id,
        "sop_title": scenario.sop_title,
        "sop_available": True,
        "sop_approval_status": "Draft for review — NOT APPROVED (SOP-MAN-000 Rev 0)",
        "sop_coverage": scenario.sop_coverage,
        "sop_coverage_notes": list(scenario.sop_coverage_notes),
        "demo_group": "WITH MATCHING SOP" if scenario.sop_coverage == "full" else "SOP PARTIALLY COVERS INCIDENT",
        "tags": scenario_tags(scenario),
        "table": scenario_table(scenario),
        "source_status": "SIMULATED",
        "source_document": SOURCE_DOCUMENT,
    }


def scenario_for_incident(primary_tag: Optional[str], clustered_tags: Optional[List[str]] = None) -> Optional[Scenario]:
    """Which of the six incidents an incident record belongs to.

    Decided by the primary alarm when it is an incident's primary alarm, else
    by the tags that belong to exactly one incident. Shared tags (EFF-301-TSS,
    AER-201-MLSS) never decide on their own. Returns None for legacy/unknown.
    """
    for spec in SCENARIOS:
        if primary_tag == spec.primary_alarm:
            return spec
    tags = list(dict.fromkeys([t for t in [primary_tag, *(clustered_tags or [])] if t]))
    scores = {}
    for spec in SCENARIOS:
        own = set(scenario_tags(spec))
        scores[spec.scenario_id] = sum(1 for t in tags if t in own and len(scenario_for_tag(t)) == 1)
    best = max(scores.items(), key=lambda kv: kv[1]) if scores else (None, 0)
    return SCENARIO_BY_ID.get(best[0]) if best[1] > 0 else None

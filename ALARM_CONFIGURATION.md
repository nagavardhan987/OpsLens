# Alarm Configuration — derived from the plant SOP manual

> **v2.1 tag set.** The simulated plant now uses only the six incidents of the plant incident map. Tags, equipment, units, limits and SOP mapping are defined in `edge_intelligence/incident_catalog.py`, and `config/alarm_reference.json` was updated to those tags (37 definitions, all `direct` mappings). Older tag names in this document (for example `DPT-110-SCR`, `AIT-201-NH4`, UV/filter tags) belong to v2.0 and were removed. See README → *What you see in the demo* for the incident → SOP → coverage table.


**Source:** `SOP Manual – Wastewater Treatment Plant.pdf` — document **SOP-MAN-000**, revision 0 (Draft for review), 29 pages, SHA-256 `a26b0b5eb29bdd1f…`.  
**Status:** DRAFT / REFERENCE ONLY — NOT APPROVED. The approval table on page 1 is blank. Section 3 (page 2) states that all set points, alarm levels and operating ranges are typical values for a mid-size plant that must be verified against manufacturer data, design basis, discharge permit and local regulations before use.

Machine-readable file: [`edge_intelligence/config/alarm_reference.json`](edge_intelligence/config/alarm_reference.json). It is loaded by `alarm_config.py` and served at `GET /api/alarms/reference`; the engineering console shows it under **Alarm Reference**.

## How the PDF is used by the running system

1. **Tag classification** — only alarm inputs (`ALM-*`, `*-FAULT`, `*-TRIP`) become alarm records. `P101-RUN` and other status tags are evidence, never alarms.
2. **SOP limit check** — every mapped measurement in an incident is compared with the manual's normal range and limits in Python; the operator brief shows the limit reached, the next limit and the margin, with the page number.
3. **Escalation** — limits the manual marks as P1 (e.g. wet well ≥ 3.85 m, p.15) raise a P1 banner and the P1 acknowledgement deadline (2 min, p.4).
4. **Verification criteria** — the brief lists the manual's own recovery checks (e.g. *"Watch the wet well level fall below 2.4 m. Release the tanker."*, p.15).
5. **Procedure steps** — `sop_steps.py` copies the numbered steps of each SOP's Procedure section verbatim with page numbers.
6. **Conflict report** — `GET /api/alarms/conflicts` lists every difference between the manual and the OpsLens tag registry. Nothing is changed automatically.

## Extraction rules

- Every value below was copied from the cited page of SOP-MAN-000. Nothing was estimated.
- Fields the manual does not state are recorded as the string NOT SPECIFIED.
- The manual names parameters, not PLC/HMI alarm tags. The 'opslens_mapping' block records which OpsLens simulated tag was associated with each parameter and how confident that association is.
- The manual does not define alarm deadbands or reset/clear conditions. 'verification_criteria' records the procedure's own recovery checks, which are NOT alarm reset conditions.

## Alarm priority convention (page 4)

| Priority | Meaning | Acknowledge within | Operator on location within |
|---|---|---|---|
| P1 | Risk to life, environment or permit compliance now | 2 minutes | 15 minutes |
| P2 | Equipment or process degrading, likely to reach P1 | 5 minutes | 30 minutes |
| P3 | Advisory, no immediate effect | 30 minutes | Next round |

## Alarm response rules — SOP-GEN-003 (pages 8–9)

1. Acknowledge the alarm within the time in the Alarm Priority Convention (Section 6 of this manual).
2. Read the tag name, value, limit and time. Check related instruments to confirm the alarm is genuine and not a sensor fault.
3. Classify the alarm P1, P2 or P3.
4. For P1 and P2: inform the shift supervisor, then go to the location with a torch, gas monitor and radio.
5. Take the immediate safe action in the relevant process SOP.
6. If the value keeps moving toward the next limit, escalate to the supervisor and on-call maintenance.
7. Never disable, shelve or inhibit an alarm without the supervisor's written approval.
8. Record the alarm, action, outcome and time in the shift log.

## Extracted parameters

`NOT SPECIFIED` means the manual does not state it. The manual names **no PLC/HMI alarm tags, deadbands or reset conditions** for any parameter.

| ID | Parameter | Area / SOP | Unit | Normal | Limits (page) | Priority | OpsLens tag (mapping) |
|---|---|---|---|---|---|---|---|
| LFT-WW-LEVEL | Wet well level | Lift station and wet well · SOP-LFT-001 p.14 | m | 1.0 to 2.4 m | HIGH 3.2 (p.14)<br>HIGH-HIGH 3.6 (p.14)<br>P1 ESCALATION 3.85 (p.15)<br>SPILL 4 (p.14) | NOT SPECIFIED below 3.85 m; P1 at or above 3.85 m (page 15) | `LIT-101-WWL` / alarm `ALM-WW-101-HH` (direct) |
| LFT-PUMP-CURRENT | Pump motor current | Lift station and wet well · SOP-LFT-001 p.14 | A | 28 to 34 A | OVERLOAD 42 (p.14)<br>LOW-LOAD 24 (p.14) | NOT SPECIFIED | `MOT-101-CUR` (direct) |
| LFT-WINDING-TEMP | Pump winding temperature | Lift station and wet well · SOP-LFT-001 p.14 | °C | 55 to 75 °C | TRIP 105 (p.14) | NOT SPECIFIED | — (none) |
| LFT-PUMP-PRESSURE | Pump discharge pressure | Lift station and wet well · SOP-LFT-001 p.14 | bar | 2.8 to 3.4 bar | LOW 2 (p.14) | NOT SPECIFIED | `PIT-101-DIS` (assumed) |
| LFT-PUMP-FLOW | Pump flow | Lift station and wet well · SOP-LFT-001 p.14 | m³/h | 380 to 450 m³/h | LOW 300 (p.14) | NOT SPECIFIED | `FIT-101-P1-FLW` (direct) |
| INL-SCREEN-DL | Differential level across screen | Inlet works · SOP-INL-001 p.11 | cm | 5 to 15 cm | HIGH 30 (p.11) | NOT SPECIFIED | `DPT-110-SCR` (unit_mismatch) |
| INL-CHANNEL-LEVEL | Upstream channel level | Inlet works · SOP-INL-001 p.11 | m | 0.8 to 1.2 m | ACTION 1.5 (p.11)<br>OVERFLOW WEIR / P1 1.8 (p.12) | NOT SPECIFIED below 1.8 m; P1 at 1.8 m (page 12) | — (none) |
| INL-RAKE-CURRENT | Rake motor current | Inlet works · SOP-INL-001 p.11 | A | 6 to 9 A | OVERLOAD TRIP 14 (p.11) | NOT SPECIFIED | `SCR-110-MOT-CUR` (direct) |
| INL-SCREEN-FLOW | Inlet flow per screen | Inlet works · SOP-INL-001 p.11 | m³/h | 900 to 1,200 m³/h (plant) | SINGLE-SCREEN CAPACITY 1500 (p.11) | NOT SPECIFIED | `FIT-110-IN` (conflict) |
| BIO-SRT | Sludge age (SRT) | Aeration tanks · SOP-BIO-001 p.17 | days | 5 to 10 days | HIGH 15 (p.17) | NOT SPECIFIED | `AER-201-SLUDGE-AGE` (direct) |
| BIO-MLSS | MLSS | Aeration tanks · SOP-BIO-001 p.17 | mg/L | 2,500 to 3,500 mg/L | HIGH 4500 (p.17) | NOT SPECIFIED | `AER-201-MLSS` (direct) |
| BIO-DO | Dissolved oxygen | Aeration tanks · SOP-BIO-001 p.17 | mg/L | 1.5 to 3.0 mg/L | LOW 1 (p.17) | NOT SPECIFIED | `AIT-201-DO` / alarm `ALM-AER-201-DO` (direct) |
| BIO-FOAM | Foam depth | Aeration tanks · SOP-BIO-001 p.17 | cm | Below 2 cm | HIGH 10 (p.17) | NOT SPECIFIED | `AER-201-FOAM-DEPTH` / alarm `ALM-AER-201-FOAM` (direct) |
| BIO-EFF-TURB | Effluent turbidity | Aeration tanks · SOP-BIO-001 p.17 | NTU | 2 to 5 NTU | SAMPLING ACTION 8 (p.18)<br>PERMIT 10 (p.17) | NOT SPECIFIED | `AER-201-EFF-TURB` (direct) |
| RAS-TOTAL-FLOW | Total RAS flow | Secondary clarifiers, RAS pumps · SOP-BIO-002 p.19 | m³/h | 700 to 840 m³/h | LOW 550 (p.19) | NOT SPECIFIED | `RAS-FLOW` (direct) |
| RAS-WINDING-TEMP | RAS pump winding temperature | Secondary clarifiers, RAS pumps · SOP-BIO-002 p.19 | °C | 60 to 80 °C | TRIP 130 (p.19) | NOT SPECIFIED | — (none) |
| CLR-BLANKET | Sludge blanket depth | Secondary clarifiers, RAS pumps · SOP-BIO-002 p.19 | m | 0.3 to 0.8 m | HIGH 1.5 (p.19)<br>WAS ACTION 2 (p.20)<br>WEIR / P1 2.5 (p.20) | NOT SPECIFIED below 2.5 m; P1 at 2.5 m (page 20) | `SLB-201-DEPTH` / alarm `ALM-SLB-201-HIGH` (direct) |
| CLR-EFF-TSS | Effluent TSS | Secondary clarifiers, RAS pumps · SOP-BIO-002 p.19 | mg/L | 8 to 15 mg/L | PERMIT / P1 30 (p.19) | P1 at 30 mg/L (page 20) | — (none) |
| GAS-HOLDER-PRESS | Holder pressure | Gas line · SOP-GAS-001 p.22 | mbar | 15 to 25 mbar | HIGH 32 (p.22)<br>RELIEF 38 (p.22) | NOT SPECIFIED at 32 mbar; P1 at 38 mbar if flare not burning or relief venting (page 23) | `GAS-601-PRESS` / alarm `ALM-GAS-601-HIGH` (direct) |
| GAS-HOLDER-FILL | Holder fill level | Gas line · SOP-GAS-001 p.22 | % | 40 to 70 % | HIGH 90 (p.22) | NOT SPECIFIED | `GAS-601-FILL` (direct) |
| GAS-PRODUCTION | Biogas production | Gas line · SOP-GAS-001 p.22 | m³/h | 160 to 200 m³/h | none stated | NOT SPECIFIED | `GAS-601-FLOW` (conflict) |
| GAS-CHP-CONSUMPTION | CHP gas consumption | Gas line · SOP-GAS-001 p.22 | m³/h | 150 to 190 m³/h | LOW 100 (p.22) | NOT SPECIFIED | — (none) |
| GAS-LEL | Gas near holder vent | Gas line · SOP-GAS-001 p.22 | % LEL | 0 % LEL | P1 EVACUATE 10 (p.22) | P1 (page 22) | `GAS-601-H2S` (unit_mismatch) |
| SLD-BOWL-SPEED | Bowl speed | Sludge line · SOP-SLD-001 p.24 | rpm | 3,200 rpm | LOW 2900 (p.24) | NOT SPECIFIED | `SLD-701-BOWL-RPM` (direct) |
| SLD-CAPTURE | Solids capture | Sludge line · SOP-SLD-001 p.24 | % | 92 to 97 % | LOW 88 (p.24) | NOT SPECIFIED | `SLD-701-CAPTURE` / alarm `ALM-SLD-701-CAPTURE` (direct) |
| SLD-CAKE-DRY | Cake dryness | Sludge line · SOP-SLD-001 p.24 | % DS | 22 to 26 % DS | LOW 20 (p.24) | NOT SPECIFIED | `SLD-701-CAKE-DRY` (direct) |
| SLD-CENTRATE-NH4 | Centrate ammonia (NH₄-N) | Sludge line · SOP-SLD-001 p.24 | mg/L | 800 to 1,100 mg/L | HIGH 1400 (p.24) | NOT SPECIFIED | `SLD-701-CENTRATE-NH4` (conflict) |
| SLD-INLET-NH4 | Plant inlet ammonia | Sludge line · SOP-SLD-001 p.24 | mg/L | 35 to 42 mg/L | HIGH 50 (p.24) | NOT SPECIFIED | `SLD-701-INLET-NH4` (direct) |
| SLD-BLOWER-AIR | Blower airflow | Sludge line · SOP-SLD-001 p.25 | Nm³/h | 2,800 to 3,400 Nm³/h | MAX 4200 (p.25) | NOT SPECIFIED | — (none) |
| EFF-NH4 | Effluent ammonia | Sludge line · SOP-SLD-001 p.25 | mg/L | 0.5 to 2 mg/L | PERMIT 5 (p.25) | NOT SPECIFIED | `AIT-201-NH4` / alarm `ALM-AER-201-NH4` (conflict) |
| CSE-ATMOSPHERE | Confined space atmosphere (O₂ / LEL / H₂S / CO) | Wet well, tanks, sumps, digester · SOP-GEN-002 p.7 | mixed | Oxygen 19.5 to 23.5 %; Flammable gas below 10 % LEL; H₂S below 10 ppm; CO below 25 ppm | none stated | NOT SPECIFIED | — (none) |

### Acknowledgement, reset, verification and restrictions per parameter

**LFT-WW-LEVEL — Wet well level** (SOP-LFT-001, p.14)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog level limit (high / high-high)
- Acknowledgement: Acknowledge the HIGH level alarm (3.2 m). Check both pumps' status, current and pressure on SCADA. (page 14)
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Watch the wet well level fall below 2.4 m. Release the tanker. (page 15)
- Interlocks / restrictions: Do not enter the wet well. Use SOP-GEN-002 if entry is unavoidable. (page 14); Isolate the failed pump under SOP-GEN-001. (page 14)
- Mapping note: Same quantity and unit. ALM-WW-101-HH is the OpsLens high-high alarm input; its 3.6 m threshold matches page 14.

**LFT-PUMP-CURRENT — Pump motor current** (SOP-LFT-001, p.14)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog current limit
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Verify motor current 28 to 34 A, discharge pressure 2.8 to 3.4 bar, flow 380 m³/h or above. (page 15)
- Interlocks / restrictions: Identify the cause before resetting the thermal overload. Do not reset repeatedly. (page 14)
- Mapping note: Same quantity and unit; the manual's values are per pump (P-101/P-102).

**LFT-WINDING-TEMP — Pump winding temperature** (SOP-LFT-001, p.14)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog temperature trip
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Allow the motor to cool to normal winding temperature (below 75 °C) and check insulation resistance before reset. (page 14)
- Interlocks / restrictions: Identify the cause before resetting the thermal overload. Do not reset repeatedly. (page 14)
- Mapping note: No OpsLens tag currently represents lift pump winding temperature.

**LFT-PUMP-PRESSURE — Pump discharge pressure** (SOP-LFT-001, p.14)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog pressure low limit
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Verify motor current 28 to 34 A, discharge pressure 2.8 to 3.4 bar, flow 380 m³/h or above. (page 15)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: The manual gives a per-pump discharge pressure. OpsLens PIT-101-DIS is described as the lift-station discharge pressure; site confirmation is required that it measures the same point.

**LFT-PUMP-FLOW — Pump flow** (SOP-LFT-001, p.14)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog flow low limit
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Verify motor current 28 to 34 A, discharge pressure 2.8 to 3.4 bar, flow 380 m³/h or above. (page 15)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: Per-pump flow for P-101.

**INL-SCREEN-DL — Differential level across screen** (SOP-INL-001, p.11)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog differential level high
- Acknowledgement: Acknowledge the alarm and inform the supervisor. Check the second screen's status. (page 11)
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Confirm the channel level falls below 1.2 m and the differential level below 15 cm. (page 12)
- Interlocks / restrictions: Isolate the jammed screen under SOP-GEN-001. Never reach into or onto a rake that is not locked out. (page 12)
- Mapping note: OpsLens DPT-110-SCR is a differential pressure in kPa; the manual specifies differential level in cm. Limits are NOT applied automatically.

**INL-CHANNEL-LEVEL — Upstream channel level** (SOP-INL-001, p.11)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog level high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Confirm the channel level falls below 1.2 m and the differential level below 15 cm. (page 12)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: No OpsLens tag currently represents the upstream channel level.

**INL-RAKE-CURRENT — Rake motor current** (SOP-INL-001, p.11)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog current trip
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Restart and observe at least three full rake cycles. Motor current must return to 6 to 9 A. (page 12)
- Interlocks / restrictions: Isolate before inspection (page 11)
- Mapping note: Same quantity and unit.

**INL-SCREEN-FLOW — Inlet flow per screen** (SOP-INL-001, p.11)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog flow high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: OpsLens FIT-110-IN uses a notional 50 MLD plant (1,700–2,350 m³/h baseline). The manual's plant flow is 900–1,200 m³/h. Limits are NOT applied automatically.

**BIO-SRT — Sludge age (SRT)** (SOP-BIO-001, p.17)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Calculated process value high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Review progress daily until foam depth stays below 5 cm for 3 consecutive days. (page 18)
- Interlocks / restrictions: Do not change sludge age by more than 25 % in one day, to avoid shocking the biology. (page 18)
- Mapping note: Same quantity and unit; OpsLens baseline 8–15 days differs from the manual's normal 5–10 days (see conflict report).

**BIO-MLSS — MLSS** (SOP-BIO-001, p.17)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Laboratory / analyser high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: Same quantity and unit.

**BIO-DO — Dissolved oxygen** (SOP-BIO-001, p.17)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analyser low
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Verify DO stays at 1.5 mg/L or above after each change. (page 18)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: Same quantity and unit; OpsLens low trip 1.0 mg/L matches.

**BIO-FOAM — Foam depth** (SOP-BIO-001, p.17)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Observed depth high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Review progress daily until foam depth stays below 5 cm for 3 consecutive days. (page 18)
- Interlocks / restrictions: Do not pump trapped foam directly to the digester without approval. (page 18); Use anti-foam chemicals only on Process Engineer approval, as a short-term measure. (page 18)
- Mapping note: Same quantity and unit; OpsLens trip 15 cm differs from the manual's 10 cm (see conflict report).

**BIO-EFF-TURB — Effluent turbidity** (SOP-BIO-001, p.17)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analyser high / permit
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: OpsLens trip 8 NTU corresponds to the manual's 8 NTU sampling action, not the 10 NTU permit limit.

**RAS-TOTAL-FLOW — Total RAS flow** (SOP-BIO-002, p.19)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog flow low
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Confirm total RAS flow is climbing back toward 700 m³/h or above. (page 20)
- Interlocks / restrictions: Do not repeatedly reset a tripped breaker. Reset only after the cause is identified. (page 20)
- Mapping note: Same quantity, unit and limits.

**RAS-WINDING-TEMP — RAS pump winding temperature** (SOP-BIO-002, p.19)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog temperature trip
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: Do not reset until cool (page 19)
- Mapping note: No OpsLens tag currently represents RAS pump winding temperature.

**CLR-BLANKET — Sludge blanket depth** (SOP-BIO-002, p.19)
- Alarm tag in PDF: SLUDGE BLANKET HIGH (alarm name in text, page 20) · Alarm type: Analog level high
- Acknowledgement: Acknowledge the SLUDGE BLANKET HIGH alarm. Check the actual blanket depth with the probe, then confirm with a manual sample. (page 20)
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Reduce the temporary flow limit gradually and watch the blanket fall below 0.8 m. This normally takes 4 to 8 hours. (page 20)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: Same quantity, unit and 1.5 m high limit.

**CLR-EFF-TSS — Effluent TSS** (SOP-BIO-002, p.19)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Laboratory permit limit
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Sample the effluent hourly until TSS is back below 15 mg/L. (page 20)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: No OpsLens tag currently represents effluent TSS.

**GAS-HOLDER-PRESS — Holder pressure** (SOP-GAS-001, p.22)
- Alarm tag in PDF: GAS HOLDER PRESSURE HIGH (alarm name in text, page 22) · Alarm type: Analog pressure high
- Acknowledgement: Acknowledge the siren and the GAS HOLDER PRESSURE HIGH alarm. Inform the shift supervisor. (page 22)
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Confirm the flare closes and holder pressure returns to 15 to 25 mbar. (page 23)
- Interlocks / restrictions: Do not override a flame-failure trip and do not bypass any gas safety interlock. (page 22); Stop all hot work and cancel active permits under SOP-GEN-005. Allow no ignition sources. (page 22)
- Mapping note: Same quantity and unit; OpsLens trip 35 mbar differs from the manual's 32 mbar alarm (see conflict report).

**GAS-HOLDER-FILL — Holder fill level** (SOP-GAS-001, p.22)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog level high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: 90 % high limit matches; OpsLens baseline 30–70 % differs from 40–70 %.

**GAS-PRODUCTION — Biogas production** (SOP-GAS-001, p.22)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Record only (Alarm / Limit: n/a)
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: OpsLens GAS-601-FLOW is in Nm³/h with a 250–350 baseline; the manual gives 160–200 m³/h.

**GAS-CHP-CONSUMPTION — CHP gas consumption** (SOP-GAS-001, p.22)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog flow low
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Verify gas supply pressure, engine load 380 to 420 kWe and gas consumption 150 to 190 m³/h. (page 23)
- Interlocks / restrictions: Do not restart the engine until the fault is understood and repaired. (page 23)
- Mapping note: OpsLens models CHP state as CHP-601-RUN only.

**GAS-LEL — Gas near holder vent** (SOP-GAS-001, p.22)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Gas detection high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: Any reading of 10 % LEL or above is a P1 event: evacuate the zone, call the fire service, and inform the Plant Manager. (page 23)
- Mapping note: OpsLens GAS-601-H2S is an H₂S detector in ppm; the manual limit is flammable gas in % LEL. Limits are NOT applied automatically.

**SLD-BOWL-SPEED — Bowl speed** (SOP-SLD-001, p.24)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog speed low
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: No setpoints may be changed without Process Engineer approval. (page 25)
- Mapping note: Same quantity and unit.

**SLD-CAPTURE — Solids capture** (SOP-SLD-001, p.24)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Laboratory / calculated low
- Acknowledgement: Acknowledge the alarm or laboratory report showing low capture, low cake dryness, or high centrate ammonia. (page 25)
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Adjust and re-sample until readings are in the Operating Limits table. (page 25)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: Same quantity and unit; OpsLens trip 80 % differs from the manual's 88 % (see conflict report).

**SLD-CAKE-DRY — Cake dryness** (SOP-SLD-001, p.24)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Laboratory low
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: OpsLens unit '%' assumed to mean % DS.

**SLD-CENTRATE-NH4 — Centrate ammonia (NH₄-N)** (SOP-SLD-001, p.24)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Laboratory high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: OpsLens baseline 20–50 mg/L / trip 100 mg/L is an order of magnitude below the manual's 800–1,100 / 1,400 mg/L. Limits are NOT applied automatically until the simulated tag is rescaled.

**SLD-INLET-NH4 — Plant inlet ammonia** (SOP-SLD-001, p.24)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analyser / laboratory high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Increase the frequency of effluent ammonia sampling to every 4 hours until inlet ammonia is back below 42 mg/L. (page 25)
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: Same quantity and unit.

**SLD-BLOWER-AIR — Blower airflow** (SOP-SLD-001, p.25)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Analog flow high
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: Where blower airflow approaches 4,200 Nm³/h, pause centrifuge feed and further centrate return, with the Process Engineer's approval. (page 26)
- Mapping note: No OpsLens tag currently represents blower airflow.

**EFF-NH4 — Effluent ammonia** (SOP-SLD-001, p.25)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Permit limit
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: NOT SPECIFIED
- Interlocks / restrictions: NOT SPECIFIED
- Mapping note: OpsLens AIT-201-NH4 is an aeration-basin analyser (1–3 mg/L baseline, 8 mg/L trip). The manual's 5 mg/L is a final-effluent permit limit; the measurement points differ.

**CSE-ATMOSPHERE — Confined space atmosphere (O₂ / LEL / H₂S / CO)** (SOP-GEN-002, p.7)
- Alarm tag in PDF: NOT SPECIFIED · Alarm type: Personal / portable gas monitor (entry permit)
- Acknowledgement: NOT SPECIFIED
- Reset / clear condition: NOT SPECIFIED
- Verification criteria: Re-test the atmosphere at least every 2 hours and after any break. (page 8)
- Interlocks / restrictions: Leave immediately if: O₂ below 19.5 % or above 23.5 %; 10 % LEL or above; H₂S 10 ppm or above; CO 25 ppm or above. (page 7)
- Mapping note: Portable entry-permit limits; not mapped to fixed OpsLens telemetry.

## Mapping categories

| Mapping | Meaning | Limit check applied? |
|---|---|---|
| `direct` | Same quantity and unit as the OpsLens tag | Yes |
| `assumed` | Probably the same measurement point; site confirmation needed | Yes, labelled *Mapping assumed* |
| `unit_mismatch` | Different engineering quantity/unit (e.g. kPa vs cm) | No |
| `conflict` | Same quantity but OpsLens simulates a very different scale or measurement point | No |
| `none` | Not instrumented in OpsLens (reported as missing evidence) | No |

## Conflicts between the manual and the OpsLens tag registry

Generated from `GET /api/alarms/conflicts`. **Reported, not auto-fixed:** confirm the site value, then change one source.

| Tag | Field | SOP manual | OpsLens registry | Page | Mapping |
|---|---|---|---|---|---|
| `PIT-101-DIS` | normal_low | 2.8 | 1.8 | 14 | assumed |
| `PIT-101-DIS` | normal_high | 3.4 | 3.0 | 14 | assumed |
| `PIT-101-DIS` | trip_threshold | LOW=2.0 | 4.2 | 14 | assumed |
| `FIT-101-P1-FLW` | normal_low | 380.0 | 350.0 | 14 | direct |
| `DPT-110-SCR` | unit | cm | kPa | 11 | unit_mismatch |
| `DPT-110-SCR` | normal_low | 5.0 | 0.5 | 11 | unit_mismatch |
| `DPT-110-SCR` | normal_high | 15.0 | 1.5 | 11 | unit_mismatch |
| `DPT-110-SCR` | trip_threshold | HIGH=30.0 | 4.0 | 11 | unit_mismatch |
| `FIT-110-IN` | normal_low | 900.0 | 1700.0 | 11 | conflict |
| `FIT-110-IN` | normal_high | 1200.0 | 2350.0 | 11 | conflict |
| `FIT-110-IN` | trip_threshold | SINGLE-SCREEN CAPACITY=1500.0 | 3200.0 | 11 | conflict |
| `AER-201-SLUDGE-AGE` | normal_low | 5.0 | 8.0 | 17 | direct |
| `AER-201-SLUDGE-AGE` | normal_high | 10.0 | 15.0 | 17 | direct |
| `AIT-201-DO` | normal_high | 3.0 | 2.5 | 17 | direct |
| `AER-201-FOAM-DEPTH` | normal_high | 2.0 | 5.0 | 17 | direct |
| `AER-201-FOAM-DEPTH` | trip_threshold | HIGH=10.0 | 15.0 | 17 | direct |
| `AER-201-EFF-TURB` | normal_low | 2.0 | 1.0 | 17 | direct |
| `AER-201-EFF-TURB` | normal_high | 5.0 | 4.0 | 17 | direct |
| `GAS-601-PRESS` | trip_threshold | HIGH=32.0, RELIEF=38.0 | 35.0 | 22 | direct |
| `GAS-601-FILL` | normal_low | 40.0 | 30.0 | 22 | direct |
| `GAS-601-FLOW` | unit | m³/h | Nm³/h | 22 | conflict |
| `GAS-601-FLOW` | normal_low | 160.0 | 250.0 | 22 | conflict |
| `GAS-601-FLOW` | normal_high | 200.0 | 350.0 | 22 | conflict |
| `GAS-601-H2S` | unit | % LEL | ppm | 22 | unit_mismatch |
| `GAS-601-H2S` | normal_high | 0.0 | 5.0 | 22 | unit_mismatch |
| `SLD-701-BOWL-RPM` | normal_low | 3200.0 | 3150.0 | 24 | direct |
| `SLD-701-BOWL-RPM` | normal_high | 3200.0 | 3250.0 | 24 | direct |
| `SLD-701-CAPTURE` | normal_low | 92.0 | 90.0 | 24 | direct |
| `SLD-701-CAPTURE` | trip_threshold | LOW=88.0 | 80.0 | 24 | direct |
| `SLD-701-CAKE-DRY` | unit | % DS | % | 24 | direct |
| `SLD-701-CAKE-DRY` | normal_low | 22.0 | 20.0 | 24 | direct |
| `SLD-701-CAKE-DRY` | normal_high | 26.0 | 25.0 | 24 | direct |
| `SLD-701-CENTRATE-NH4` | normal_low | 800.0 | 20.0 | 24 | conflict |
| `SLD-701-CENTRATE-NH4` | normal_high | 1100.0 | 50.0 | 24 | conflict |
| `SLD-701-CENTRATE-NH4` | trip_threshold | HIGH=1400.0 | 100.0 | 24 | conflict |
| `SLD-701-INLET-NH4` | normal_low | 35.0 | 20.0 | 24 | direct |
| `SLD-701-INLET-NH4` | normal_high | 42.0 | 50.0 | 24 | direct |
| `AIT-201-NH4` | normal_low | 0.5 | 1.0 | 25 | conflict |
| `AIT-201-NH4` | normal_high | 2.0 | 3.0 | 25 | conflict |
| `AIT-201-NH4` | trip_threshold | PERMIT=5.0 | 8.0 | 25 | conflict |

### Conflicts that matter most for the demo

- **`PIT-101-DIS` direction.** The manual's pump discharge pressure has a **LOW** limit of 2.0 bar (normal 2.8–3.4, p.14, "Suspect clog"). The registry has a **high** trip at 4.2 bar. In the wet-well scenario the pressure falls to 1.7 bar: the SOP limit check flags it, but the registry's prioritiser treats it only as an excursion. Recommended: confirm whether `PIT-101-DIS` is the per-pump discharge pressure, then set a low trip of 2.0 bar.
- **`GAS-601-PRESS`** trip 35 mbar vs manual alarm 32 mbar / relief 38 mbar (p.22).
- **`SLD-701-CAPTURE`** trip 80 % vs manual 88 % (p.24); **`AER-201-FOAM-DEPTH`** trip 15 cm vs 10 cm (p.17).
- **`SLD-701-CENTRATE-NH4`** is simulated at 20–50 mg/L; the manual's normal centrate ammonia is 800–1,100 mg/L. Limits are not applied until the simulated tag is rescaled.
- **`DPT-110-SCR`** is a differential *pressure* in kPa; the manual specifies differential *level* in cm. Not comparable.
- **`LIT-101-WWL` / `ALM-WW-101-HH`** agree with the manual (normal 1.0–2.4 m, HH 3.6 m).

## Alarm lifecycle implemented

| State (`/api/alarms/active`) | Meaning | How it is reached |
|---|---|---|
| `ACTIVE_UNACK` | Input TRUE, not acknowledged | First TRUE reading of an alarm input |
| `ACTIVE_ACK` | Input TRUE, acknowledged | Operator acknowledgement (`POST /api/actions`, `ACKNOWLEDGE` with `alarm_id`). **Does not clear.** |
| `RTN_UNACK` | Input returned to FALSE, never acknowledged | FALSE reading with a timestamp later than the last TRUE |
| `NORMAL` | Returned to normal and acknowledged | Both of the above |
| `UNKNOWN` | No reading of the input recorded | — |

Incident resolution is separate: `RESOLVE` requires a later FALSE reading of the source alarm and an operator confirmation; OpsLens never writes the PLC.

**Repeat count:** incremented on re-activation after return-to-normal, or on an explicit re-annunciation (`alarm_state="REANNUNCIATED"`, used by *Trigger same alarm again*). Polled samples of a TRUE input (simulator, OPC UA) do not increment it. Push-style notifications without a polled `data_source` count as notifications, as before.

**Status tags:** `status_normal_states` in the JSON (OpsLens demo configuration, not from the PDF) defines the normal state of discrete status tags: `P101-RUN`, `RAS-P1-RUN`, `SCR-110-RAKE-RUN`, `CHP-601-RUN` normally TRUE; `FLR-601-RUN` normally FALSE. A change away from normal is evidence, never an alarm.

## Gaps in the manual

- The manual does not list PLC/HMI alarm tag names, alarm deadbands, on/off delays, or reset/clear conditions for any alarm.
- The manual does not assign a P1/P2/P3 priority to individual alarm limits, except where an escalation clause states the event becomes P1.
- The manual contains no procedures for tertiary filtration, UV disinfection, hypochlorite backup, effluent diversion or microbiological sampling (relevant to OpsLens Scenario 7).
- All numerical values are 'typical values for a mid-size plant' (page 2) and the approval table (page 1) is blank.

## Updating the configuration

1. Edit `edge_intelligence/config/alarm_reference.json` (keep `source_page` for every value).
2. Restart the backend (the file is cached at start-up).
3. Run `run_tests.bat` — `tests/test_alarm_reference_and_brief.py` checks page ranges, the wet-well limits and conflict reporting.
4. To change a registry threshold, edit `tag_registry.py` and record the reason in CHANGELOG.md; the conflict report will update automatically.

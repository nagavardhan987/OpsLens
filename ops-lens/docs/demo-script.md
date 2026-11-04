# OpsLens — 3-Minute Live Demo Script
### Schneider Electric Innovation Marathon (PS1: AI-Powered Runtime Copilot for Industrial HMI)
**Team: Sentient Screens** (Aditya S, Daksh M, Nagavardhan N)

---

## Demo Setup Checklist Before Presenting
- [ ] Backend running on `http://localhost:8000` (`python -m uvicorn backend.main:app --port 8000`)
- [ ] Frontend running on `http://localhost:5173` (`npm run dev`)
- [ ] Browser opened in full screen at `http://localhost:5173`
- [ ] Dashboard in baseline state: `● SYSTEM RUNNING NOMINAL`, 0 Active Alarms.

---

## 0:00 – 0:30 | The Problem & Baseline State

**Spoken Script:**
> *"Good morning, judges. Today, when an alarm trips in an industrial plant, operators are hit with an alarm flood. Disjointed sensor values flash simultaneously, experienced operators rely on unwritten tribal knowledge, and junior operators struggle to identify what actually broke first.*
>
> *This is OpsLens: an AI-Powered Runtime Copilot designed specifically for low-end HMI hardware like Schneider Electric's EcoStruxure Operator Terminal Expert.*
>
> *Notice our baseline: Pump-02 is running normally at 4.8 bar discharge pressure, 82 L/min flow, and 78% valve opening. Everything is nominal with zero alarm clutter."*

**Action on Screen:**
- Point cursor to **Sticky Status Header** (`● SYSTEM RUNNING NOMINAL`) and the 4 green telemetry cards.

---

## 0:30 – 1:15 | Starting the Incident & The Event Story Centerpiece

**Spoken Script:**
> *"Now, let's simulate an operational excursion on Feed Water Pump-02 by clicking [ START INCIDENT ].*
>
> *Watch the screen. Instead of throwing 4 random disconnected alarms at the operator, OpsLens correlates the process physics:*
> - *At 14:31, Valve-04 position dropped from 78% down to 43%.*
> - *4 seconds later, downstream discharge flow drops to 56 L/min.*
> - *Motor current climbs to 9.2 Amps due to hydraulic backpressure.*
> - *Pressure spikes to 6.9 bar, breaching the 6.0 bar limit and triggering a High Pressure Alarm.*
>
> *Look at our Event Story: this is the centerpiece of OpsLens. It proves that the valve deviation happened 60 seconds before the alarm. The alarm is not an isolated electrical fault; it is the consequence of a mechanical restriction."*

**Action on Screen:**
- Click `[ START INCIDENT ]`.
- Watch the telemetry gauges transition from green to amber and red.
- Point to the **Event Story** timeline cards unfolding chronologically from 14:31 to 14:32.

---

## 1:15 – 1:50 | Evidence-Backed Likely Contributor (Defensible AI)

**Spoken Script:**
> *"Crucially, OpsLens is NOT a generative chatbot guessing what happened. We strictly adhere to defensible industrial AI:*
> *Notice the phrasing: 'Likely contributor based on correlated evidence: Valve-04 restriction.'*
>
> *Every claim is backed by empirical mathematical proof:*
> - *Valve position decreased by 45% (78 to 43)*
> - *Flow decreased by 32% (82 to 56)*
> - *Motor current surged by 18% (7.8 to 9.2 A)*
> - *Discharge pressure surged by 44% (4.8 to 6.9 bar)*
> - *And the valve deviation preceded the alarm.*
>
> *This gives the operator 100% explainability in under 5 seconds."*

**Action on Screen:**
- Scroll slightly to highlight the **Evidence-Backed Likely Contributor** card and the green verified badges.

---

## 1:50 – 2:15 | Contextual SOP Retrieval (HP-P02)

**Spoken Script:**
> *"Rather than digging through paper binders or searching static intranet PDFs, OpsLens instantly retrieves the exact relevant standard operating procedure: SOP HP-P02 — High Pressure Response.*
>
> *Clicking [ VIEW SOP ] opens the full 5-step interactive procedure. Operators can check off verification steps in real time with embedded safety warnings regarding line hammering and burst disc thresholds."*

**Action on Screen:**
- Click `[ VIEW SOP (5-STEP PROCEDURE) ]`.
- Scroll through the 5 steps in the modal, click step 1 and step 2 to show interactive verification checkmarks, then close the modal.

---

## 2:15 – 2:45 | Human-in-the-Loop & Next-Best Action

**Spoken Script:**
> *"Notice our cardinal safety principle: 'Operator approval required.' OpsLens never autonomously commands the PLC. The AI recommends; the human operator decides.*
>
> *On the main HMI dashboard, we provide 4 immediate action buttons:*
> *1. Verify Valve-04*
> *2. Review Pump-02*
> *3. View SOP*
> *4. Mark Action Complete*
>
> *When I click [ VERIFY VALVE-04 ], notice the instant feedback: 'Operator action recorded'. The system logs this directly to our audit trail under certified operator J. Rivera."*

**Action on Screen:**
- Click `[ VERIFY VALVE-04 ]`.
- Show the green banner: `✓ Operator action recorded: Verify Valve-04 position and condition`.
- Click `[ MARK ACTION COMPLETE ]`.

---

## 2:45 – 3:00 | Automated Shift Handover & Reset

**Spoken Script:**
> *"Finally, when shift change arrives at 15:00, no knowledge is lost. OpsLens automatically compiles the Shift Handover Dossier:*
> - *Incident: High pressure detected at 14:32*
> - *Likely Contributor: Valve-04 restriction*
> - *Operator Action: Valve-04 verified by J. Rivera (Shift 2)*
> - *Current Status: Action Completed / Monitoring*
>
> *And with one click on [ RESET DEMO ], our system returns cleanly to steady state. OpsLens empowers operators to respond faster, reduce downtime, and preserve plant knowledge—all on edge hardware. Thank you!"*

**Action on Screen:**
- Show the Shift Handover card or modal with updated action text and operator signature.
- Click `[ RESET DEMO ]` to show instantaneous return to normal green running state.

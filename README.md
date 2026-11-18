<div align="center">

<img width="100%" src="https://capsule-render.vercel.app/api?type=waving&color=0:0b4f6c,100:01baef&height=210&section=header&text=OpsLens&fontSize=70&fontColor=ffffff&animation=fadeIn&fontAlignY=38&desc=AI%20Copilot%20for%20Industrial%20HMI%20%E2%80%94%20evidence-based%20incident%20investigation&descAlignY=60&descSize=16"/>

### 🥇 Winner · Schneider Electric HMI Hackathon 2026 (Innovation Marathon)
**Team Sentient Screens · SRM Institute of Science and Technology · Problem Statement PS1 — AI-Powered Runtime Copilot for Industrial HMI**

<img src="https://img.shields.io/badge/Status-Prototype-01baef?style=for-the-badge"/>
<img src="https://img.shields.io/badge/Mode-Read--only%20%26%20Advisory-0b4f6c?style=for-the-badge"/>
<img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge"/>
<img src="https://img.shields.io/badge/Tests-348%20automated-success?style=for-the-badge"/>

</div>

> **ℹ️ About this repository** — This is the public **showcase** for OpsLens. The full source code is kept in a **private repository**. If you'd like a walkthrough or access for evaluation, please [reach out](mailto:nn7326@srmist.edu.in).
>
> *OpsLens is a student prototype. It is not a Schneider Electric product and is not deployed at any plant.*

---

## 🎯 The Problem

A traditional HMI tells the operator **that** an alarm is active. It stops there. During a real incident — foam on an aeration tank, a lift-station pump clogging, a CHP engine tripping — the operator has to mentally reconstruct *what actually happened*, dig through the SOP manual, and judge how urgent it is, all while the clock runs.

## 💡 The Solution

**OpsLens reconstructs the story behind the alarm.** For every incident it answers:

- 🔍 **What happened?** — which readings moved first, which equipment is involved, the recorded chronological sequence
- 📖 **What does the SOP say?** — the exact procedure steps, copied **verbatim** from the cited manual page
- 📏 **How bad is it?** — how far the process is from the next escalation, every margin calculated in Python
- ✅ **How will we know it's fixed?** — explicit recovery and verification criteria

It is **advisory and read-only**. OpsLens never starts or stops a motor, changes a speed, opens a valve, writes a PLC variable, or overrides an interlock. The operator always acts through the plant's existing systems.

---

## 📸 Screenshots

<div align="center">

**Home — live alarm with leading hypothesis, SOP steps and deviation from limits**
<img src="docs/screenshots/home_live_alarm.png" width="85%"/>

<table>
<tr>
<td width="50%"><img src="docs/screenshots/confidence_score.png"/><p align="center"><sub>Evidence Support score with every check shown</sub></p></td>
<td width="50%"><img src="docs/screenshots/related_incidents.png"/><p align="center"><sub>Related incidents from recent history</sub></p></td>
</tr>
<tr>
<td width="50%"><img src="docs/screenshots/shift_panel.png"/><p align="center"><sub>Current shift panel</sub></p></td>
<td width="50%"><img src="docs/screenshots/trend_30_days.png"/><p align="center"><sub>30-day trend with dated axis</sub></p></td>
</tr>
</table>

<sub>Simulated data (Scenario Lab), captured at 1280×800 with a stand-in model.</sub>

</div>

---

## ✨ Key Features

| | Feature | What it does |
|---|---|---|
| 🧩 | **Evidence engine** | Builds cause candidates from recorded data only and ranks them by a transparent, rule-based score (not a black-box probability) |
| 📚 | **Verbatim SOP guidance** | Shows the numbered procedure steps exactly as printed, with page numbers — never an invented procedure |
| 🤖 | **Honest AI diagnosis** | An LLM *explains* the established facts in 8 sections; every line is validated against the record and labelled with its true source |
| 📈 | **Time-series analytics** | Rolling anomaly markers, gated local-trend forecasts with backtest, and predictive warnings |
| 🔄 | **Full alarm lifecycle** | Active → Acknowledged → Recovered → Resolved, with acknowledgement kept separate from clearing |
| 🗂️ | **Shift handover** | Record-grounded operator briefs and shift summaries |
| 🔌 | **Read-only OPC UA** | Optional read-only client for M241/M251 PLCs — no writes, ever |

---

## 🏗️ Architecture

```text
        ┌──────────── Telemetry (read-only) ────────────┐
        │  Synthetic scenario generator │ OPC UA client  │
        └───────────────┬───────────────┴───────────────┘
                        ▼
                SQLite tag_readings  (timestamps, quality)
                        │
        ┌───────────────▼────────────────────────────────┐
        │ Orchestrator (asyncio)                          │
        │  contextualise → prioritise → dedup/lifecycle → │
        │  correlate → event story → evidence ranking →   │
        │  SOP retrieval → guidance                       │
        └───────────────┬────────────────────────────────┘
                        ▼
                  FastAPI  /api/...
            ┌───────────┴───────────┐
            ▼                       ▼
     Operator HMI (5173)   Engineering Console (5174)
     alarms · story ·      Scenario Lab · Procedures ·
     brief · Ask OpsLens   Alarm Reference · Metrics
```

> Everything that decides *what happened* is **deterministic Python**. Language models are optional — they explain facts already established, and every answer is checked against the record.

---

## 🧰 Tech Stack

<p>
<img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
<img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
<img src="https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB"/>
<img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white"/>
<img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white"/>
<img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white"/>
<img src="https://img.shields.io/badge/OPC%20UA-00599C?style=for-the-badge"/>
</p>

**Backend:** FastAPI · asyncio orchestrator · SQLite (WAL) · 348 automated tests
**Frontend:** React + Vite — Operator HMI (1280×800 panel) and Engineering Console
**AI:** pluggable LLM providers (LM Studio / Groq / Gemini / OpenAI / Anthropic), all optional
**Retrieval:** curated SOP sections · Qdrant vectors · BM25 fallback

---

## 🧠 How a Cause Is Chosen

When an alarm becomes an incident, the backend builds cause candidates from recorded data only and scores each on its own evidence — recorded trips, what changed before the primary alarm, the size of the deviation, corroborating readings, SOP limits exceeded, and process topology. Contradicting readings subtract points. Candidates are ordered and assigned roles: **Leading**, **Contributing**, **Related condition**, **Possible consequence**, or **Insufficient evidence**.

Points are **not** probabilities — they are an auditable rating of the evidence in the record, and every candidate carries a plain-English ranking note.

---

## 👥 Team

**Team Sentient Screens** — SRM Institute of Science and Technology

## 📄 License

Released under the **MIT License**.

<div align="center">
<img width="100%" src="https://capsule-render.vercel.app/api?type=waving&color=0:01baef,100:0b4f6c&height=120&section=footer"/>
</div>

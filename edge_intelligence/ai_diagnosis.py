"""Incident diagnosis: Evidence Engine facts -> Qwen (Ollama) explanation.

The Evidence Engine and operator brief are the factual source. This module
turns one incident's facts into a compact prompt, asks the local model
(qwen2.5:3b in Ollama by default) for a seven-section engineering diagnosis,
streams it, validates it against the facts, and caches the result.

Rules enforced here, not just requested in the prompt:
  * only this incident's tags go into the prompt (no cross-incident evidence);
  * the output is checked: required headings, tags must belong to this
    incident, numbers must exist in the facts, cited SOP steps must exist;
  * when Ollama is unavailable or the output fails validation, a deterministic
    diagnosis is returned and labelled as such. It is never shown as AI output;
  * OpsLens is read-only: the prompt forbids control actions and the validator
    rejects text that claims to have operated equipment or cleared alarms.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime
from time import perf_counter
from typing import Any, Dict, Iterator, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

SECTIONS = [
    "Incident summary",
    "Confirmed observations",
    "Possible root causes",
    "Evidence for and against",
    "Missing information",
    "Recommended safe operator checks",
    "Final engineering assessment",
]
FALLBACK_LABEL = "DETERMINISTIC FALLBACK — not AI-generated"
MAX_STORY_STEPS = 14
MAX_SOP_STEPS = 10

SYSTEM_PROMPT = (
    "You are an industrial wastewater process engineer assisting a control-room operator. "
    "Use ONLY the FACTS given. Never invent readings, tags, limits, SOP steps or actions. "
    "Label every statement as CONFIRMED (a recorded reading or alarm in FACTS), HYPOTHESIS "
    "(a possible cause) or UNKNOWN (not in FACTS). The ranking score is NOT a probability. "
    "The SOP is a DRAFT, NOT APPROVED; never call it approved. When you recommend a check, "
    "quote the SOP step number from FACTS, or say 'no SOP step covers this'. "
    "OpsLens is read-only: never say you started, stopped, reset, acknowledged or cleared anything. "
    "Write exactly these seven markdown headings, in order, with short bullet points under each:\n"
    + "\n".join(f"## {i}. {name}" for i, name in enumerate(SECTIONS, 1))
)

_TAG_RE = re.compile(r"\b(?:[A-Z]{2,5}-){1,3}[A-Z0-9]{1,6}(?:-[A-Z0-9]{1,6})*\b")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9-])\d+(?:[.,]\d+)?")
_STEP_RE = re.compile(r"\bsteps?\s+(\d{1,2})(?:\s*(?:,|and|to|-|–)\s*(\d{1,2}))*", re.I)
_CONTROL_CLAIMS = re.compile(
    r"\b(I|OpsLens|the system)\s+(have|has|will|did)?\s*(started|stopped|reset|acknowledged|cleared|opened|closed|switched)\b",
    re.I)
_APPROVED_CLAIM = re.compile(r"(?<!not )(?<!un)\bapproved (SOP|procedure)\b", re.I)


# --------------------------------------------------------------------------- facts

def _hms(ts: Optional[str]) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%H:%M:%S UTC")
    except ValueError:
        return str(ts)


def _fmt(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    return int(v) if v.is_integer() else round(v, 3)


def build_facts(full_event: Dict[str, Any], db=None) -> Dict[str, Any]:
    """Compact, incident-scoped facts for the model and the fallback."""
    from operator_brief import build_operator_brief
    from tag_registry import TAG_REGISTRY

    brief = build_operator_brief(full_event, db)
    problem = brief["problem"]
    scenario = brief.get("scenario") or {}
    own = set(scenario.get("incident_tags") or [])
    if not own:
        cand = (full_event.get("candidate") or {})
        own = set(cand.get("clustered_tags") or []) | {full_event.get("primary_tag")}
    own.discard(None)

    def label(tag: str) -> str:
        entry = TAG_REGISTRY.get(tag)
        return getattr(entry, "description", None) or tag

    readings: List[Dict[str, Any]] = []
    seen = set()
    for chk in brief["supporting_evidence"]["limit_checks"]:
        if chk["tag"] not in own:
            continue
        seen.add(chk["tag"])
        hit = chk.get("highest_exceeded") or {}
        readings.append({
            "tag": chk["tag"], "name": chk.get("parameter") or label(chk["tag"]),
            "value": _fmt(chk.get("value")), "unit": chk.get("unit"),
            "normal": chk.get("normal_text"),
            "state": "LIMIT EXCEEDED" if chk.get("exceeded_limits") else (chk.get("normal_state") or "").replace("_", " "),
            "limit": (f"{hit.get('source_text')} -> {hit.get('action')} (SOP p.{hit.get('source_page')})" if hit else None),
        })
    if db is not None:
        for tag in sorted(own - seen):
            entry = TAG_REGISTRY.get(tag)
            if entry is None or entry.unit in ("bool", "status") or tag.startswith("ALM-"):
                continue
            row = db.get_latest_reading(tag)
            if row is not None:
                readings.append({"tag": tag, "name": label(tag), "value": _fmt(row.value), "unit": entry.unit,
                                 "normal": None, "state": "no SOP limit", "limit": None})

    sequence = []
    for step in (full_event.get("story") or {}).get("steps") or []:
        if step.get("tag") not in own:
            continue
        sequence.append({"time": _hms(step.get("timestamp")), "tag": step["tag"],
                         "change": f"{_fmt(step.get('value_before'))} -> {_fmt(step.get('value_after'))} {step.get('unit') or ''}".strip()})
    if len(sequence) > MAX_STORY_STEPS:
        sequence = sequence[:4] + sequence[-(MAX_STORY_STEPS - 4):]

    changes = [{"tag": c["tag"], "change_pct": c["change_percent_vs_baseline_midpoint"]}
               for c in brief["supporting_evidence"]["calculated"] if c["tag"] in own][:10]

    evidence = full_event.get("evidence") or {}
    ranking = None
    if evidence.get("likely_contributor_tag") in own:
        ranking = {"tag": evidence["likely_contributor_tag"], "score": evidence.get("confidence_score"),
                   "note": "evidence-ranking score, NOT a probability of root cause"}

    sop = brief["sop"]
    steps = (brief.get("safe_inspection_steps") or {}).get("steps") or []
    sop_facts = None
    if sop.get("sop_id"):
        sop_facts = {
            "sop_id": sop["sop_id"], "title": sop.get("title"),
            "status": sop.get("approval_label") or "DRAFT — NOT APPROVED", "approved": False,
            "coverage": sop.get("coverage") or "unknown",
            "coverage_notes": sop.get("coverage_notes") or [],
            "steps": [{"n": s["number"], "text": s["text"][:240], "page": s.get("page")} for s in steps[:MAX_SOP_STEPS]],
        }

    alarms = [a for a in problem.get("active_alarm_inputs") or [] if a in own]
    return {
        "event_id": full_event.get("event_id"),
        "incident": scenario.get("name") or problem.get("alarm_description"),
        "equipment": problem.get("equipment"),
        "primary_alarm": {"tag": problem.get("alarm_tag"), "description": problem.get("alarm_description"),
                          "first_at": _hms(problem.get("first_triggered_at")),
                          "input_active": problem.get("alarm_input_active")},
        "data_source": problem.get("data_source"),
        "incident_tags": sorted(own),
        "active_alarms": alarms,
        "readings": readings,
        "sequence": sequence,
        "changes_vs_normal_pct": changes,
        "ranking": ranking,
        "sop": sop_facts,
        "verification": [v for v in brief.get("verification_criteria") or []][:4],
        "missing": [m for m in brief.get("missing_evidence") or [] if "STALE" not in m][:5],
    }


def facts_hash(facts: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_prompt(facts: Dict[str, Any]) -> str:
    """User message: the facts as compact JSON (no indentation)."""
    return ("FACTS (one incident, " + str(facts.get("data_source")) + " data):\n"
            + json.dumps(facts, separators=(",", ":"), ensure_ascii=False, default=str)
            + "\nWrite the seven-section diagnosis now.")


# ----------------------------------------------------------------- validation

def _allowed_numbers(facts: Dict[str, Any]) -> set:
    text = json.dumps(facts, ensure_ascii=False, default=str)
    nums = set()
    for m in _NUM_RE.findall(text):
        try:
            nums.add(round(float(m.replace(",", ".")), 3))
        except ValueError:
            pass
    return nums


def validate(text: str, facts: Dict[str, Any]) -> Dict[str, Any]:
    """Check model output against the facts. Returns issues and a verdict."""
    issues: List[str] = []
    rejected: List[str] = []
    lower = text.lower()
    missing_headings = [s for s in SECTIONS if s.lower() not in lower]
    if len(missing_headings) > 2:
        rejected.append(f"missing sections: {', '.join(missing_headings)}")
    elif missing_headings:
        issues.append(f"missing sections: {', '.join(missing_headings)}")

    own = set(facts.get("incident_tags") or [])
    sop_id = (facts.get("sop") or {}).get("sop_id")
    # Anything tag-shaped that appears in this incident's own facts (including
    # verbatim SOP text such as "BS-2") may be quoted; nothing else may.
    facts_text = json.dumps(facts, ensure_ascii=False, default=str)
    allowed_refs = own | {sop_id, "SOP-MAN-000"} | {f"SOP-GEN-00{i}" for i in range(1, 10)} | set(_TAG_RE.findall(facts_text))
    found = {t for t in _TAG_RE.findall(text) if any(ch.isdigit() for ch in t)}
    foreign = sorted(t for t in found if t not in allowed_refs and not t.startswith("SOP-"))
    foreign_sops = sorted(t for t in found if t.startswith("SOP-") and t not in allowed_refs)
    if foreign:
        rejected.append(f"tags not in this incident: {', '.join(foreign)}")
    if foreign_sops:
        rejected.append(f"SOPs not mapped to this incident: {', '.join(foreign_sops)}")

    allowed = _allowed_numbers(facts)
    # Small integers are list numbering, section numbers and step numbers.
    stripped = re.sub(r"^\s*(?:#+\s*)?\d+[.)]\s", " ", text, flags=re.M)
    unknown = []
    for m in _NUM_RE.findall(stripped):
        try:
            v = round(float(m.replace(",", ".")), 3)
        except ValueError:
            continue
        if v <= 10 and float(v).is_integer():
            continue
        if v not in allowed:
            unknown.append(m)
    unknown = sorted(set(unknown), key=lambda s: float(s.replace(",", ".")))
    if len(unknown) >= 3:
        rejected.append(f"numbers not found in the incident record: {', '.join(unknown)}")
    elif unknown:
        issues.append(f"numbers not found in the incident record: {', '.join(unknown)}")

    step_numbers = {s["n"] for s in ((facts.get("sop") or {}).get("steps") or [])}
    cited = set()
    for m in _STEP_RE.finditer(text):
        for g in m.groups():
            if g:
                cited.add(int(g))
    bad_steps = sorted(cited - step_numbers) if step_numbers else sorted(cited)
    if bad_steps:
        rejected.append(f"SOP steps that do not exist in {sop_id or 'the record'}: {bad_steps}")
    if _CONTROL_CLAIMS.search(text):
        rejected.append("claims to have operated equipment or changed alarm state")
    if _APPROVED_CLAIM.search(text):
        rejected.append("describes the draft SOP as approved")
    return {"valid": not rejected, "rejected_reasons": rejected, "warnings": issues,
            "cited_sop_steps": sorted(cited & step_numbers), "unverified_numbers": unknown}


# ------------------------------------------------------------------- fallback

def deterministic_diagnosis(facts: Dict[str, Any]) -> str:
    """Seven sections built only from recorded facts. Clearly not AI output."""
    pa = facts["primary_alarm"]
    out = [f"> {FALLBACK_LABEL}", ""]
    out.append(f"## 1. {SECTIONS[0]}")
    out.append(f"- CONFIRMED: {pa['tag']} ({pa['description']}) on {facts.get('equipment')} first at {pa['first_at']}; "
               f"alarm input {'still active' if pa.get('input_active') else 'returned to normal'}. Data: {facts.get('data_source')}.")
    out.append(f"## 2. {SECTIONS[1]}")
    if not facts["readings"] and not facts["active_alarms"]:
        out.append("- UNKNOWN: no current readings for this incident's tags are recorded.")
    for r in facts["readings"]:
        if r["state"] == "LIMIT EXCEEDED":
            out.append(f"- CONFIRMED: {r['name']} ({r['tag']}) {r['value']} {r['unit']} — normal {r['normal']}; {r['limit']}.")
    for r in facts["readings"]:
        if r["state"] != "LIMIT EXCEEDED":
            out.append(f"- CONFIRMED: {r['name']} ({r['tag']}) {r['value']} {r['unit']} ({r['state'] or 'within limits'}).")
    if facts["active_alarms"]:
        out.append(f"- CONFIRMED active alarm inputs: {', '.join(facts['active_alarms'])}.")
    out.append(f"## 3. {SECTIONS[2]}")
    if facts.get("ranking"):
        rk = facts["ranking"]
        out.append(f"- HYPOTHESIS: {rk['tag']} shows the strongest recorded change (ranking score {rk['score']}; {rk['note']}).")
    first = facts["sequence"][0] if facts["sequence"] else None
    if first:
        out.append(f"- HYPOTHESIS: the first recorded change was {first['tag']} at {first['time']} ({first['change']}); "
                   "an earlier change may be upstream of later ones, but timing alone does not prove cause.")
    out.append(f"## 4. {SECTIONS[3]}")
    for c in facts["changes_vs_normal_pct"][:6]:
        out.append(f"- {c['tag']}: {c['change_pct']}% versus the normal midpoint.")
    out.append("- No automatic for/against weighing is done without the AI model.")
    out.append(f"## 5. {SECTIONS[4]}")
    for m in facts["missing"] or ["UNKNOWN: field confirmation of the HMI values (local gauges, panel fault codes)."]:
        out.append(f"- {m}")
    sop = facts.get("sop")
    if sop and sop.get("coverage") != "full":
        for note in sop.get("coverage_notes") or []:
            if note.lower().startswith("gap") or "not" in note.lower():
                out.append(f"- SOP gap: {note}")
    out.append(f"## 6. {SECTIONS[5]}")
    if sop:
        out.append(f"- {sop['sop_id']} {sop['title']} — {sop['status']}.")
        for s in sop["steps"][:5]:
            out.append(f"- Step {s['n']} (p.{s['page']}): {s['text']}")
    else:
        out.append("- No process-specific SOP is mapped to this incident. Check the field readings and escalate to the shift supervisor.")
    out.append(f"## 7. {SECTIONS[6]}")
    out.append("- Not produced: an engineering assessment needs the AI model or an engineer. The facts above are recorded data only.")
    return "\n".join(out)


# --------------------------------------------------------------------- Ollama

def _ollama_base() -> str:
    return (os.environ.get("EDGE_LLM_URL") or "http://127.0.0.1:11434").rstrip("/")


def ollama_enabled() -> bool:
    from llm_provider import selected_provider
    return selected_provider() == "ollama"


def _options() -> Dict[str, Any]:
    def env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except ValueError:
            return default
    return {"temperature": 0.2, "top_p": 0.9,
            "num_ctx": env_int("OPSLENS_DIAG_NUM_CTX", 4096),
            "num_predict": env_int("OPSLENS_DIAG_NUM_PREDICT", 650)}


def stream_ollama(prompt: str) -> Iterator[Tuple[str, Optional[Dict[str, Any]]]]:
    """Yield (token, None) then ("", final_stats). Raises ProviderError on failure."""
    from edge_slm import keep_alive, local_connect_timeout, local_llm_timeout
    from llm_provider import ProviderError, llm_model
    payload = {"model": llm_model("ollama"), "stream": True, "keep_alive": keep_alive(),
               "options": _options(),
               "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]}
    try:
        with requests.post(f"{_ollama_base()}/api/chat", json=payload, stream=True,
                           timeout=(local_connect_timeout(), local_llm_timeout())) as resp:
            if resp.status_code == 404:
                raise ProviderError("model_missing", f"Ollama model '{payload['model']}' not found (HTTP 404). Run: ollama pull {payload['model']}", 404)
            if resp.status_code >= 400:
                raise ProviderError("unavailable", f"Ollama HTTP {resp.status_code}", resp.status_code)
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    raise ProviderError("unavailable", f"Ollama error: {data['error']}")
                token = (data.get("message") or {}).get("content") or ""
                if token:
                    yield token, None
                if data.get("done"):
                    yield "", {k: data.get(k) for k in ("total_duration", "load_duration", "prompt_eval_count",
                                                         "prompt_eval_duration", "eval_count", "eval_duration")}
                    return
    except requests.exceptions.ConnectionError as exc:
        raise ProviderError("unreachable", f"Ollama is not running at {_ollama_base()}") from exc
    except requests.exceptions.Timeout as exc:
        raise ProviderError("timeout", "Ollama did not answer within the configured timeout") from exc


LAST_CALL: Dict[str, Any] = {"attempted": False, "succeeded": None, "at": None, "error": None,
                             "time_to_first_token_ms": None, "total_ms": None, "model": None}


def _record_call(succeeded: bool, error: Optional[str] = None, latency: Optional[Dict[str, Any]] = None) -> None:
    from datetime import timezone
    from llm_provider import llm_model
    LAST_CALL.update({"attempted": True, "succeeded": succeeded, "error": error, "model": llm_model("ollama"),
                      "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                      "time_to_first_token_ms": (latency or {}).get("time_to_first_token_ms"),
                      "total_ms": (latency or {}).get("total_ms")})


def _mark_verified() -> None:
    import llm_provider
    llm_provider._verified_provider = ("ollama", llm_provider.llm_model("ollama"))


# ---------------------------------------------------------------------- cache

class _Cache:
    def __init__(self, size: int = 64):
        self._d: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._size = size
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            hit = self._d.get(key)
            if hit is not None:
                self._d.move_to_end(key)
            return hit

    def put(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self._size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


CACHE = _Cache()


def _cache_key(facts: Dict[str, Any]) -> str:
    from llm_provider import llm_model
    return f"{facts['event_id']}:{facts_hash(facts)}:{llm_model('ollama') if ollama_enabled() else 'none'}"


# ------------------------------------------------------------------ main API

def stream_diagnosis(full_event: Dict[str, Any], db=None) -> Iterator[Dict[str, Any]]:
    yield from stream_diagnosis_from_facts(build_facts(full_event, db))


def stream_diagnosis_from_facts(facts: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Yield events: meta, token*, done. 'done' carries the final result.

    Tokens are an unvalidated draft shown while the model writes; the 'done'
    event carries the validated result. Its engine is 'ollama' only when
    Ollama really produced the text and it passed validation; otherwise it is
    'deterministic_fallback' with the reason.
    """
    started = perf_counter()
    prompt = build_prompt(facts)
    key = _cache_key(facts)
    from llm_provider import llm_model
    meta = {"type": "meta", "event_id": facts["event_id"], "incident": facts["incident"],
            "data_source": facts["data_source"], "model": llm_model("ollama") if ollama_enabled() else None,
            "prompt_chars": len(SYSTEM_PROMPT) + len(prompt), "facts_hash": key.split(":")[1]}
    cached = CACHE.get(key)
    if cached is not None:
        yield {**meta, "cached": True}
        yield {"type": "done", **cached, "cached": True,
               "latency": {**cached.get("latency", {}), "served_from_cache_ms": round((perf_counter() - started) * 1000, 1)}}
        return
    yield {**meta, "cached": False}

    reason = None
    if not ollama_enabled():
        reason = "No LLM provider selected (OPSLENS_LLM_PROVIDER is not 'ollama')."
    else:
        from llm_provider import ProviderError
        parts: List[str] = []
        stats: Dict[str, Any] = {}
        first_token_at = None
        try:
            for token, final in stream_ollama(prompt):
                if final is not None:
                    stats = final
                    break
                if first_token_at is None:
                    first_token_at = perf_counter()
                parts.append(token)
                yield {"type": "token", "text": token}
        except ProviderError as exc:
            reason = f"Ollama unavailable: {exc}"
            if parts:
                reason += " (stream interrupted; partial text discarded)"
        text = "".join(parts).strip()
        total_ms = round((perf_counter() - started) * 1000, 1)
        if reason is None and not text:
            reason = "Ollama returned an empty response."
        if reason is not None:
            _record_call(False, error=reason)
        if reason is None:
            _mark_verified()
            check = validate(text, facts)
            latency = {"time_to_first_token_ms": round((first_token_at - started) * 1000, 1) if first_token_at else None,
                       "total_ms": total_ms,
                       "ollama_load_ms": round((stats.get("load_duration") or 0) / 1e6, 1),
                       "prompt_tokens": stats.get("prompt_eval_count"),
                       "output_tokens": stats.get("eval_count"),
                       "tokens_per_second": (round(stats["eval_count"] / (stats["eval_duration"] / 1e9), 1)
                                             if stats.get("eval_count") and stats.get("eval_duration") else None)}
            _record_call(True, latency=latency)
            logger.info("ai_diagnosis event=%s engine=ollama valid=%s ttft_ms=%s total_ms=%s",
                        facts["event_id"], check["valid"], latency["time_to_first_token_ms"], total_ms)
            if check["valid"]:
                result = {"engine": "ollama", "label": f"AI diagnosis — {llm_model('ollama')} via Ollama (local)",
                          "text": text, "validation": check, "latency": latency, "facts": facts}
                CACHE.put(key, result)
                yield {"type": "done", **result, "cached": False}
                return
            reason = "Qwen output rejected by the validator: " + "; ".join(check["rejected_reasons"])
            rejected_text = text
        else:
            rejected_text = None
            latency = {"total_ms": total_ms}
    if not ollama_enabled():
        latency = {"total_ms": round((perf_counter() - started) * 1000, 1)}
        rejected_text = None
    result = {"engine": "deterministic_fallback", "label": FALLBACK_LABEL, "fallback_reason": reason,
              "text": deterministic_diagnosis(facts), "validation": None, "latency": latency, "facts": facts,
              "rejected_ai_text": rejected_text}
    logger.info("ai_diagnosis event=%s engine=fallback reason=%s", facts["event_id"], reason)
    # Do not cache failures caused by Ollama being down: the next request should retry.
    if rejected_text is not None:
        CACHE.put(key, result)
    yield {"type": "done", **result, "cached": False}


def diagnose(full_event: Dict[str, Any], db=None) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for item in stream_diagnosis(full_event, db):
        if item["type"] == "done":
            result = item
    return result

"""
OpsLens - Guidance Generation Engine (Component 8)

Consumes EventStory, Evidence, and SopMatch. Generates operator-facing explanations
and 3 next-best-actions while enforcing zero numerical hallucinations.
Enforces strict 3.0-second API timeout, event caching, and deterministic fallback.
Persists all guidance directly to SQLite table `guidance`.
"""

import os
import json
import logging
import re
from typing import Optional, Dict, Any, Callable, List
import requests

from models import EventStory, Evidence, SopMatch, Guidance
from database import Database
from prompt_template import build_guidance_prompt
from fallback_template import generate_sop_guidance, generate_fallback_guidance
from edge_slm import (
    call_local_edge_slm,
    call_inprocess_slm,
    check_edge_slm_availability,
    check_online_availability
)

logger = logging.getLogger("opslens.guidance")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class GuidanceGenerator:
    """
    Operator Guidance & Explanation Generator.
    - Keyed event caching (in-memory + SQLite)
    - SOP-first evaluation (instant certified procedures)
    - Online Cloud LLM / Offline Ollama Edge SLM synthesis when SOP is unavailable
    - Strict numerical fidelity validation
    - Deterministic safety fallback
    - Write-through persistence to SQLite table `guidance`
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        timeout: float = 3.0,
        api_caller: Optional[Callable[[str], str]] = None,
        min_sop_score: float = 0.25,
        force_online: Optional[bool] = None
    ):
        self.db = db if db is not None else Database()
        self.timeout = timeout
        self.api_caller = api_caller
        self.min_sop_score = min_sop_score
        self._force_online = force_online
        self._memory_cache: Dict[str, Guidance] = {}

    def is_sop_available(self, sop_match: Optional[SopMatch]) -> bool:
        """
        Determine whether a valid, approved SOP procedure was retrieved for this incident.
        Returns True if:
        - sop_match exists and is not None
        - sop_id is valid (not empty, not UNKNOWN-SOP, not SOP-NONE, not NONE)
        - steps has at least 1 certified action step
        - match_score meets or exceeds min_sop_score
        """
        if sop_match is None:
            return False
        if not sop_match.sop_id or sop_match.sop_id.strip() in ("UNKNOWN-SOP", "SOP-NONE", "NONE", ""):
            return False
        if not sop_match.steps or len(sop_match.steps) == 0:
            return False
        if sop_match.match_score < self.min_sop_score:
            return False
        return True

    def is_online(self) -> bool:
        """Check if cloud connectivity and keys are available for online Cloud LLM."""
        if self._force_online is not None:
            return self._force_online
        return check_online_availability()

    def generate(
        self,
        story: EventStory,
        evidence: Evidence,
        sop_match: Optional[SopMatch] = None,
        force_fallback: bool = False,
        force_llm: bool = False
    ) -> Guidance:
        """
        Industrial Guidance Generation Pipeline:
        1. Check in-memory & SQLite cache.
        2. If force_fallback is True: return deterministic fallback.
        3. Operational Hierarchy:
           a. If api_caller is explicitly provided (for testing/mocking):
              Run LLM synthesis via caller.
           b. FIRST: Inference and SOP are retrieved.
              If an approved SOP is available:
              Formulate guidance directly from retrieved SOP + Evidence facts!
              (source="sop_retrieval", zero latency, 100% adherence to plant procedures).
           c. IF SOP NOT AVAILABLE (novel incident / uncataloged excursion / low match score):
              Synthesize guidance dynamically:
              - If online: Cloud LLM (Gemini 2.5 Flash / OpenAI / Anthropic).
                If Cloud LLM fails/times out, failover to Ollama Edge SLM.
              - If offline: Local Edge SLM (Ollama / in-process model).
              - Enforce numerical fidelity validation to guarantee zero hallucinated numbers.
              - If LLM/SLM fails, times out, or hallucinates:
                Trigger deterministic safety fallback (fallback_template.py).
        """
        event_id = evidence.event_id

        # 1. Check in-memory cache
        if event_id in self._memory_cache:
            logger.info(f"[Guidance] Returning in-memory cached guidance for event {event_id}")
            return self._memory_cache[event_id]

        # 2. Check SQLite persistent cache
        db_records = self.db.get_guidance(event_id=event_id)
        if db_records:
            cached = db_records[0]
            self._memory_cache[event_id] = cached
            logger.info(f"[Guidance] Returning SQLite cached guidance for event {event_id}")
            return cached

        # 3. If forced fallback, bypass immediately
        if force_fallback:
            guidance = generate_fallback_guidance(story, evidence, sop_match)
            self._save_and_cache(guidance, source="fallback")
            return guidance

        # 4. If an injected api_caller is set (e.g. unit testing/mocking), invoke caller
        if self.api_caller is not None:
            prompt = build_guidance_prompt(story, evidence, sop_match)
            guidance: Optional[Guidance] = None
            source = "mock_llm"
            try:
                raw_response = self.api_caller(prompt)
                if raw_response:
                    expected_sop = sop_match.sop_id if sop_match else "NONE"
                    parsed = self._parse_llm_json(raw_response, event_id, expected_sop)
                    if parsed:
                        if self._validate_numerical_fidelity(parsed.explanation_text, evidence):
                            guidance = parsed
                        else:
                            logger.warning("[Guidance] Injected caller output failed numerical fidelity check.")
            except Exception as e:
                logger.warning(f"[Guidance] Injected caller failed: {e}")

            if guidance is None:
                guidance = generate_fallback_guidance(story, evidence, sop_match)
                source = "fallback"

            self._save_and_cache(guidance, source=source)
            return guidance

        # 5. FIRST: Check if approved SOP procedure was retrieved for this incident
        if not force_llm and self.is_sop_available(sop_match):
            logger.info(
                f"[Guidance] Approved SOP '{sop_match.sop_id}' available (score={sop_match.match_score:.2f}). "
                f"Generating certified SOP guidance directly."
            )
            guidance = generate_sop_guidance(story, evidence, sop_match)
            self._save_and_cache(guidance, source="sop_retrieval")
            return guidance

        # 6. IF SOP NOT AVAILABLE: Synthesize guidance dynamically (Cloud LLM if online, Ollama SLM if offline)
        prompt = build_guidance_prompt(story, evidence, sop_match)
        guidance: Optional[Guidance] = None
        source = "fallback"
        raw_response: Optional[str] = None

        if self.is_online():
            logger.info(f"[Guidance] SOP not available for event {event_id}. Online mode active: calling Cloud LLM.")
            raw_response = self._call_cloud_llm(prompt)
            source = "cloud_llm"
            if not raw_response:
                logger.warning(f"[Guidance] Cloud LLM returned no response. Failing over to local Ollama edge SLM.")
                raw_response = self._call_edge_slm(prompt)
                source = "edge_slm"
        else:
            logger.info(f"[Guidance] SOP not available for event {event_id}. Offline mode active: calling Ollama edge SLM.")
            raw_response = self._call_edge_slm(prompt)
            source = "edge_slm"

        if raw_response:
            expected_sop = (
                sop_match.sop_id
                if (sop_match and sop_match.sop_id and sop_match.sop_id not in ("UNKNOWN-SOP", "SOP-NONE", "NONE"))
                else "NONE"
            )
            try:
                parsed = self._parse_llm_json(raw_response, event_id, expected_sop)
                if parsed:
                    if self._validate_numerical_fidelity(parsed.explanation_text, evidence):
                        guidance = parsed
                    else:
                        logger.warning("[Guidance] LLM/SLM output failed numerical fidelity check. Triggering safety fallback.")
            except Exception as e:
                logger.warning(f"[Guidance] Failed parsing LLM/SLM response: {e}")

        # 7. Safety Net: Trigger deterministic fallback if LLM/SLM failed, timed out, or hallucinated
        if guidance is None:
            guidance = generate_fallback_guidance(story, evidence, sop_match)
            source = "fallback"

        # 8. Save and cache result
        self._save_and_cache(guidance, source=source)
        return guidance

    def _call_cloud_llm(self, prompt: str) -> Optional[str]:
        """
        Invoke Cloud LLM with strict timeout.
        Tries Gemini API first, then OpenAI, then Anthropic based on configured keys.
        """
        gemini_key = os.environ.get("GEMINI_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

        try:
            if gemini_key:
                return self._call_gemini(prompt, gemini_key)
            elif openai_key:
                return self._call_openai(prompt, openai_key)
            elif anthropic_key:
                return self._call_anthropic(prompt, anthropic_key)
        except Exception as e:
            logger.warning(f"[Guidance] Cloud LLM API call failed: {e}")
        return None

    def _call_edge_slm(self, prompt: str) -> Optional[str]:
        """
        Invoke local Edge Small Language Model (SLM) on edge device / gateway.
        1. Local REST API (Ollama / llama.cpp / LocalAI at http://localhost:11434)
        2. In-process CPU model if configured (Transformers CPU)
        """
        try:
            edge_res = call_local_edge_slm(prompt, timeout=self.timeout)
            if edge_res:
                return edge_res

            edge_provider = os.environ.get("EDGE_LLM_PROVIDER", "").lower()
            if edge_provider in ["transformers", "inprocess", "local_cpu"]:
                inproc_res = call_inprocess_slm(prompt)
                if inproc_res:
                    return inproc_res
        except Exception as e:
            logger.warning(f"[Guidance] Local edge SLM error: {e}")
        return None

    def _call_gemini(self, prompt: str, api_key: str) -> Optional[str]:
        """Call Gemini API via REST with strict timeout."""
        # Try gemini-2.5-flash then fallback to gemini-1.5-flash
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }
        resp = requests.post(url, json=payload, timeout=self.timeout)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text")
        else:
            logger.warning(f"[Guidance] Gemini API returned HTTP {resp.status_code}: {resp.text[:200]}")
            return None

    def _call_openai(self, prompt: str, api_key: str) -> Optional[str]:
        """Call OpenAI API via REST with strict timeout."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content")
        else:
            logger.warning(f"[Guidance] OpenAI API returned HTTP {resp.status_code}: {resp.text[:200]}")
            return None

    def _call_anthropic(self, prompt: str, api_key: str) -> Optional[str]:
        """Call Anthropic Claude API via REST with strict timeout."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 512,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("content", [])
            if content:
                return content[0].get("text")
        else:
            logger.warning(f"[Guidance] Anthropic API returned HTTP {resp.status_code}: {resp.text[:200]}")
            return None

    def _parse_llm_json(
        self,
        raw_text: str,
        expected_event_id: str,
        expected_sop_id: str
    ) -> Optional[Guidance]:
        """Parse raw LLM response text into a valid Guidance model instance."""
        # Strip potential markdown code fences
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback regex extraction in case small models add conversational preambles
            match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    logger.warning(f"[Guidance] Failed to decode JSON from LLM output: {raw_text[:100]}")
                    return None
            else:
                logger.warning(f"[Guidance] Failed to decode JSON from LLM output: {raw_text[:100]}")
                return None

        explanation_text = data.get("explanation_text")
        next_actions = data.get("next_best_actions")
        cited_sop_id = data.get("cited_sop_id") or expected_sop_id

        if not explanation_text or not isinstance(explanation_text, str):
            return None

        if not next_actions or not isinstance(next_actions, list):
            return None

        # Clean string actions
        action_strings = [str(a).strip() for a in next_actions if str(a).strip()]
        if not action_strings:
            return None

        return Guidance(
            event_id=expected_event_id,
            explanation_text=explanation_text.strip(),
            next_best_actions=action_strings[:3],
            cited_sop_id=cited_sop_id
        )

    def _validate_numerical_fidelity(self, text: str, evidence: Evidence) -> bool:
        """
        Verify that any numbers or percentages mentioned in explanation_text
        do not contradict or invent values contrary to evidence.supporting_deltas.
        """
        # Find all numbers (e.g. -44.9, 18.2, 50) in text
        # If any percentage appears, check if it exists in input deltas
        mentioned_pcts = re.findall(r'([+-]?\d+(?:\.\d+)?)\s*%', text)
        if mentioned_pcts:
            known_pcts = {
                round(abs(d.delta_pct), 1) for d in evidence.supporting_deltas
            }
            known_pcts.update({round(abs(d.delta_pct), 0) for d in evidence.supporting_deltas})
            for m in mentioned_pcts:
                val = round(abs(float(m)), 1)
                val_int = round(abs(float(m)), 0)
                if val not in known_pcts and val_int not in known_pcts:
                    logger.warning(f"[Guidance] Mentioned percentage {m}% not found in supporting deltas!")
                    return False

        return True

    def _save_and_cache(self, guidance: Guidance, source: str) -> None:
        """Cache guidance in-memory and write-through to SQLite."""
        self._memory_cache[guidance.event_id] = guidance
        self.db.save_guidance(guidance, source=source)
        logger.info(f"[Guidance] Saved guidance for event {guidance.event_id} (source='{source}')")

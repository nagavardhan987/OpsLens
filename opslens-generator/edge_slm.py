"""
OpsLens - Edge Small Language Model (SLM) Client

Designed for low-power industrial edge devices (e.g. Schneider Electric Harmony iPC,
Raspberry Pi 5, Intel Celeron/Atom/NUC edge gateways, NVIDIA Jetson).

Capabilities:
1. Local Edge Inference Service (Ollama / llama.cpp / LocalAI / vLLM):
   Connects via low-latency local REST API with zero cloud dependency.
   Supports compact models: qwen2.5:0.5b, gemma:2b, phi3:mini, tinyllama.
2. In-Process Lightweight SLM (Transformers CPU):
   Runs compact instruction models (e.g. Qwen2.5-0.5B-Instruct or SmolLM-360M)
   directly in Python using PyTorch CPU with <800MB RAM footprint.
3. Fast availability probing (<=0.5s) to seamlessly fall back to deterministic
   templates without introducing UI lag.
"""

import os
import json
import logging
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger("opslens.edge_slm")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Default environment configuration
DEFAULT_EDGE_URL = os.environ.get("EDGE_LLM_URL", "http://localhost:11434")
DEFAULT_EDGE_MODEL = os.environ.get("EDGE_LLM_MODEL", "qwen2.5:0.5b")
DEFAULT_TIMEOUT = float(os.environ.get("EDGE_LLM_TIMEOUT", "3.0"))

# Global handle for lazy-loaded in-process SLM pipeline
_inprocess_pipeline = None


def check_edge_slm_availability(url: Optional[str] = None, timeout: float = 0.5) -> bool:
    """
    Fast, non-blocking check to determine if a local edge SLM server is reachable.
    Checks Ollama /tags or standard root endpoint within timeout (default 500ms).
    """
    base_url = (url or DEFAULT_EDGE_URL).rstrip("/")
    try:
        # Check Ollama tags or standard root
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout)
        if resp.status_code == 200:
            return True
    except Exception:
        pass

    try:
        # Check OpenAI-compatible /v1/models or root
        resp = requests.get(f"{base_url}/v1/models", timeout=timeout)
        if resp.status_code == 200:
            return True
    except Exception:
        pass

def check_online_availability(timeout: float = 0.5) -> bool:
    """
    Fast check to determine if the system is operating online with cloud LLM connectivity.
    Returns False if OPSLENS_OFFLINE is set, no API keys are present, or internet is unreachable.
    """
    if os.environ.get("OPSLENS_OFFLINE", "false").lower() in ("true", "1", "yes"):
        return False

    has_cloud_key = bool(
        os.environ.get("GEMINI_API_KEY") or
        os.environ.get("OPENAI_API_KEY") or
        os.environ.get("ANTHROPIC_API_KEY")
    )
    if not has_cloud_key:
        return False

    # Fast network probe to confirm cloud reachability
    try:
        resp = requests.head("https://generativelanguage.googleapis.com", timeout=timeout)
        return resp.status_code < 500
    except Exception:
        try:
            resp = requests.head("https://www.google.com", timeout=timeout)
            return resp.status_code < 500
        except Exception:
            return False


def call_local_edge_slm(
    prompt: str,
    url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None
) -> Optional[str]:
    """
    Call a local edge SLM inference server (Ollama, llama.cpp, LocalAI).
    Tries Ollama native JSON format first, then OpenAI-compatible /v1/chat/completions.

    Returns the raw generated text/JSON string, or None if unavailable/failed.
    """
    base_url = (url or DEFAULT_EDGE_URL).rstrip("/")
    model_name = model or DEFAULT_EDGE_MODEL
    req_timeout = timeout or DEFAULT_TIMEOUT

    # 1. Try Ollama native REST API with format="json"
    ollama_url = f"{base_url}/api/generate"
    try:
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": 256
            }
        }
        resp = requests.post(ollama_url, json=payload, timeout=req_timeout)
        if resp.status_code == 200:
            data = resp.json()
            response_text = data.get("response")
            if response_text:
                logger.info(f"[EdgeSLM] Received response from local Ollama model '{model_name}'")
                return response_text
    except requests.exceptions.ConnectionError:
        # Expected when Ollama is not running locally
        pass
    except Exception as e:
        logger.debug(f"[EdgeSLM] Ollama endpoint failed: {e}")

    # 2. Try OpenAI-compatible /v1/chat/completions (llama.cpp server, vLLM, LocalAI)
    v1_url = f"{base_url}/v1/chat/completions"
    try:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 256,
            "response_format": {"type": "json_object"}
        }
        resp = requests.post(v1_url, json=payload, timeout=req_timeout)
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content")
                if content:
                    logger.info(f"[EdgeSLM] Received response from OpenAI-compatible edge server '{model_name}'")
                    return content
    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        logger.debug(f"[EdgeSLM] /v1 endpoint failed: {e}")

    return None


def call_inprocess_slm(
    prompt: str,
    model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
    max_new_tokens: int = 256
) -> Optional[str]:
    """
    Run lightweight SLM in-process using Hugging Face transformers.
    Optimized for low-power edge devices with pure CPU inference.
    """
    global _inprocess_pipeline
    try:
        if _inprocess_pipeline is None:
            import torch
            from transformers import pipeline

            logger.info(f"[EdgeSLM] Initializing in-process lightweight SLM '{model_name}' on CPU...")
            _inprocess_pipeline = pipeline(
                "text-generation",
                model=model_name,
                torch_dtype=torch.float32,
                device="cpu",
                model_kwargs={"low_cpu_mem_usage": True}
            )

        messages = [
            {"role": "system", "content": "You are an industrial copilot. Output raw JSON only."},
            {"role": "user", "content": prompt}
        ]

        outputs = _inprocess_pipeline(
            messages,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            do_sample=False
        )

        if outputs and len(outputs) > 0:
            generated = outputs[0].get("generated_text", [])
            if isinstance(generated, list) and len(generated) > 0:
                last_msg = generated[-1]
                return last_msg.get("content", "")
            elif isinstance(generated, str):
                return generated
    except Exception as e:
        logger.warning(f"[EdgeSLM] In-process SLM inference failed: {e}")

    return None

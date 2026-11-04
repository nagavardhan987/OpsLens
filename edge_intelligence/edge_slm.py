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
DEFAULT_EDGE_MODEL = os.environ.get("EDGE_LLM_MODEL", "qwen2.5:3b")
DEFAULT_TIMEOUT = float(os.environ.get("EDGE_LLM_TIMEOUT", "60"))

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


def _edge_url(url: Optional[str] = None) -> str:
    return (url or os.environ.get("EDGE_LLM_URL") or DEFAULT_EDGE_URL).rstrip("/")


def _edge_model(model: Optional[str] = None) -> str:
    return model or os.environ.get("OPSLENS_LLM_MODEL") or os.environ.get("EDGE_LLM_MODEL") or DEFAULT_EDGE_MODEL


def local_llm_timeout() -> float:
    """Read timeout for a local model. CPU inference of a 3B model, including a
    cold model load, routinely takes 10-60 s; a 3-6 s budget always times out."""
    value = (os.environ.get("OPSLENS_OLLAMA_TIMEOUT") or os.environ.get("EDGE_LLM_TIMEOUT")
             or os.environ.get("OPSLENS_LLM_TIMEOUT") or "60")
    try:
        return max(1.0, float(value))
    except ValueError:
        return 60.0


def local_connect_timeout() -> float:
    try:
        return max(0.2, float(os.environ.get("OPSLENS_OLLAMA_CONNECT_TIMEOUT", "2")))
    except ValueError:
        return 2.0


def keep_alive() -> str:
    return os.environ.get("OPSLENS_OLLAMA_KEEP_ALIVE", "30m")


def ollama_health(url: Optional[str] = None, timeout: float = 1.5) -> Dict[str, Any]:
    """Report whether Ollama is reachable and the configured model is installed.
    Never raises; used by /api/copilot/health and the UI status pill."""
    base_url = _edge_url(url)
    model_name = _edge_model()
    result: Dict[str, Any] = {"url": base_url, "model": model_name, "reachable": False,
                              "model_installed": False, "models": [], "error": None}
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=timeout)
        result["reachable"] = resp.status_code == 200
        if resp.status_code == 200:
            names = [m.get("name") or m.get("model") for m in (resp.json().get("models") or [])]
            result["models"] = [n for n in names if n]
            wanted = model_name if ":" in model_name else f"{model_name}:latest"
            result["model_installed"] = any(n in (model_name, wanted) for n in result["models"])
            if not result["model_installed"]:
                result["error"] = f"Model '{model_name}' is not installed. Run: ollama pull {model_name}"
        else:
            result["error"] = f"Ollama returned HTTP {resp.status_code}"
    except requests.exceptions.ConnectionError:
        result["error"] = f"Ollama is not running at {base_url}. Start it with: ollama serve"
    except requests.exceptions.Timeout:
        result["error"] = "Ollama did not answer the health check in time."
    except Exception as exc:  # pragma: no cover - defensive
        result["error"] = type(exc).__name__
    return result


def warm_up_ollama(url: Optional[str] = None) -> Dict[str, Any]:
    """Load the model into memory (empty prompt) so the first operator question
    is not spent on a cold start. Safe to call when Ollama is absent."""
    base_url = _edge_url(url)
    model_name = _edge_model()
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={"model": model_name, "prompt": "", "keep_alive": keep_alive(), "stream": False},
            timeout=(local_connect_timeout(), local_llm_timeout()),
        )
        return {"model": model_name, "loaded": resp.status_code == 200, "http_status": resp.status_code}
    except requests.exceptions.RequestException as exc:
        return {"model": model_name, "loaded": False, "error": type(exc).__name__}


def call_local_edge_slm(
    prompt: str,
    url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None
) -> Optional[str]:
    """
    Call a local edge SLM inference server (Ollama, llama.cpp, LocalAI).
    Tries Ollama native JSON format first. The OpenAI-compatible
    /v1/chat/completions route is tried only when the native route does not
    exist (HTTP 404) - never after a timeout or refused connection, which
    would otherwise double the operator's wait for the same failure.

    Returns the raw generated text/JSON string, or None if unavailable/failed.
    Timeouts are re-raised so the caller can report them precisely.
    """
    base_url = _edge_url(url)
    model_name = _edge_model(model)
    read_timeout = timeout or local_llm_timeout()
    req_timeout = (local_connect_timeout(), read_timeout)

    ollama_url = f"{base_url}/api/generate"
    try:
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": keep_alive(),
            "options": {
                "temperature": 0.1,
                "num_predict": int(os.environ.get("OPSLENS_OLLAMA_NUM_PREDICT", "320")),
            }
        }
        resp = requests.post(ollama_url, json=payload, timeout=req_timeout)
        if resp.status_code == 200:
            response_text = resp.json().get("response")
            if response_text:
                logger.info(f"[EdgeSLM] Received response from local Ollama model '{model_name}'")
                return response_text
            return None
        if resp.status_code != 404:
            logger.warning("[EdgeSLM] Ollama returned HTTP %s for model '%s'", resp.status_code, model_name)
            return None
    except requests.exceptions.Timeout:
        logger.warning("[EdgeSLM] Ollama model '%s' exceeded %.0fs read timeout (OPSLENS_OLLAMA_TIMEOUT)", model_name, read_timeout)
        raise
    except requests.exceptions.ConnectionError:
        logger.info("[EdgeSLM] Ollama not reachable at %s; using deterministic output", base_url)
        return None
    except Exception as e:
        logger.debug(f"[EdgeSLM] Ollama endpoint failed: {e}")
        return None

    # Native route missing (HTTP 404): try an OpenAI-compatible local server.
    v1_url = f"{base_url}/v1/chat/completions"
    try:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 320,
            "response_format": {"type": "json_object"}
        }
        resp = requests.post(v1_url, json=payload, timeout=req_timeout)
        if resp.status_code == 200:
            choices = resp.json().get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content")
                if content:
                    logger.info(f"[EdgeSLM] Received response from OpenAI-compatible edge server '{model_name}'")
                    return content
    except requests.exceptions.Timeout:
        raise
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

"""Configurable assistant LLM/SLM provider with deterministic fallback.

Secrets stay in environment variables. Keys are never logged or returned.
A provider is reported as verified only after a successful model call.
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any, Dict, Iterator, Optional

import requests

from edge_slm import call_inprocess_slm, call_local_edge_slm

logger = logging.getLogger("opslens.llm_provider")
_PROVIDER_CONCURRENCY = max(1, int(os.environ.get("OPSLENS_LLM_MAX_CONCURRENCY", "3")))
_PROVIDER_SLOTS = threading.BoundedSemaphore(_PROVIDER_CONCURRENCY)

_verified_provider: Optional[tuple[str, str]] = None
_provider_request_context: ContextVar[tuple[str, str]] = ContextVar(
    "opslens_provider_request_context", default=("untracked", "inference")
)
_provider_http_status: ContextVar[Optional[int]] = ContextVar(
    "opslens_provider_http_status", default=None
)


def set_provider_request_context(request_id: str, call_type: str) -> Token:
    """Attach safe correlation metadata to provider logs for this call only."""
    return _provider_request_context.set((request_id, call_type))


def reset_provider_request_context(token: Token) -> None:
    _provider_request_context.reset(token)
    _provider_http_status.set(None)


def clear_provider_http_status() -> None:
    _provider_http_status.set(None)


def get_provider_http_status() -> Optional[int]:
    return _provider_http_status.get()


def _record_provider_http_status(status_code: int) -> None:
    _provider_http_status.set(int(status_code))


class ProviderError(RuntimeError):
    def __init__(self, kind: str, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


def selected_provider() -> str:
    explicit = (os.environ.get("OPSLENS_LLM_PROVIDER") or "none").strip().lower()
    if os.environ.get("OPSLENS_OFFLINE", "false").lower() in ("true", "1", "yes"):
        return "none"
    return explicit or "none"


LOCAL_PROVIDERS = ("ollama", "openai_compatible", "transformers", "inprocess", "local_cpu")


def llm_timeout(provider: Optional[str] = None) -> float:
    """Provider-aware request timeout in seconds.

    Cloud APIs answer in a few seconds, so a short budget keeps the operator
    moving to the deterministic answer. A local CPU model (e.g. qwen2.5:3b in
    Ollama) needs far longer, especially on its first request while the model
    loads; the previous 4 s default made every local call time out.
    OPSLENS_OLLAMA_TIMEOUT (local) and OPSLENS_LLM_TIMEOUT (cloud) override.
    """
    provider = provider or selected_provider()
    if provider in LOCAL_PROVIDERS:
        from edge_slm import local_llm_timeout
        return local_llm_timeout()
    try:
        return float(os.environ.get("OPSLENS_LLM_TIMEOUT") or "8.0")
    except ValueError:
        return 8.0


def llm_model(provider: Optional[str] = None) -> str:
    provider = provider or selected_provider()
    env_model = os.environ.get("OPSLENS_LLM_MODEL") or os.environ.get("EDGE_LLM_MODEL")
    if env_model:
        return env_model
    return {
        "groq": "openai/gpt-oss-20b",
        "gemini": "gemini-2.5-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20240307",
        "ollama": os.environ.get("EDGE_LLM_MODEL", "qwen2.5:3b"),
        "openai_compatible": os.environ.get("EDGE_LLM_MODEL", "gpt-4o-mini"),
        "transformers": os.environ.get("EDGE_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
        "inprocess": os.environ.get("EDGE_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
    }.get(provider, "unconfigured")


def provider_status() -> Dict[str, Any]:
    provider = selected_provider()
    selected = provider not in ("", "none", "off", "disabled")
    error = configuration_error()
    configured = selected and error is None
    verified = configured and _verified_provider == (provider, llm_model(provider))
    return {
        "provider": provider if selected else "none",
        "model": llm_model(provider) if selected else None,
        "selected": selected,
        "configured": configured,
        "verified": verified,
        "initialization": (
            "not_selected" if not selected else
            "missing_credentials" if error else
            "verified" if verified else "ready_not_verified"
        ),
        "configuration_error": error,
        "note": "verified is true only after a successful provider call in this process",
    }


def configuration_error() -> Optional[str]:
    provider = selected_provider()
    if provider in ("", "none", "off", "disabled"):
        return None
    if provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
        return "OPSLENS_LLM_PROVIDER=gemini but GEMINI_API_KEY is not set."
    if provider == "groq" and not (os.environ.get("GROQ_API_KEY") or "").strip():
        return "OPSLENS_LLM_PROVIDER=groq but GROQ_API_KEY is not set."
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        return "OPSLENS_LLM_PROVIDER=openai but OPENAI_API_KEY is not set."
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        return "OPSLENS_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set."
    supported = {
        "gemini", "groq", "openai", "anthropic", "ollama", "openai_compatible",
        "transformers", "inprocess", "local_cpu",
    }
    if provider not in supported:
        return f"Unknown OPSLENS_LLM_PROVIDER '{provider}'."
    if provider in ("transformers", "inprocess") and (os.environ.get("EDGE_LLM_PROVIDER", provider).lower() not in ("transformers", "inprocess", "local_cpu")):
        return None
    return None


def complete_chat(prompt: str, timeout: Optional[float] = None) -> str:
    """Return model text or raise ProviderError. Never returns invented fallback text."""
    provider = selected_provider()
    error = configuration_error()
    if error:
        logger.warning(
            "provider_initialization provider=%s model=%s result=failed error=missing_credentials",
            provider, llm_model(provider),
        )
        raise ProviderError("configuration", error)
    if provider in ("", "none", "off", "disabled"):
        raise ProviderError("configuration", "No LLM provider is configured.")
    logger.info("provider_initialization provider=%s model=%s result=ready", provider, llm_model(provider))
    req_timeout = timeout or llm_timeout()
    started = perf_counter()
    try:
        slot_wait = max(0.0, float(os.environ.get("OPSLENS_LLM_QUEUE_TIMEOUT", "0.25")))
        if not _PROVIDER_SLOTS.acquire(timeout=slot_wait):
            raise ProviderError("busy", "LLM concurrency limit reached.")
        try:
            if provider == "gemini":
                text = _call_gemini(prompt, req_timeout)
            elif provider == "groq":
                text = _call_groq(prompt, req_timeout)
            elif provider == "openai":
                text = _call_openai(prompt, req_timeout)
            elif provider == "anthropic":
                text = _call_anthropic(prompt, req_timeout)
            elif provider in ("ollama", "openai_compatible"):
                text = call_local_edge_slm(prompt, timeout=req_timeout)
                if not text:
                    raise ProviderError("unavailable", "Local edge SLM did not return a response.")
            elif provider in ("transformers", "inprocess", "local_cpu"):
                text = call_inprocess_slm(prompt)
                if not text:
                    raise ProviderError("unavailable", "In-process SLM did not return a response.")
            else:
                raise ProviderError("configuration", f"Unknown OPSLENS_LLM_PROVIDER '{provider}'.")
        finally:
            _PROVIDER_SLOTS.release()
    except ProviderError as exc:
        logger.warning(
            "provider_inference provider=%s model=%s result=failed reason=%s http_status=%s elapsed_ms=%.3f",
            provider, llm_model(provider), exc.kind, exc.status_code,
            (perf_counter() - started) * 1000,
        )
        raise
    except requests.exceptions.Timeout as exc:
        raise ProviderError("timeout", f"{provider} request timed out") from exc
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        kind = "auth" if status in (401, 403) else "rate_limit" if status == 429 else "unavailable"
        raise ProviderError(kind, f"{provider} HTTP {status}") from exc
    except requests.exceptions.RequestException as exc:
        kind = _request_failure_kind(exc)
        logger.warning(
            "provider_transport provider=%s model=%s failure_kind=%s exception_type=%s",
            provider, llm_model(provider), kind, type(exc).__name__,
        )
        raise ProviderError(kind, f"{provider} request failed ({kind})") from exc
    except Exception as exc:
        raise ProviderError("unavailable", f"{provider} call failed") from exc
    if not text or not str(text).strip():
        exc = ProviderError("empty", f"{provider} returned an empty response.")
        logger.warning(
            "provider_inference provider=%s model=%s result=failed reason=empty http_status=200 elapsed_ms=%.3f",
            provider, llm_model(provider), (perf_counter() - started) * 1000,
        )
        raise exc
    global _verified_provider
    _verified_provider = (provider, llm_model(provider))
    logger.info(
        "provider_inference provider=%s model=%s result=success http_status=200 elapsed_ms=%.3f",
        provider, llm_model(provider), (perf_counter() - started) * 1000,
    )
    return str(text)


def stream_chat(prompt: str, timeout: Optional[float] = None) -> Iterator[str]:
    """Yield text chunks. Providers without streaming yield a single complete chunk."""
    provider = selected_provider()
    if provider == "openai":
        yield from _stream_openai(prompt, timeout or llm_timeout())
        return
    if provider == "groq":
        yield from _stream_openai_compatible(prompt, "groq", timeout or llm_timeout())
        return
    if provider == "gemini":
        yield from _stream_gemini(prompt, timeout or llm_timeout())
        return
    if provider == "anthropic":
        yield from _stream_anthropic(prompt, timeout or llm_timeout())
        return
    if provider in ("ollama", "openai_compatible"):
        yielded = False
        for chunk in _stream_ollama(prompt, timeout or llm_timeout()):
            yielded = True
            yield chunk
        if yielded:
            return
    yield complete_chat(prompt, timeout=timeout)


def _auth_failure(status: int, provider: str) -> None:
    if status in (401, 403):
        raise ProviderError("auth", f"{provider} authentication failed", status)
    if status == 429:
        raise ProviderError("rate_limit", f"{provider} rate-limited the request", status)
    if status in (408, 504):
        raise ProviderError("timeout", f"{provider} request timed out (HTTP {status})", status)
    if status == 400:
        raise ProviderError("invalid_request", f"{provider} rejected the request (HTTP 400)", status)
    if status >= 400:
        raise ProviderError("unavailable", f"{provider} HTTP {status}", status)


def _request_failure_kind(exc: requests.exceptions.RequestException) -> str:
    """Classify transport failures without logging request URLs or secrets."""
    if isinstance(exc, requests.exceptions.SSLError):
        return "tls_error"
    if isinstance(exc, requests.exceptions.ProxyError):
        return "proxy_error"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connection_timeout"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout"

    pending = [exc]
    visited = set()
    while pending:
        cause = pending.pop()
        if cause is None or id(cause) in visited:
            continue
        visited.add(id(cause))
        cause_name = type(cause).__name__.lower()
        safe_message = str(cause).lower()
        if "name resolution" in safe_message or "getaddrinfo failed" in safe_message or "no such host" in safe_message:
            return "dns_error"
        if "name resolution" in cause_name or "nameresolution" in cause_name:
            return "dns_error"
        if "ssl" in cause_name or "certificate" in safe_message:
            return "tls_error"
        pending.extend((getattr(cause, "__cause__", None), getattr(cause, "__context__", None)))
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    return "network_error"


def _call_gemini(prompt: str, timeout: float) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or ""
    model = llm_model("gemini")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    resp = requests.post(url, headers={"x-goog-api-key": api_key, "Content-Type": "application/json"}, json=payload, timeout=timeout)
    _record_provider_http_status(resp.status_code)
    _auth_failure(resp.status_code, "gemini")
    data = resp.json()
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    return (parts[0].get("text") if parts else "") or ""


def _call_openai(prompt: str, timeout: float) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    payload = {
        "model": llm_model("openai"),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    _record_provider_http_status(resp.status_code)
    _auth_failure(resp.status_code, "openai")
    choices = resp.json().get("choices") or []
    return ((choices[0].get("message") or {}).get("content") if choices else "") or ""


def _call_groq(prompt: str, timeout: float) -> str:
    api_key = os.environ.get("GROQ_API_KEY") or ""
    endpoint = os.environ.get(
        "GROQ_API_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions"
    ).strip()
    payload = {
        "model": llm_model("groq"),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    started = perf_counter()
    request_id, call_type = _provider_request_context.get()
    logger.info("provider_request request_id=%s call_type=%s provider=groq model=%s result=start", request_id, call_type, payload["model"])
    try:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        elapsed = (perf_counter() - started) * 1000
        reason = "timeout" if isinstance(exc, requests.exceptions.Timeout) else "network_error"
        logger.warning(
            "provider_request request_id=%s call_type=%s provider=groq model=%s result=failed reason=%s http_status=none elapsed_ms=%.3f",
            request_id, call_type, payload["model"], reason, elapsed,
        )
        raise
    elapsed = (perf_counter() - started) * 1000
    _record_provider_http_status(resp.status_code)
    logger.info(
        "provider_request request_id=%s call_type=%s provider=groq model=%s result=http_response http_status=%s elapsed_ms=%.3f",
        request_id, call_type, payload["model"], resp.status_code, elapsed,
    )
    if resp.status_code == 429:
        # Quota exhaustion is terminal until the account/limits change. For a
        # transient window limit, make at most one short retry and honor the
        # provider's delay only when it fits the configured latency budget.
        max_wait = max(0.0, float(os.environ.get("OPSLENS_GROQ_MAX_RETRY_WAIT", "2.5")))
        body_text = ""
        try:
            body_text = json.dumps(resp.json()).lower()
        except Exception:
            pass
        retry_after = _groq_retry_after(resp.headers or {})
        if "insufficient_quota" not in body_text and max_wait > 0 and (retry_after is None or retry_after <= max_wait):
            delay = min(max_wait, retry_after if retry_after is not None else 0.2 * (2 ** 0) + random.uniform(0.0, 0.15))
            logger.warning("provider_request request_id=%s groq_rate_limited retrying_once delay_ms=%.1f", request_id, delay * 1000)
            time.sleep(delay)
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            _record_provider_http_status(resp.status_code)
        else:
            logger.warning("provider_request request_id=%s groq_rate_limited retry_skipped reason=%s", request_id,
                           "quota_exhausted" if "insufficient_quota" in body_text else "retry_after_exceeds_budget")
    _auth_failure(resp.status_code, "groq")
    try:
        data = resp.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        message = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            reasoning = message.get("reasoning")
            if isinstance(reasoning, str) and "{" in reasoning and "}" in reasoning:
                import re
                match = re.search(r"(\{.*\})", reasoning, re.DOTALL)
                if match:
                    content = match.group(1)
    except (ValueError, TypeError, AttributeError, IndexError, KeyError):
        raise ProviderError("malformed_response", "groq returned an invalid chat-completion response.", resp.status_code)
        raise ProviderError("malformed_response", "groq returned an invalid chat-completion response.", resp.status_code)
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("malformed_response", "groq returned no text content in its chat-completion response.", resp.status_code)
    return content


def _groq_retry_after(headers: Dict[str, Any]) -> Optional[float]:
    """Read common Groq/OpenAI-compatible rate-limit timing headers."""
    for name in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = headers.get(name) or headers.get(name.title())
        if value is None:
            continue
        text = str(value).strip().lower()
        try:
            if text.endswith("ms"):
                return max(0.0, float(text[:-2]) / 1000)
            if text.endswith("s"):
                return max(0.0, float(text[:-1]))
            return max(0.0, float(text))
        except ValueError:
            continue
    return None


def _stream_openai_compatible(prompt: str, provider: str, timeout: float) -> Iterator[str]:
    """Stream chat-completion SSE from a compatible provider (Groq)."""
    global _verified_provider
    api_key = os.environ.get("GROQ_API_KEY") or ""
    endpoint = os.environ.get(
        "GROQ_API_ENDPOINT", "https://api.groq.com/openai/v1/chat/completions"
    ).strip()
    payload = {
        "model": llm_model(provider),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "stream": True,
    }
    yielded = False
    try:
        with requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
            stream=True,
        ) as resp:
            _auth_failure(resp.status_code, provider)
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = (json.loads(data).get("choices") or [{}])[0].get("delta") or {}
                except json.JSONDecodeError:
                    continue
                content = delta.get("content")
                if content:
                    yielded = True
                    yield content
    except requests.exceptions.Timeout as exc:
        raise ProviderError("timeout", f"{provider} stream timed out") from exc
    if yielded:
        _verified_provider = (provider, llm_model(provider))


def _call_anthropic(prompt: str, timeout: float) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    payload = {
        "model": llm_model("anthropic"),
        "max_tokens": 700,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    _record_provider_http_status(resp.status_code)
    _auth_failure(resp.status_code, "anthropic")
    content = resp.json().get("content") or []
    return (content[0].get("text") if content else "") or ""


def _stream_anthropic(prompt: str, timeout: float) -> Iterator[str]:
    global _verified_provider
    api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    payload = {
        "model": llm_model("anthropic"),
        "max_tokens": 700,
        "temperature": 0.1,
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
    }
    yielded = False
    try:
        with requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
            stream=True,
        ) as resp:
            _auth_failure(resp.status_code, "anthropic")
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if text:
                            yielded = True
                            yield text
    except requests.exceptions.Timeout as exc:
        raise ProviderError("timeout", "anthropic stream timed out") from exc
    if yielded:
        _verified_provider = ("anthropic", llm_model("anthropic"))


def _stream_openai(prompt: str, timeout: float) -> Iterator[str]:
    global _verified_provider
    api_key = os.environ.get("OPENAI_API_KEY") or ""
    payload = {
        "model": llm_model("openai"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "stream": True,
    }
    yielded = False
    try:
        with requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
            stream=True,
        ) as resp:
            _auth_failure(resp.status_code, "openai")
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    delta = (json.loads(data).get("choices") or [{}])[0].get("delta") or {}
                except json.JSONDecodeError:
                    continue
                content = delta.get("content")
                if content:
                    yielded = True
                    yield content
    except requests.exceptions.Timeout as exc:
        raise ProviderError("timeout", "openai stream timed out") from exc
    if yielded:
        _verified_provider = ("openai", llm_model("openai"))


def _stream_ollama(prompt: str, timeout: float) -> Iterator[str]:
    global _verified_provider
    base = (os.environ.get("EDGE_LLM_URL") or "http://localhost:11434").rstrip("/")
    from edge_slm import keep_alive, local_connect_timeout
    payload = {
        "model": llm_model("ollama"),
        "prompt": prompt,
        "stream": True,
        "keep_alive": keep_alive(),
        "options": {"temperature": 0.1, "num_predict": 400},
    }
    yielded = False
    try:
        # (connect, read): an absent Ollama fails fast; a slow first token on
        # CPU is allowed up to the configured local timeout.
        with requests.post(f"{base}/api/generate", json=payload,
                           timeout=(local_connect_timeout(), timeout), stream=True) as resp:
            if resp.status_code >= 400:
                return
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk = data.get("response")
                if chunk:
                    yielded = True
                    yield chunk
    except requests.exceptions.RequestException:
        return
    if yielded:
        provider = selected_provider()
        _verified_provider = (provider, llm_model(provider))


def _stream_gemini(prompt: str, timeout: float) -> Iterator[str]:
    global _verified_provider
    api_key = os.environ.get("GEMINI_API_KEY") or ""
    model = llm_model("gemini")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    yielded = False
    try:
        with requests.post(
            url,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
            stream=True,
        ) as resp:
            _auth_failure(resp.status_code, "gemini")
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if not data_str:
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                candidates = data.get("candidates") or []
                if candidates:
                    parts = ((candidates[0].get("content") or {}).get("parts") or [])
                    for part in parts:
                        text = part.get("text")
                        if text:
                            yielded = True
                            yield text
    except requests.exceptions.Timeout as exc:
        raise ProviderError("timeout", "gemini stream timed out") from exc
    if yielded:
        _verified_provider = ("gemini", llm_model("gemini"))

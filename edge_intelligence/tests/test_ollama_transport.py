"""Ollama transport tests against a local fake Ollama HTTP server.

No real model is needed: the fake server implements /api/tags and
/api/generate (streaming and non-streaming) so timeouts, keep-alive,
health reporting and fallback behaviour are exercised over real HTTP.
"""
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


class _FakeOllama(BaseHTTPRequestHandler):
    delay = 0.0
    received = []

    def log_message(self, *args):  # silence test output
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(payload)
        time.sleep(type(self).delay)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            if payload.get("stream"):
                for token in ("Wet-well ", "level ", "3.8 m."):
                    self.wfile.write((json.dumps({"response": token, "done": False}) + "\n").encode())
                self.wfile.write((json.dumps({"response": "", "done": True}) + "\n").encode())
            else:
                self.wfile.write(json.dumps({"response": json.dumps({"answer": "Wet-well level 3.8 m."}), "done": True}).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


class OllamaTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _FakeOllama.delay = 0.0
        _FakeOllama.received = []
        self.env = patch.dict(os.environ, {"OPSLENS_LLM_PROVIDER": "ollama", "EDGE_LLM_URL": self.url,
                                           "EDGE_LLM_MODEL": "qwen2.5:3b", "OPSLENS_OLLAMA_TIMEOUT": "5"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_health_reports_installed_model(self):
        from edge_slm import ollama_health
        health = ollama_health()
        self.assertTrue(health["reachable"])
        self.assertTrue(health["model_installed"])
        self.assertIsNone(health["error"])

    def test_complete_chat_success_sends_keep_alive_and_model(self):
        from llm_provider import complete_chat, provider_status
        text = complete_chat("prompt")
        self.assertIn("3.8", text)
        sent = _FakeOllama.received[-1]
        self.assertEqual(sent["model"], "qwen2.5:3b")
        self.assertEqual(sent["keep_alive"], "30m")
        self.assertTrue(provider_status()["verified"])

    def test_streaming_tokens(self):
        from llm_provider import stream_chat
        self.assertEqual("".join(stream_chat("prompt")), "Wet-well level 3.8 m.")

    def test_slow_model_times_out_at_configured_budget_without_retry(self):
        from llm_provider import ProviderError, complete_chat
        _FakeOllama.delay = 3.0
        with patch.dict(os.environ, {"OPSLENS_OLLAMA_TIMEOUT": "1"}):
            started = time.monotonic()
            with self.assertRaises(ProviderError) as ctx:
                complete_chat("prompt")
            elapsed = time.monotonic() - started
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertLess(elapsed, 2.5)          # one attempt, not native + /v1 retry
        self.assertEqual(len(_FakeOllama.received), 1)

    def test_default_budget_is_long_enough_for_a_slow_cpu_answer(self):
        """A 2 s answer used to fail under the old 4 s default only on cold
        starts; with the 60 s local default it succeeds."""
        from llm_provider import complete_chat, llm_timeout
        _FakeOllama.delay = 2.0
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPSLENS_OLLAMA_TIMEOUT", None)
            self.assertEqual(llm_timeout(), 60.0)
            self.assertIn("3.8", complete_chat("prompt"))

    def test_warm_up_loads_model(self):
        from edge_slm import warm_up_ollama
        result = warm_up_ollama()
        self.assertTrue(result["loaded"])
        self.assertEqual(_FakeOllama.received[-1]["prompt"], "")


if __name__ == "__main__":
    unittest.main()

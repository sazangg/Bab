"""Minimal deterministic OpenAI-compatible provider for local performance runs."""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count

HOST = os.getenv("PROVIDER_STUB_HOST", "127.0.0.1")
PORT = int(os.getenv("PROVIDER_STUB_PORT", "8080"))
DELAY_SECONDS = int(os.getenv("PROVIDER_STUB_DELAY_MS", "20")) / 1000
FAIL_EVERY = int(os.getenv("PROVIDER_STUB_FAIL_EVERY", "0"))
REQUEST_COUNT = count(1)


class Handler(BaseHTTPRequestHandler):
    server_version = "bab-provider-stub/1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path.rstrip("/") == "/v1/models":
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "benchmark-chat",
                            "object": "model",
                            "owned_by": "bab-local",
                        }
                    ],
                },
            )
            return
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length", "0"))
        if content_length:
            self.rfile.read(content_length)
        request_number = next(REQUEST_COUNT)
        time.sleep(DELAY_SECONDS)
        if FAIL_EVERY and request_number % FAIL_EVERY == 0:
            self._json(503, {"error": {"message": "deterministic stub failure"}})
            return
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": {"message": "not found"}})
            return
        self._json(
            200,
            {
                "id": f"chatcmpl-benchmark-{request_number}",
                "object": "chat.completion",
                "created": 1_750_000_000,
                "model": "benchmark-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "benchmark-ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

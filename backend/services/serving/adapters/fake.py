"""FakeAdapter — a test double so supervisor + service tests run with no real engine.

Its ``download_spec`` launches a child that writes a tiny file, and ``serve_spec`` a Python
HTTP stub that answers ``/v1/models`` with 200 and ``/v1/embeddings`` with a small
vector — enough for the supervisor's readiness probe, the registry round-trip, and an
embedding role-bind probe to be exercised end-to-end without llama.cpp/MLX.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..download import DownloadSpec
from ..models import EngineKind, LaunchOptions, Workload
from ..supervisor import ServeSpec
from .base import EngineAdapter

# A trivial download child: writes a stub artifact into the destination and prints the
# manager's control lines (TOTAL + ARTIFACT), so the subprocess download path is exercised
# end-to-end with no network — mirroring how _STUB_SERVER stands in for a real engine.
_STUB_DOWNLOAD = """
import sys
from pathlib import Path

dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=True)
artifact = dest / "model.gguf"
artifact.write_bytes(b"GGUF")
print("TOTAL 4", flush=True)
print(f"ARTIFACT {artifact}", flush=True)
"""

# A minimal OpenAI-ish server: 200 on any GET (so /v1/models passes) and a small
# deterministic vector for any /embeddings POST (so an embedding endpoint can be bound
# and probed without a real engine). Runs until killed.
_STUB_SERVER = """
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._json({"object": "list", "data": []})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._json({
            "object": "list",
            "model": "fake",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        })

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


HTTPServer((sys.argv[1], int(sys.argv[2])), Handler).serve_forever()
"""


class FakeAdapter(EngineAdapter):
    kind = EngineKind.llama_cpp
    workloads = frozenset({Workload.chat, Workload.embedding})
    native_tools_default = True
    context_window_hint = 4096

    def __init__(self, *, available: bool = True) -> None:
        self._available = available

    async def is_available(self) -> bool:
        return self._available

    async def is_installed(self) -> bool:
        return self._available

    async def ensure_engine(self) -> None:
        return None

    def download_spec(
        self, repo: str, quant: str | None, dest: Path, token: str | None = None
    ) -> DownloadSpec:
        return DownloadSpec(argv=[sys.executable, "-c", _STUB_DOWNLOAD, str(dest)])

    def serve_spec(
        self,
        artifact: Path,
        port: int,
        workload: Workload,
        model_id: str,
        options: LaunchOptions | None = None,
    ) -> ServeSpec:
        return ServeSpec(argv=[sys.executable, "-c", _STUB_SERVER, "127.0.0.1", str(port)])

    def resolved_model_id(self, repo: str, artifact: Path) -> str:
        return repo

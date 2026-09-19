import json
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.runs import RunRequest
from app.variants import VariantPatch, apply_patch, sha256


def patch(body=b"Old example", **changes):
    return VariantPatch(
        **{
            "patch_id": "docs-example",
            "url": "https://example.com/docs",
            "expected_sha256": sha256(body),
            "old_text": "Old",
            "new_text": "Correct",
            **changes,
        }
    )


def test_exact_patch_and_drift_guard():
    variant = patch()
    body, outcome = apply_patch(b"Old example", variant)
    assert body == b"Correct example"
    assert outcome.status == "applied"
    body, outcome = apply_patch(b"Old example has changed", variant)
    assert body == b"Old example has changed"
    assert outcome.status == "hash_mismatch"
    body, outcome = apply_patch(b"Old Old", patch(b"Old Old"))
    assert body == b"Old Old"
    assert outcome.status == "text_not_unique"


def test_variant_requires_capture_and_matching_origin():
    request = {
        "url": "https://example.com",
        "tasks": ["question"],
        "harnesses": [{"name": "codex"}],
        "patches": [patch()],
    }
    with pytest.raises(ValidationError):
        RunRequest(**request)
    RunRequest(**request, variant_id="B", capture_http=True)
    with pytest.raises(ValidationError):
        RunRequest(
            **{**request, "url": "https://another.example"},
            variant_id="B",
            capture_http=True,
        )


@pytest.mark.skipif(
    not shutil.which("mitmdump"),
    reason="Run uv run --with mitmproxy==12.2.3 pytest tests/test_variants.py",
)
def test_real_https_proxy_rewrites_and_records_response(tmp_path):
    """Real TLS client -> MITM -> TLS origin, without external network or models."""
    original = b"Old example"

    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(original)

        def log_message(self, *args):
            pass

    cert = tmp_path / "origin.pem"
    key = tmp_path / "origin-key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        proxy_port = reserve.getsockname()[1]
    url = f"https://localhost:{server.server_port}/docs"
    variant = patch(url=url)
    (tmp_path / "config.json").write_text(
        json.dumps({"url": url, "patches": [variant.model_dump(mode="json")]})
    )
    module = Path(__file__).resolve().parents[1] / "app/sandbox_proxy.py"
    with (tmp_path / "proxy.log").open("w") as log:
        process = subprocess.Popen(
            [
                "mitmdump",
                "--quiet",
                "--listen-host",
                "127.0.0.1",
                "--listen-port",
                str(proxy_port),
                "--set",
                f"confdir={tmp_path / 'ca'}",
                "--ssl-insecure",
                "-s",
                str(module),
            ],
            stdout=log,
            stderr=log,
            env={
                **os.environ,
                "UPTRACK_OBSERVE_DIR": str(tmp_path),
                "PYTHONPATH": str(module.parent.parent),
            },
        )
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", proxy_port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        context = ssl.create_default_context(
            cafile=str(tmp_path / "ca/mitmproxy-ca-cert.pem")
        )
        with httpx.Client(
            proxy=f"http://127.0.0.1:{proxy_port}", verify=context
        ) as client:
            assert client.get(url).text == "Correct example"
            original = b"Old example has drifted"
            assert client.get(url).content == original
        observations = [
            json.loads(line)
            for line in (tmp_path / "http.jsonl").read_text().splitlines()
        ]
        assert observations[0]["patch"]["status"] == "applied"
        assert observations[0]["original_sha256"] == variant.expected_sha256
        assert observations[0]["response_body"] == "Correct example"
        assert observations[1]["patch"]["status"] == "hash_mismatch"
    finally:
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
        server.server_close()

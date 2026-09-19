"""Sandbox-only mitmproxy addon and launcher for public documentation GETs."""

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.observability import MAX_BODY, MAX_EVENTS, HTTPObservation, redact, safe_url
from app.variants import PatchOutcome, VariantPatch, apply_patch, origin, sha256

DIRECTORY = Path(os.environ.get("UPTRACK_OBSERVE_DIR", "/opt/uptrack-observations"))


class Recorder:
    def __init__(self) -> None:
        self.config = json.loads((DIRECTORY / "config.json").read_text())
        self.patches = [VariantPatch.model_validate(p) for p in self.config["patches"]]
        self.secrets = [
            value
            for key, value in os.environ.items()
            if key.endswith(("API_KEY", "PROXY_TOKEN")) and value
        ]
        self.count = 0

    def in_scope(self, flow: Any) -> bool:
        return flow.request.method == "GET" and origin(
            flow.request.pretty_url
        ) == origin(self.config["url"])

    def record(self, observation: HTTPObservation) -> None:
        if self.count >= MAX_EVENTS:
            (DIRECTORY / "truncated").touch()
            return
        self.count += 1
        with (DIRECTORY / "http.jsonl").open("a") as stream:
            stream.write(
                json.dumps(redact(observation.model_dump(), self.secrets)) + "\n"
            )

    def response(self, flow: Any) -> None:
        if not self.in_scope(flow):
            return
        response = flow.response
        content_type = response.headers.get("content-type", "")
        textual = content_type.startswith("text/") or any(
            kind in content_type for kind in ("json", "javascript", "xml")
        )
        # Decode HTTP content encoding first; hash exact decoded entity bytes.
        body = response.content or b""
        modified = body
        matching = next(
            (p for p in self.patches if str(p.url) == flow.request.pretty_url), None
        )
        sensitive = bool(
            flow.request.headers.get("authorization")
            or flow.request.headers.get("cookie")
        )
        eligible = textual and not sensitive and response.status_code == 200
        outcome = None
        if matching:
            if eligible and len(body) <= 1_000_000:
                modified, outcome = apply_patch(body, matching)
                if outcome.status == "applied":
                    response.content = modified
                    for header in ("etag", "content-md5", "last-modified", "digest"):
                        response.headers.pop(header, None)
                    response.headers["cache-control"] = "no-store"
            else:
                outcome = PatchOutcome(
                    patch_id=matching.patch_id, status="response_ineligible"
                )
        self.record(
            HTTPObservation(
                url=safe_url(flow.request.pretty_url),
                method=flow.request.method,
                started_at=flow.request.timestamp_start,
                duration_ms=round(
                    (time.time() - flow.request.timestamp_start) * 1000, 3
                ),
                status_code=response.status_code,
                content_type=content_type,
                original_sha256=sha256(body),
                modified_sha256=sha256(modified),
                original_body=body[:MAX_BODY].decode("utf-8", "replace")
                if eligible
                else None,
                response_body=modified[:MAX_BODY].decode("utf-8", "replace")
                if eligible
                else None,
                body_truncated=max(len(body), len(modified)) > MAX_BODY,
                patch=outcome,
            )
        )

    def error(self, flow: Any) -> None:
        if self.in_scope(flow):
            self.record(
                HTTPObservation(
                    url=safe_url(flow.request.pretty_url),
                    method=flow.request.method,
                    started_at=flow.request.timestamp_start,
                    duration_ms=round(
                        (time.time() - flow.request.timestamp_start) * 1000, 3
                    ),
                    error=str(flow.error),
                )
            )


def start(config: str) -> None:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    DIRECTORY.chmod(0o700)
    (DIRECTORY / "config.json").write_text(config)
    (DIRECTORY / "http.jsonl").touch()
    target = urlsplit(json.loads(config)["url"])
    with (DIRECTORY / "proxy.log").open("w") as log:
        process = subprocess.Popen(
            [
                "mitmdump",
                "--quiet",
                "--listen-host",
                "127.0.0.1",
                "--listen-port",
                "8080",
                "--set",
                f"confdir={DIRECTORY / 'ca'}",
                "--set",
                "block_global=false",
                "--set",
                "body_size_limit=2m",
                "--allow-hosts",
                rf"^{re.escape(target.hostname or '')}:\d+$",
                "-s",
                __file__,
            ],
            stdout=log,
            stderr=log,
        )
    certificate = DIRECTORY / "ca/mitmproxy-ca-cert.pem"
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Observation proxy failed to start")
        try:
            with socket.create_connection(("127.0.0.1", 8080), timeout=0.1):
                if certificate.exists():
                    # Only public certificates are readable by the harness user.
                    bundle = Path("/tmp/uptrack-ca.pem")
                    system = Path("/etc/ssl/certs/ca-certificates.crt")
                    bundle.write_bytes(system.read_bytes() + certificate.read_bytes())
                    bundle.chmod(0o644)
                    return
        except OSError:
            pass
        time.sleep(0.1)
    process.terminate()
    raise TimeoutError("Observation proxy did not become ready")


if __name__ == "__main__":
    start(sys.argv[1])
else:
    # mitmproxy loads this file as a script, outside the application process.
    if (DIRECTORY / "config.json").exists():
        addons = [Recorder()]

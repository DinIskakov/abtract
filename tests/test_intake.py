"""Intake: mirror a site served by http.server into a directory / the store, and pick tasks. No API keys."""
from __future__ import annotations

import functools
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from abtract import store
from abtract.config import settings
from abtract.intake.mirror import MirrorReport, local_path_for, mirror_site, mirror_to_store, site_id_for_url
from abtract.intake.tasks import pick_tasks

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demo_site" / "v0"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D102
        pass


@pytest.fixture(scope="module")
def demo_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(DEMO)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    finally:
        httpd.shutdown()


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    return tmp_path / "data"


def _local_refs(html_file: Path) -> list[str]:
    soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")
    refs = [str(a["href"]) for a in soup.find_all("a", href=True)]
    refs += [str(el["href"]) for el in soup.find_all("link", href=True)]
    refs += [str(el["src"]) for el in soup.find_all("script", src=True)]
    return refs


# --------------------------------------------------------------------------- mirror_site

def test_mirror_demo_site(demo_server, tmp_path):
    dest = tmp_path / "mirror"
    report = mirror_site(demo_server, dest, max_pages=40)
    assert isinstance(report, MirrorReport)
    for rel in ("index.html", "pricing.html", "docs/index.html", "assets/style.css", "abtract-tasks.json"):
        assert (dest / rel).is_file(), rel
    assert report.tasks_file and "abtract-tasks.json" in report.assets
    assert report.errors == [] and report.skipped == []
    assert 0 < len(report.pages) <= 40 and len(set(report.pages)) == len(report.pages)
    assert "index.html" in report.pages and "docs/quickstart.html" in report.pages
    assert "changelog.html" in report.pages  # only linked by the demo's JavaScript navigation
    assert report.unresolved_links == 0
    # every reference in the mirrored docs page is relative and resolves to a mirrored file
    docs = dest / "docs" / "index.html"
    refs = _local_refs(docs)
    assert refs, "docs page has links"
    for ref in refs:
        assert not ref.startswith(("http://", "https://", "/")), ref
        target = (docs.parent / ref.split("#")[0]).resolve()
        assert target.is_file(), f"{ref} -> {target}"
    assert "../assets/style.css" in refs and "../index.html" in refs
    # the form action on the newsletter page still points at the api endpoint (never fetched, kept relative)
    news = (dest / "newsletter.html").read_text()
    assert 'action="api/newsletter"' in news
    # the tasks file is the demo's 14 tasks
    assert len(json.loads((dest / "abtract-tasks.json").read_text())) == 14


def test_mirror_respects_max_pages(demo_server, tmp_path):
    report = mirror_site(demo_server, tmp_path / "m", max_pages=3)
    assert len(report.pages) == 3
    assert any("page cap" in s for s in report.skipped)
    assert report.errors == []


def test_mirror_emits_page_checks_before_writing_complete_snapshot(demo_server, tmp_path):
    seen = []
    dest = tmp_path / "progress"
    def on_page(path, html):
        assert not (dest / "index.html").exists()
        assert b"<html" in html.lower()
        seen.append(path)
    report = mirror_site(demo_server, dest, max_pages=3, on_page=on_page)
    assert seen[0] == "index.html" and len(seen) == len(report.pages) == 3


# a tiny hand-rolled site with the awkward cases: absolute same-origin links, <base>, query strings,
# extension-less HTML, off-origin links, css url(), a 404 and a huge asset
class _CasesHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[str, bytes]] = {}

    def do_GET(self):  # noqa: N802
        path = self.path
        if path in self.routes:
            ctype, body = self.routes[path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/old":
            self.send_response(302)
            self.send_header("Location", "/pricing")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):  # noqa: D102
        pass


@pytest.fixture
def cases_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _CasesHandler)
    port = httpd.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    _CasesHandler.routes = {
        "/app/": ("text/html; charset=utf-8", f"""<!doctype html><html><head><base href="{origin}/app/">
            <link rel="stylesheet" href="{origin}/app/css/site.css"></head><body>
            <a href="{origin}/app/pricing">Pricing</a> <a href="docs/">Docs</a> <a href="search?q=gpu">Search</a>
            <a href="{origin}/legal/terms.html">Terms</a> <a href="https://example.org/x">Off-origin</a>
            <a href="mailto:a@b.c">Mail</a> <a href="/old">Old</a> <a href="missing.html">Missing</a>
            <img src="{origin}/app/img/big.png"> <a href="#top">Top</a>
            <form action="{origin}/app/api/lead" method="post"><input name="email"></form>
            </body></html>""".encode()),
        "/app/pricing": ("text/html", b"<html><body><h1>Pricing $3</h1><a href='./'>Home</a></body></html>"),
        "/app/docs/": ("text/html", f"<html><body><a href='{origin}/app/pricing#plans'>Plans</a></body></html>".encode()),
        "/app/search?q=gpu": ("text/html", b"<html><body>results</body></html>"),
        "/legal/terms.html": ("text/html", b"<html><body>terms <a href='/app/'>home</a></body></html>"),
        "/app/css/site.css": ("text/css", f"body{{background:url({origin}/app/img/bg.png)}} @import '{origin}/app/css/x.css';".encode()),
        "/app/img/bg.png": ("image/png", b"\x89PNG bg"),
        "/app/img/big.png": ("image/png", b"\x89PNG" + b"0" * 5000),
        "/app/css/x.css": ("text/css", b"h1{color:red}"),
    }
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield origin + "/app/"
    finally:
        httpd.shutdown()


def test_mirror_rewrites_awkward_links(cases_server, tmp_path):
    dest = tmp_path / "m"
    report = mirror_site(cases_server, dest, max_asset_bytes=1000)
    files = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert {"index.html", "pricing.html", "docs/index.html", "__/legal/terms.html", "css/site.css", "css/x.css",
            "img/bg.png"} <= files
    assert any(re.fullmatch(r"search_q[0-9a-f]{6}\.html", f) for f in files)
    assert "img/big.png" not in files and any("big.png" in s and "byte cap" in s for s in report.skipped)
    index = (dest / "index.html").read_text()
    assert "<base" not in index
    assert 'href="pricing.html"' in index and 'href="docs/index.html"' in index
    assert 'href="__/legal/terms.html"' in index
    assert 'href="https://example.org/x"' in index and 'href="mailto:a@b.c"' in index and 'href="#top"' in index
    assert 'href="pricing.html"' in index  # /old redirected to /pricing -> aliased
    assert 'href="missing.html"' in index  # unfetched: best guess, reported by check_site
    assert 'action="api/lead"' in index
    assert re.search(r'href="search_q[0-9a-f]{6}\.html"', index)
    assert 'href="../pricing.html#plans"' in (dest / "docs" / "index.html").read_text()
    assert 'href="../../index.html"' in (dest / "__" / "legal" / "terms.html").read_text()
    css = (dest / "css" / "site.css").read_text()
    assert "url(../img/bg.png)" in css and "@import '../css/x.css'" in css or "@import 'x.css'" in css
    assert report.unresolved_links >= 1  # missing.html
    assert any("missing.html" in e or "404" in e for e in report.errors)


# --------------------------------------------------------------------------- local paths & ids

def test_local_path_for_cases():
    root = "https://x.modal.run/s/demo/v0/"
    assert local_path_for(root, root, content_type="text/html") == "index.html"
    assert local_path_for(root + "docs/", root, content_type="text/html") == "docs/index.html"
    assert local_path_for(root + "pricing.html", root, content_type="text/html") == "pricing.html"
    assert local_path_for(root + "pricing", root, content_type="text/html") == "pricing.html"
    assert local_path_for("https://x.modal.run/other/a.png", root, kind="asset", content_type="image/png") == "__/other/a.png"
    q = local_path_for(root + "pricing.html?plan=pro", root, content_type="text/html")
    assert re.fullmatch(r"pricing_q[0-9a-f]{6}\.html", q)
    assert local_path_for(root + "api/lead", root, kind="action") == "api/lead"
    assert local_path_for(root + "data", root, kind="asset", content_type="application/json") == "data.json"
    assert local_path_for(root + "../../etc/passwd", root, content_type="text/html").startswith("__/")


def test_site_id_for_url(tmp_store):
    assert site_id_for_url("https://zephyrcompute.io/") == "zephyrcompute-io"
    assert site_id_for_url("https://www.zephyrcompute.io/pricing.html") == "zephyrcompute-io-pricing"
    assert site_id_for_url("https://x.modal.run/s/demo/v0/") == "demo-v0"
    assert site_id_for_url("https://x.modal.run/s/demo/v3/docs/index.html") == "demo-v3"
    assert site_id_for_url("http://localhost:8000/") == "localhost-8000"
    assert site_id_for_url("example.org") == "example-org"
    # uniqueness against the store: existing id -> 4-char hash suffix
    store.site_dir("zephyrcompute-io", "v0").mkdir(parents=True)
    sid = site_id_for_url("https://zephyrcompute.io/")
    assert re.fullmatch(r"zephyrcompute-io-[0-9a-f]{4}", sid)
    assert re.fullmatch(r"demo-v0-[0-9a-f]{4}", site_id_for_url("https://x/s/demo/v0/", existing=["demo-v0"]))


# --------------------------------------------------------------------------- mirror_to_store + pick_tasks

def test_mirror_to_store_and_site_provided_tasks(demo_server, tmp_store):
    sv, report = mirror_to_store(demo_server)
    assert sv.version == "v0" and sv.site_id == site_id_for_url(demo_server, existing=[])
    assert sv.notes.startswith("Mirrored from")
    assert (store.site_dir(sv.site_id, "v0") / "abtract-tasks.json").is_file()
    assert [v.version for v in store.list_versions(sv.site_id)] == ["v0"]
    assert "index.html" in sv.changed_files

    tasks, how = pick_tasks(sv.site_id, "v0", source_url=demo_server)
    assert how == "site-provided" and len(tasks) == 14
    assert {t.kind.value for t in tasks} == {"answer", "url", "action"}
    saved = store.load_site_tasks(sv.site_id)
    assert saved is not None and [t.id for t in saved] == [t.id for t in tasks]
    # a second intake of the same URL gets a fresh id
    assert site_id_for_url(demo_server) != sv.site_id


def test_pick_tasks_skips_missing_pricing_page(tmp_store):
    d = store.site_dir("plain", "v0")
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body><a href='pricing.html'>Pricing</a></body></html>")
    tasks, how = pick_tasks("plain", "v0", source_url="https://plain.example/")
    assert how == "site-derived"
    assert [t.id for t in tasks] == ["discovered_home"]
    assert not any(re.search(t.expected_url_pattern, "pricing.html") for t in tasks)
    assert store.load_site_tasks("plain") == tasks


def test_pick_tasks_uses_captured_content_and_nested_links(tmp_store):
    d = store.site_dir("plain", "v0")
    (d / "guides").mkdir(parents=True)
    (d / "index.html").write_text('<h1>Build &amp; ship</h1><a href="guides/">Guides</a>'
                                 '<a href="pricing.html">Pricing</a><a href="https://outside.example">External</a>')
    (d / "guides/index.html").write_text('<h1>Guides</h1><a href="../tutorial">Tutorial</a>'
                                        '<a href="../index.html">Home</a>')
    (d / "tutorial.html").write_text("<h1>Tutorial</h1>")
    tasks, how = pick_tasks("plain", "v0")
    assert how == "site-derived" and len(tasks) == 3
    assert tasks[0].expected_answer == "Build & ship"
    navigation = tasks[1:]
    assert any(re.search(t.expected_url_pattern, "guides/") for t in navigation)
    assert any(re.search(t.expected_url_pattern, "tutorial") for t in navigation)
    assert not any(re.search(t.expected_url_pattern, "pricing.html") for t in navigation)


def test_pick_tasks_validates_manifest_against_site(tmp_store):
    d = store.site_dir("plain", "v0")
    d.mkdir(parents=True)
    (d / "index.html").write_text("<h1>Build things</h1>")
    raw = [
        {"id": "missing_page", "kind": "url", "prompt": "Pricing?", "expected_url_pattern": "^pricing"},
        {"id": "made_up_fact", "kind": "answer", "prompt": "Price?", "expected_answer": "$99.99"},
        {"id": "made_up_action", "kind": "action", "prompt": "Buy", "expected_event": "checkout"},
        {"id": "real", "kind": "answer", "prompt": "Headline?", "expected_answer": "Build things"},
    ]
    (d / "abtract-tasks.json").write_text(json.dumps(raw))
    tasks, how = pick_tasks("plain", "v0")
    assert how == "site-provided" and [t.id for t in tasks] == ["real"]

    (d / "abtract-tasks.json").write_text(json.dumps(raw[:-1]))
    tasks, how = pick_tasks("plain", "v0")
    assert how == "site-derived" and [t.id for t in tasks] == ["discovered_headline"]


def test_pick_tasks_does_not_invent_homepage_when_capture_is_missing(tmp_store):
    with pytest.raises(FileNotFoundError, match="no captured homepage"):
        pick_tasks("missing", "v0")


def test_pick_tasks_gemini_failure_falls_through(tmp_store, monkeypatch):
    import abtract.optimizer.task_gen as tg

    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(tg, "generate_tasks", boom)
    d = store.site_dir("plain2", "v0")
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body>hi</body></html>")
    tasks, how = pick_tasks("plain2", "v0", source_url=None)
    assert how == "site-derived" and [t.id for t in tasks] == ["discovered_home"]

"""Tests for the site server (abtract/hosting/serve.py) using FastAPI's TestClient against a tmp data dir."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import settings
from app.hosting import serve
from app.schemas import SiteVersion


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


@pytest.fixture()
def site(data_dir: Path) -> Path:
    d = store.site_dir("demo", "v0")
    d.mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>Home</title><h1>Home</h1>")
    (d / "about.html").write_text("<!doctype html><title>About</title><h1>About</h1>")
    (d / "thanks.html").write_text("<!doctype html><title>Thanks</title><h1>Thanks</h1>")
    (d / "style.css").write_text("body{color:red}")
    (d / "app.js").write_text("console.log(1)")
    (d / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (d / "docs").mkdir()
    (d / "docs" / "index.html").write_text("<h1>Docs</h1>")
    (d / "docs" / "guide.html").write_text("<h1>Guide</h1>")
    store.register_version(SiteVersion(site_id="demo", version="v0"))
    # a file *outside* the site tree that must never be reachable
    (data_dir / "secret.txt").write_text("SECRET")
    return d


@pytest.fixture()
def client(site: Path) -> TestClient:
    return TestClient(serve.create_app())


# --------------------------------------------------------------------------- static serving


def test_healthz_and_index(client: TestClient):
    assert client.get("/healthz").json() == {"ok": True}
    r = client.get("/", headers={"Accept": "text/html"})
    assert r.status_code == 200 and "demo" in r.text and "/s/demo/v0/" in r.text
    r = client.get("/", headers={"Accept": "application/json"})
    assert r.json()["sites"][0]["site_id"] == "demo"


def test_serve_page_and_content_types(client: TestClient):
    r = client.get("/s/demo/v0/about.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<h1>About</h1>" in r.text
    assert client.get("/s/demo/v0/style.css").headers["content-type"].startswith("text/css")
    assert client.get("/s/demo/v0/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/s/demo/v0/logo.svg").headers["content-type"].startswith("image/svg+xml")


def test_index_fallbacks(client: TestClient):
    assert "<h1>Home</h1>" in client.get("/s/demo/v0/").text
    assert "<h1>Home</h1>" in client.get("/s/demo/v0/index.html").text
    assert "<h1>Docs</h1>" in client.get("/s/demo/v0/docs/").text
    assert "<h1>Docs</h1>" in client.get("/s/demo/v0/docs").text
    # no trailing slash on the version root -> redirect so relative links work
    r = client.get("/s/demo/v0", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].endswith("/s/demo/v0/")


def test_html_extension_fallback(client: TestClient):
    assert "<h1>About</h1>" in client.get("/s/demo/v0/about").text
    assert "<h1>Guide</h1>" in client.get("/s/demo/v0/docs/guide").text


def test_404s(client: TestClient):
    assert client.get("/s/demo/v0/nope.html").status_code == 404
    assert client.get("/s/demo/v0/nope").status_code == 404
    assert client.get("/s/demo/v9/").status_code == 404
    assert client.get("/s/other/v0/").status_code == 404


def test_path_traversal_blocked(client: TestClient, data_dir: Path):
    for p in ["../../secret.txt", "..%2F..%2Fsecret.txt", "%2e%2e/%2e%2e/secret.txt", "docs/../../../secret.txt"]:
        r = client.get(f"/s/demo/v0/{p}")
        assert r.status_code == 404, p
        assert "SECRET" not in r.text
    # site_id / version are sanitised by the store too
    assert client.get("/s/..%2F..%2F/secret.txt/").status_code == 404


def test_missing_version_reloads_store_once(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(store, "reload", lambda: calls.append(1))
    assert client.get("/s/demo/v7/").status_code == 404
    assert client.get("/s/demo/v7/").status_code == 404
    assert client.get("/s/demo/v7/index.html").status_code == 404
    assert len(calls) == 1  # throttled: not once per request
    # existing versions never trigger a reload
    calls.clear()
    assert client.get("/s/demo/v0/").status_code == 200
    assert calls == []


def test_reload_picks_up_version_written_by_another_container(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def fake_reload():
        d = store.site_dir("demo", "v1")
        d.mkdir(parents=True)
        (d / "index.html").write_text("<h1>V1</h1>")

    monkeypatch.setattr(store, "reload", fake_reload)
    r = client.get("/s/demo/v1/")
    assert r.status_code == 200 and "V1" in r.text


# --------------------------------------------------------------------------- events


def test_json_event_with_header(client: TestClient):
    r = client.post(
        "/s/demo/v0/api/event",
        json={"name": "cta_click", "payload": {"button": "signup"}},
        headers={"X-Abtract-Episode": "ep_header"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["episode_id"] == "ep_header"
    assert r.cookies.get("abtract_ep") == "ep_header"
    evs = store.read_events("demo", "v0")
    assert len(evs) == 1
    assert evs[0].name == "cta_click" and evs[0].payload == {"button": "signup"} and evs[0].episode_id == "ep_header"
    assert client.get("/s/demo/v0/api/events?episode_id=ep_header").json()[0]["name"] == "cta_click"
    assert client.get("/s/demo/v0/api/events?episode_id=other").json() == []


def test_json_event_requires_name(client: TestClient):
    assert client.post("/s/demo/v0/api/event", json={"payload": {}}).status_code == 400


def test_form_event_with_query_redirects_to_thanks(client: TestClient):
    r = client.post(
        "/s/demo/v0/api/waitlist?abtract_ep=ep_query",
        data={"email": "a@b.co", "plan": "pro"},
        headers={"Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("/s/demo/v0/thanks.html")
    assert r.cookies.get("abtract_ep") == "ep_query"
    evs = store.read_events("demo", "v0", "ep_query")
    assert len(evs) == 1
    assert evs[0].name == "waitlist" and evs[0].payload == {"email": "a@b.co", "plan": "pro"}
    # following the redirect lands on the real thanks page
    r2 = client.get(r.headers["location"])
    assert r2.status_code == 200 and "Thanks" in r2.text


def test_form_event_without_thanks_page_returns_html(client: TestClient, site: Path):
    (site / "thanks.html").unlink()
    r = client.post(
        "/s/demo/v0/api/contact", data={"msg": "hi"}, headers={"Accept": "text/html"}, follow_redirects=False
    )
    assert r.status_code == 200 and "Thanks" in r.text and "contact" in r.text


def test_form_event_json_client_gets_json(client: TestClient):
    r = client.post("/s/demo/v0/api/contact", data={"msg": "hi"}, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["episode_id"] is None
    r = client.post("/s/demo/v0/api/contact", json={"msg": "json body"}, headers={"X-Abtract-Episode": "ep_j"})
    assert r.json()["episode_id"] == "ep_j"
    assert store.read_events("demo", "v0", "ep_j")[0].payload == {"msg": "json body"}


def test_cookie_attribution_after_page_view(client: TestClient):
    # first navigation carries the episode in the query -> cookie is set on the page response
    r = client.get("/s/demo/v0/?abtract_ep=ep_cookie")
    assert r.status_code == 200 and r.cookies.get("abtract_ep") == "ep_cookie"
    # later plain requests (TestClient keeps the cookie jar) are attributed via the cookie
    r = client.post("/s/demo/v0/api/signup", data={"email": "x@y.z"}, headers={"Accept": "application/json"})
    assert r.json()["episode_id"] == "ep_cookie"
    assert store.read_events("demo", "v0", "ep_cookie")[0].name == "signup"
    # header still wins over the cookie
    r = client.post(
        "/s/demo/v0/api/signup",
        data={"email": "q"},
        headers={"X-Abtract-Episode": "ep_hdr", "Accept": "application/json"},
    )
    assert r.json()["episode_id"] == "ep_hdr"


def test_events_are_per_version(client: TestClient):
    client.post("/s/demo/v0/api/event", json={"name": "a"}, headers={"X-Abtract-Episode": "e1"})
    assert store.read_events("demo", "v1") == []
    assert len(store.read_events("demo", "v0")) == 1

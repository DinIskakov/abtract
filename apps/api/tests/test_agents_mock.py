"""Offline tests for the text / dom / vision agents. No API keys: model "mock" plus a scripted `chat` monkeypatch.

A tiny 3-page site (tests/fixtures/site) is served by http.server in a thread; POST api/newsletter is handled by
the test server so form submissions can be asserted (payload + X-Abtract-Episode header).
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from app.agents import run_agent
from app.agents.base import parse_reply
from app.models.llm import ChatMessage, LLMError, LLMResponse
from app.schemas import AgentKind, Task, TaskKind, Usage

FIXTURE_SITE = Path(__file__).parent / "fixtures" / "site"


# --------------------------------------------------------------------------- fixture server


class _Handler(SimpleHTTPRequestHandler):
    posts: list[dict] = []

    def log_message(self, *a, **k):  # silence
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode()
        form = {k: v[0] for k, v in parse_qs(body).items()}
        _Handler.posts.append({"path": self.path, "form": form, "episode": self.headers.get("X-Abtract-Episode")})
        if self.path.endswith("/api/newsletter"):
            html = f"<html><head><title>Subscribed</title></head><body><h1>Thanks!</h1><p>You are subscribed with {form.get('email', '?')}.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
        else:
            self.send_error(404)


@pytest.fixture(scope="module")
def site_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Handler, directory=str(FIXTURE_SITE)))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.fixture(autouse=True)
def _clear_posts():
    _Handler.posts.clear()
    yield


# --------------------------------------------------------------------------- scripted model


def script(monkeypatch, replies):
    """Replace llm.chat with a side-effect list. Returns the list of message lists seen (one per call)."""
    calls: list[list[ChatMessage]] = []

    def fake_chat(spec, messages, **kw):
        calls.append(messages)
        r = replies[min(len(calls) - 1, len(replies) - 1)]
        text = r if isinstance(r, str) else json.dumps(r)
        return LLMResponse(text=text, usage=Usage(input_tokens=100, output_tokens=10, llm_calls=1, llm_latency_ms=1))

    monkeypatch.setattr("app.models.llm.chat", fake_chat)
    return calls


def obs_text(messages: list[ChatMessage]) -> str:
    c = messages[-1].content
    if isinstance(c, str):
        return c
    return "\n".join(p["text"] for p in c if p.get("type") == "text")


def A(type_, **kw):
    return {"thought": f"do {type_}", "action": {"type": type_, **kw}}


def task(prompt="What does an H100 cost per hour?", max_steps=8, kind=TaskKind.answer):
    return Task(id="t_test", kind=kind, prompt=prompt, max_steps=max_steps)


def run(kind, t, site_url, **kw):
    return run_agent(kind, "mock", t, site_url, run_id="test", site_id="fixture", site_version="v0", **kw)


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:  # noqa: BLE001
        return False


needs_chromium = pytest.mark.skipif(
    not chromium_available(), reason="Playwright Chromium not installed (uv run playwright install chromium)"
)


# --------------------------------------------------------------------------- reply parsing


def test_parse_reply_is_lenient():
    th, a, err = parse_reply('{"thought": "x", "action": {"type": "click", "id": "12"}}')
    assert err is None and a.type == "click" and a.id == 12 and th == "x"
    _, a, err = parse_reply('```json\n{"type": "answer", "text": "$3.95/hr"}\n```')
    assert err is None and a.type == "answer" and a.text == "$3.95/hr"
    _, a, err = parse_reply('{"action": "type", "id": "[3]", "text": "hi"}')
    assert err is None and a.type == "type" and a.id == 3 and a.text == "hi"
    _, a, err = parse_reply('{"reasoning": "...", "action": {"goto": {"url": "pricing.html"}}}')
    assert err is None and a.type == "navigate" and a.url == "pricing.html"
    _, a, err = parse_reply('{"action": {"name": "scroll_down"}}')
    assert err is None and a.type == "scroll" and a.direction == "down"
    _, a, err = parse_reply('{"thought": "done", "action": {"type": "final_answer", "answer": "Sydney"}}')
    assert err is None and a.type == "answer" and a.text == "Sydney"
    _, a, err = parse_reply('{"action": {"type": "give_up"}}')
    assert err is None and a.type == "give_up" and a.reason
    _, a, err = parse_reply("I think we should click something")
    assert a is None and "JSON" in err
    _, a, err = parse_reply('{"action": {"type": "hover", "id": 1}}')
    assert a is None and "unknown action" in err
    _, a, err = parse_reply('{"action": {"type": "click"}}')
    assert a is None and "id" in err


# --------------------------------------------------------------------------- text agent


def test_text_answer_via_mock_env(monkeypatch, site_url):
    monkeypatch.setenv("ABTRACT_MOCK_REPLY", json.dumps(A("answer", text="$3.95/hr")))
    ep = run("text", task(), site_url)
    assert ep.final_answer == "$3.95/hr"
    assert ep.usage.llm_calls == 1 and len(ep.steps) == 1
    assert ep.failure_mode is None and ep.error is None and ep.success is None
    assert ep.finished_at is not None and ep.final_url == site_url
    assert ep.agent_kind == AgentKind.text and ep.model_id == "mock"
    assert ep.steps[0].observation_chars > 0 and ep.steps[0].thought == "do answer"
    assert ep.cost_usd == 0.0


def test_text_click_link_then_answer(monkeypatch, site_url):
    calls = script(monkeypatch, [A("click", id=2), A("answer", text="$3.95/hr")])
    ep = run("text", task(), site_url)
    assert ep.final_answer == "$3.95/hr"
    assert ep.final_url.endswith("pricing.html")
    assert len(ep.steps) == 2 and ep.usage.llm_calls == 2 and ep.usage.input_tokens == 200
    first, second = obs_text(calls[0]), obs_text(calls[1])
    assert "[2]" in first and 'link "Pricing" -> pricing.html' in first
    assert "$3.95/hr" in second and "Title: Pricing - Acme Cloud" in second
    assert "PREVIOUS STEPS" in second and '"click"' in second
    assert ep.steps[0].url == site_url and ep.steps[1].url.endswith("pricing.html")


def test_text_sees_hidden_text_and_no_js(monkeypatch, site_url):
    calls = script(monkeypatch, [A("answer", text="x")])
    run("text", task(), site_url)
    o = obs_text(calls[0])
    assert "ZEBRA-42" in o  # display:none text is visible to a text agent (that is the trap)
    assert "JS-OFF" in o and "JS-ON" not in o
    assert "textContent" not in o  # script bodies are dropped


def test_text_form_submit(monkeypatch, site_url):
    calls = script(
        monkeypatch,
        [
            A("navigate", url="signup.html"),
            A("type", id=3, text="jane@example.com"),
            A("select", id=4, value="Pro"),
            A("click", id=5),  # checkbox
            A("click", id=7),  # submit
            A("answer", text="Subscribed jane@example.com"),
        ],
    )
    ep = run(
        "text", task("Subscribe jane@example.com to the newsletter on the Pro plan", kind=TaskKind.action), site_url
    )
    assert ep.final_answer == "Subscribed jane@example.com"
    assert [s.error for s in ep.steps] == [None] * 6
    assert len(_Handler.posts) == 1
    post = _Handler.posts[0]
    assert post["path"].endswith("/api/newsletter")
    assert post["form"] == {"email": "jane@example.com", "plan": "pro", "terms": "yes", "source": "signup-page"}
    assert post["episode"] == ep.id
    assert ep.final_url.endswith("/api/newsletter")
    assert "Thanks!" in obs_text(calls[5])
    form_obs = obs_text(calls[4])
    assert 'value="jane@example.com"' in form_obs and "selected='pro'" in form_obs and "checked" in form_obs
    assert "submits form POST api/newsletter" in obs_text(calls[1])


def test_text_js_button_and_back(monkeypatch, site_url):
    script(monkeypatch, [A("click", id=3), A("click", id=6), A("back"), A("answer", text="ok")])
    ep = run("text", task(), site_url)
    assert ep.steps[0].error is None and ep.steps[0].url == site_url
    assert "JavaScript" in ep.steps[1].error
    assert ep.steps[2].error is None
    assert ep.final_url == site_url


def test_text_refuses_offsite(monkeypatch, site_url):
    script(monkeypatch, [A("navigate", url="https://example.com/"), A("click", id=5), A("answer", text="ok")])
    ep = run("text", task(), site_url)
    assert "origin" in ep.steps[0].error and "origin" in ep.steps[1].error
    assert ep.final_url == site_url and ep.final_answer == "ok"


def test_text_unparseable_reply_is_recorded_and_loop_continues(monkeypatch, site_url):
    calls = script(
        monkeypatch, ["sure, let me click the pricing link", '{"action": {"type": "hover"}}', A("answer", text="x")]
    )
    ep = run("text", task(), site_url)
    assert len(ep.steps) == 3
    assert ep.steps[0].action.type == "noop" and "JSON" in ep.steps[0].error
    assert ep.steps[1].action.type == "noop" and "unknown action" in ep.steps[1].error
    assert "ERROR:" in obs_text(calls[1])
    assert ep.final_answer == "x" and ep.failure_mode is None


def test_text_max_steps_and_give_up(monkeypatch, site_url):
    script(monkeypatch, [A("scroll", direction="down")])
    ep = run("text", task(max_steps=3), site_url)
    assert ep.failure_mode == "max_steps" and len(ep.steps) == 3 and ep.final_answer is None
    script(monkeypatch, [A("give_up", reason="nope")])
    ep = run("text", task(), site_url)
    assert ep.failure_mode == "gave_up" and len(ep.steps) == 1 and ep.steps[0].action.reason == "nope"


def test_text_timeout(monkeypatch, site_url):
    from app.config import settings

    script(monkeypatch, [A("scroll", direction="down")])
    monkeypatch.setattr(settings, "episode_timeout_s", -1)
    ep = run("text", task(), site_url)
    assert ep.failure_mode == "timeout" and ep.finished_at is not None


def test_llm_error_never_raises(monkeypatch, site_url):
    def boom(*a, **k):
        raise LLMError("no key")

    monkeypatch.setattr("app.models.llm.chat", boom)
    ep = run("text", task(), site_url)
    assert ep.failure_mode == "error" and "no key" in ep.error and ep.finished_at is not None


def test_text_unreachable_site(monkeypatch):
    script(monkeypatch, [A("answer", text="x")])
    ep = run("text", task(), "http://127.0.0.1:9/")
    assert ep.failure_mode == "error" and ep.error and len(ep.steps) == 0


def test_vision_requires_vision_model(site_url):
    ep = run_agent("vision", "qwen3.8-max", task(), site_url, run_id="test", site_id="fixture", site_version="v0")
    assert ep.failure_mode == "error" and ep.error == "model has no vision" and ep.usage.llm_calls == 0


# --------------------------------------------------------------------------- browser agents


@needs_chromium
def test_dom_click_then_answer(monkeypatch, site_url):
    calls = script(monkeypatch, [A("click", id=2), A("answer", text="$3.95/hr")])
    ep = run("dom", task(), site_url)
    assert ep.error is None and ep.final_answer == "$3.95/hr"
    assert ep.final_url.endswith("pricing.html") and len(ep.steps) == 2
    first, second = obs_text(calls[0]), obs_text(calls[1])
    assert "ZEBRA-42" not in first  # hidden text is not rendered
    assert "JS-ON" in first  # JavaScript ran
    assert 'link "Pricing" -> pricing.html' in first
    assert "$3.95/hr" in second and "Title: Pricing - Acme Cloud" in second


@needs_chromium
def test_dom_form_submit_and_offsite_block(monkeypatch, site_url):
    calls = script(
        monkeypatch,
        [
            A("click", id=5),  # External partner (target=_blank, other host) -> blocked
            A("navigate", url="signup.html"),
            A("type", id=3, text="jane@example.com"),
            A("select", id=4, value="pro"),
            A("click", id=5),  # checkbox
            A("click", id=7),  # submit
            A("answer", text="done"),
        ],
    )
    ep = run("dom", task("Subscribe", kind=TaskKind.action), site_url)
    assert ep.error is None, ep.error
    assert ep.steps[0].error and "not on this site" in ep.steps[0].error
    assert f"CURRENT OBSERVATION:\nURL: {site_url}\n" in obs_text(calls[1])  # went back after the blocked hop
    assert [s.error for s in ep.steps[1:]] == [None] * 6
    assert len(_Handler.posts) == 1
    post = _Handler.posts[0]
    assert post["form"] == {"email": "jane@example.com", "plan": "pro", "terms": "yes", "source": "signup-page"}
    assert post["episode"] == ep.id
    assert "Thanks!" in obs_text(calls[6]) and ep.final_url.endswith("/api/newsletter")


@needs_chromium
def test_vision_screenshot_and_legend(monkeypatch, site_url, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    shots = tmp_path / "runs" / "test" / "screenshots" / "ep"
    calls = script(monkeypatch, [A("click", id=2), A("answer", text="$3.95/hr")])
    ep = run("vision", task(), site_url, screenshot_dir=shots)
    assert ep.error is None and ep.final_answer == "$3.95/hr" and ep.final_url.endswith("pricing.html")
    assert (shots / "00.png").exists() and (shots / "01.png").exists()
    assert ep.steps[0].screenshot_path == "runs/test/screenshots/ep/00.png"
    assert (shots / "00.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    legend = obs_text(calls[0])
    assert '2: link "Pricing" -> pricing.html' in legend and "Viewport shows" in legend
    content = calls[0][-1].content
    assert isinstance(content, list) and any(p.get("type") == "image" and len(p["png_base64"]) > 1000 for p in content)
    assert "ZEBRA-42" not in legend

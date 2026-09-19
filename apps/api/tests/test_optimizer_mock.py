"""Optimizer with a patched `chat` (no Gemini), tmp data_dir, check_site via subprocess."""

from __future__ import annotations

import json
import time

import pytest

from app import store
from app.config import settings
from app.models.llm import LLMResponse
from app.optimizer import rewrite, task_gen
from app.optimizer.check_site import check_site
from app.schemas import Action, Episode, RunSummary, Step, Task, Usage

INDEX = (
    "<html><body><h1>Modalish</h1><nav><a href='pricing.html'>Pricing</a><a href='docs/'>Docs</a></nav></body></html>"
)
PRICING = (
    "<html><body><canvas id='c'></canvas><script>draw('H100 $3.95/hr')</script>"
    "<form action='api/waitlist_submit' method='post'><input name='email'><button>Go</button></form>"
    "<a href='index.html'>Home</a></body></html>"
)
DOCS = (
    "<html><body><p>docs</p><a href='../index.html'>Home</a><link rel='stylesheet' href='../style.css'></body></html>"
)


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    src = tmp_path / "src"
    (src / "docs").mkdir(parents=True)
    (src / "index.html").write_text(INDEX)
    (src / "pricing.html").write_text(PRICING)
    (src / "docs" / "index.html").write_text(DOCS)
    (src / "style.css").write_text("body{color:#000} .x{background:url(img/none.png)}")
    (src / "img").mkdir()
    (src / "img" / "none.png").write_bytes(b"\x89PNG")
    store.import_site("demo", "v0", src)
    return tmp_path


@pytest.fixture
def run_with_failures(site):
    task = Task(
        id="t_price",
        kind="answer",
        prompt="How much is an H100 per hour?",
        expected_answer="3.95",
        answer_aliases=["$3.95"],
        trap="canvas_pricing",
    )
    run = RunSummary(
        run_id="run_1",
        site_id="demo",
        site_version="v0",
        site_url="http://h/s/demo/v0/",
        tasks=[task],
        model_ids=["mock"],
        agent_kinds=["text"],
    )
    ep = Episode(
        run_id="run_1",
        site_id="demo",
        site_version="v0",
        task_id="t_price",
        agent_kind="text",
        model_id="mock",
        success=False,
        failure_mode="wrong_answer",
        judge_reason="expected '3.95', got 'unknown'",
        final_answer="unknown",
        finished_at=time.time(),
        steps=[
            Step(
                index=0,
                url="http://h/s/demo/v0/",
                thought="look for pricing",
                action=Action(type="navigate", url="pricing.html"),
            ),
            Step(
                index=1,
                url="http://h/s/demo/v0/pricing.html",
                thought="no price text visible",
                action=Action(type="answer", text="unknown"),
            ),
        ],
    )
    store.save_episode(ep)
    from app.metrics.score import aggregate

    aggregate(run, [ep])
    store.save_run(run)
    return run


def _patch_chat(monkeypatch, replies: list[dict]):
    calls: list[list] = []

    def fake_chat(spec, messages, **kw):
        calls.append(messages)
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return LLMResponse(text=json.dumps(reply), usage=Usage(input_tokens=10, output_tokens=5))

    monkeypatch.setattr(rewrite, "chat", fake_chat)
    return calls


# --------------------------------------------------------------------------- check_site


def test_check_site_passes_on_valid_site(site):
    assert check_site(store.site_dir("demo", "v0")) == []


def test_check_site_reports_problems(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    (d / "index.html").write_text(
        "```html\n<html><body><a href='/pricing.html'>abs</a><a href='missing.html'>gone</a>"
        "<a href='api/waitlist_submit'>ok api</a><script src='https://cdnjs.cloudflare.com/x.js'></script>"
        "<img src='https://evil.example.com/t.png'><a href='mailto:x@y.z'>m</a></body></html>\n```"
    )
    problems = "\n".join(check_site(d))
    assert "absolute internal" in problems and "/pricing.html" in problems
    assert "missing.html" in problems
    assert "evil.example.com" in problems
    assert "code fence" in problems
    assert "cdnjs" not in problems and "api/waitlist_submit" not in problems and "mailto" not in problems


# --------------------------------------------------------------------------- context


def test_build_context_has_primer_metrics_failures_and_files(run_with_failures):
    ctx = rewrite.build_context("demo", "v0", run_with_failures, store.load_episodes("run_1"))
    assert "text agent" in ctx and "vision agent" in ctx
    assert "Per task" in ctx and "canvas_pricing" in ctx
    assert "How much is an H100" in ctx and "no price text visible" in ctx and "wrong_answer" in ctx
    assert "### FILE: pricing.html" in ctx and "$3.95/hr" in ctx and "### FILE: style.css" in ctx
    # files visited in failed traces come first
    assert ctx.index("### FILE: pricing.html") < ctx.index("### FILE: docs/index.html")


# --------------------------------------------------------------------------- apply / optimize


def test_optimize_site_writes_new_version(run_with_failures, monkeypatch):
    new_pricing = PRICING.replace("<canvas id='c'></canvas>", "<table><tr><td>H100</td><td>$3.95/hr</td></tr></table>")
    proposal = {
        "notes": "Added a real table with the H100 price; the text agent could not read the canvas.",
        "files": {"pricing.html": "```html\n" + new_pricing + "\n```"},
        "deleted": [],
    }
    calls = _patch_chat(monkeypatch, [proposal])
    sv = rewrite.optimize_site("demo", "v0", "run_1", local=True)
    assert sv.version == "v1" and sv.parent == "v0" and sv.changed_files == ["pricing.html"]
    assert len(calls) == 1
    d = store.site_dir("demo", "v1")
    assert d.is_dir()
    assert (d / "pricing.html").read_text() == new_pricing  # fence stripped, full content written
    assert (d / "index.html").read_text() == INDEX  # untouched files copied from the parent
    assert (d / "docs" / "index.html").exists() and (d / "style.css").exists()
    versions = json.loads(store.versions_path("demo").read_text())
    assert [v["version"] for v in versions] == ["v0", "v1"]
    assert versions[1]["notes"] == proposal["notes"] and "VALIDATION" not in versions[1]["notes"]
    assert store.next_version("demo") == "v2"


def test_broken_link_rejects_version_after_failed_repair(run_with_failures, monkeypatch):
    broken = {
        "notes": "Linked to a new page.",
        "files": {"index.html": INDEX.replace("pricing.html", "prices.html")},
        "deleted": [],
    }
    calls = _patch_chat(monkeypatch, [broken, broken])  # the fix round returns the same broken proposal
    with pytest.raises(RuntimeError, match="(?s)Rewrite rejected.*prices.html"):
        rewrite.optimize_site("demo", "v0", "run_1", local=True)
    assert len(calls) == 2
    assert "FAILED validation" in calls[1][-1].content and "prices.html" in calls[1][-1].content
    versions = json.loads(store.versions_path("demo").read_text())
    assert [v["version"] for v in versions] == ["v0"]
    assert not store.site_dir("demo", "v1").exists()
    assert (store.site_dir("demo", "v0") / "index.html").read_text() == INDEX


def test_fix_round_repairs_the_site(run_with_failures, monkeypatch):
    broken = {"notes": "oops", "files": {"index.html": INDEX.replace("pricing.html", "prices.html")}, "deleted": []}
    fixed = {"notes": "fixed the link", "files": {"index.html": INDEX + "<!-- fixed -->"}, "deleted": []}
    calls = _patch_chat(monkeypatch, [broken, fixed])
    sv = rewrite.optimize_site("demo", "v0", "run_1", local=True)
    assert len(calls) == 2 and sv.notes == "fixed the link"
    assert "<!-- fixed -->" in (store.site_dir("demo", "v1") / "index.html").read_text()


def test_unparseable_proposal_does_not_create_fake_improvement(run_with_failures, monkeypatch):
    def bad_chat(spec, messages, **kw):
        return LLMResponse(text="I cannot do that", usage=Usage())

    monkeypatch.setattr(rewrite, "chat", bad_chat)
    with pytest.raises(RuntimeError, match="unparseable JSON"):
        rewrite.optimize_site("demo", "v0", "run_1", local=True)
    assert not store.site_dir("demo", "v1").exists()


def test_apply_rewrite_never_deletes_pages_or_escapes_dir(site):
    proposal = {
        "notes": "n",
        "files": {"../evil.html": "x", "/abs.html": "y", "notes.txt": "hello"},
        "deleted": ["index.html", "style.css"],
    }
    d = rewrite.materialize("demo", "v0", "v1", rewrite._clean_proposal(proposal))
    assert (d / "index.html").exists() and not (d / "style.css").exists()
    assert (d / "notes.txt").read_text() == "hello"
    assert not (d.parent / "evil.html").exists() and not (d / "evil.html").exists()  # '..' path dropped
    assert (d / "abs.html").read_text() == "y"  # leading '/' normalised to site-root-relative


# --------------------------------------------------------------------------- task generation


def test_validate_tasks_filters_uncheckable_tasks(site):
    files = rewrite.site_files(store.site_dir("demo", "v0"))
    raw = [
        {
            "id": "ok answer",
            "kind": "answer",
            "prompt": "H100 price?",
            "expected_answer": "$3.95/hr",
            "answer_aliases": ["3.95"],
            "trap": "canvas",
        },
        {"kind": "answer", "prompt": "made up", "expected_answer": "$99.99"},  # not on the site
        {"kind": "url", "prompt": "docs", "expected_url_pattern": "^docs/?"},  # docs/index.html exists
        {"kind": "url", "prompt": "blog", "expected_url_pattern": "^blog"},  # no such page
        {
            "kind": "action",
            "prompt": "join",
            "expected_event": "api/waitlist_submit",
            "expected_event_match": {"email": "agent@example.com"},
        },
        {"kind": "action", "prompt": "buy", "expected_event": "checkout"},  # endpoint not in site
        {"kind": "bogus", "prompt": "x"},
    ]
    tasks = task_gen.validate_tasks(raw, files, n=8)
    assert [t.kind.value for t in tasks] == ["answer", "url", "action"]
    assert tasks[0].id == "ok_answer" and tasks[2].expected_event == "waitlist_submit"


def test_generate_tasks_with_patched_chat(site, monkeypatch):
    reply = {
        "tasks": [
            {"id": "t1", "kind": "answer", "prompt": "price?", "expected_answer": "3.95"},
            {"id": "t2", "kind": "url", "prompt": "pricing", "expected_url_pattern": r"pricing\.html"},
        ]
    }
    seen = {}

    def fake_chat(spec, messages, **kw):
        seen["user"] = messages[-1].content
        return LLMResponse(text=json.dumps(reply), usage=Usage())

    monkeypatch.setattr(task_gen, "chat", fake_chat)
    tasks = task_gen.generate_tasks("demo", "v0", n=2)
    assert [t.id for t in tasks] == ["t1", "t2"]
    assert "waitlist_submit" in seen["user"] and "pricing.html" in seen["user"]

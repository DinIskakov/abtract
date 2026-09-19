#!/usr/bin/env python
"""Seed the store with plausible fake data so the dashboard can be built before real swarm runs exist.

    uv run python scripts/seed_fake_data.py [--site demo] [--src demo_site/v0] [--data-dir ./data] [--seed 42] [--keep]

Writes site "demo" with versions v0, v1, v2 (copies --src if it exists, else a small stub site), and for each version
one RunSummary made of 3 models x 3 agent kinds x 8 tasks Episodes with step traces, token usage, cost, judge
verdicts and failure modes. Success improves across versions; v1/v2 carry optimizer notes and changed_files.
All RunSummary metrics are computed from the episodes, so the dashboard's numbers are internally consistent.

Deterministic for a given --seed. Importable: `seed_fake_data.seed(site_id="demo")` returns the run ids.
"""

from __future__ import annotations

import argparse
import random
import shutil
import struct
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import store  # noqa: E402
from app.models.registry import get_model  # noqa: E402
from app.schemas import (  # noqa: E402
    Action,
    AgentKind,
    Episode,
    FailureMode,
    MetricBlock,
    RunSummary,
    SiteEvent,
    SiteVersion,
    Step,
    Task,
    TaskKind,
    Usage,
)

MODEL_IDS = ["deepseek-v4.1-flash", "glm-5.3-flash", "kimi-k3"]
AGENT_KINDS = [AgentKind.text, AgentKind.dom, AgentKind.vision]
VERSIONS = ["v0", "v1", "v2"]

# --------------------------------------------------------------------------- tasks (a "Modal-like" demo site)

TASKS: list[Task] = [
    Task(
        id="task_h100_price",
        kind=TaskKind.answer,
        prompt="What does an H100 GPU cost per hour on this platform?",
        expected_answer="$3.95/hr",
        answer_aliases=["3.95", "$3.95", "3.95/hr"],
        trap="price_in_image",
        tags=["pricing"],
    ),
    Task(
        id="task_quickstart",
        kind=TaskKind.url,
        prompt="Open the Python SDK quickstart page in the docs.",
        expected_url_pattern=r"docs/quickstart(\.html)?$",
        trap="hover_menu",
        tags=["nav"],
    ),
    Task(
        id="task_waitlist",
        kind=TaskKind.action,
        prompt="Join the GPU waitlist with the email agent@example.com.",
        expected_event="waitlist_submit",
        expected_event_match={"email": "agent@example.com"},
        trap="hidden_field",
        tags=["form"],
    ),
    Task(
        id="task_timeout",
        kind=TaskKind.answer,
        prompt="What is the maximum timeout for a single function call?",
        expected_answer="24 hours",
        answer_aliases=["24h", "86400 seconds", "24 hrs"],
        trap="accordion",
        tags=["docs"],
    ),
    Task(
        id="task_changelog",
        kind=TaskKind.url,
        prompt="Find the product changelog.",
        expected_url_pattern=r"changelog(\.html)?$",
        trap="footer_only_link",
        tags=["nav"],
    ),
    Task(
        id="task_contact",
        kind=TaskKind.action,
        prompt="Use the contact form to ask about enterprise pricing.",
        expected_event="contact_submit",
        expected_event_match={"topic": "enterprise"},
        trap="multi_step_form",
        tags=["form"],
    ),
    Task(
        id="task_regions",
        kind=TaskKind.answer,
        prompt="Which cloud regions are GPUs available in?",
        expected_answer="us-east, us-west, eu-west",
        answer_aliases=["us-east us-west eu-west"],
        trap="lazy_loaded",
        tags=["docs"],
    ),
    Task(
        id="task_status",
        kind=TaskKind.url,
        prompt="Go to the system status page.",
        expected_url_pattern=r"status(\.html)?$",
        trap="modal_overlay",
        tags=["nav"],
    ),
]

# Which version fixes which trap. Traps not listed are only partially mitigated.
FIXED_IN = {
    "price_in_image": "v1",
    "hidden_field": "v1",
    "footer_only_link": "v1",
    "hover_menu": "v1",
    "accordion": "v2",
    "multi_step_form": "v2",
    "lazy_loaded": "v2",
    "modal_overlay": "v2",
}
JS_TRAPS = {"hover_menu", "accordion", "lazy_loaded", "modal_overlay", "multi_step_form"}

VERSION_NOTES = {
    "v1": (
        "Round 1 optimizer pass. Agents failed most on things only a human with a mouse can see: the H100 price "
        "was baked into a PNG (text agents never saw it), the docs menu only opened on hover, and the waitlist form "
        "carried a hidden honeypot field that agents dutifully filled in, causing the submit to be rejected. "
        "Changes: rendered pricing as a real HTML table with the price in text; replaced the hover-only docs menu "
        "with plain links; removed the honeypot and added an explicit label to the email field; promoted the "
        "Changelog link from the footer into the top navigation."
    ),
    "v2": (
        "Round 2 optimizer pass. Remaining failures came from content that is not in the initial HTML: the timeout "
        "limit was inside a collapsed accordion, regions were injected by JavaScript after a delay, the status page "
        "was covered by a newsletter modal, and the contact form was split into three wizard steps. "
        "Changes: accordions now render expanded with their content in the DOM; region list is server-rendered; "
        "newsletter modal removed; contact form collapsed to a single page with a 'topic' select. Also added "
        "descriptive <title>s and skip links so text agents can orient faster."
    ),
}

STUB_FILES = {
    "index.html": """<!doctype html><html><head><meta charset="utf-8"><title>Modalish - Serverless GPUs</title>
<link rel="stylesheet" href="style.css"></head><body>
<nav><a href="index.html">Home</a> <a href="pricing.html">Pricing</a> <a href="docs/index.html">Docs</a>
<a href="waitlist.html">Waitlist</a> <a href="contact.html">Contact</a></nav>
<main><h1>Run anything on GPUs in seconds</h1>
<p>Serverless containers with H100s, A100s and more. Pay per second.</p>
<a class="cta" href="waitlist.html">Join the waitlist</a></main>
<footer><a href="changelog.html">Changelog</a> <a href="status.html">Status</a></footer>
</body></html>""",
    "pricing.html": """<!doctype html><html><head><meta charset="utf-8"><title>Pricing</title>
<link rel="stylesheet" href="style.css"></head><body>
<nav><a href="index.html">Home</a> <a href="pricing.html">Pricing</a> <a href="docs/index.html">Docs</a></nav>
<main><h1>Pricing</h1><img src="pricing-table.png" alt="GPU pricing table"></main>
</body></html>""",
    "docs/index.html": """<!doctype html><html><head><meta charset="utf-8"><title>Docs</title>
<link rel="stylesheet" href="../style.css"></head><body>
<nav><a href="../index.html">Home</a> <span class="menu" data-hover="true">Guides</span></nav>
<main><h1>Documentation</h1><details><summary>Limits</summary><p>Maximum function timeout: 24 hours.</p></details>
<div id="regions" data-lazy="regions.json"></div></main>
</body></html>""",
    "docs/quickstart.html": """<!doctype html><html><head><meta charset="utf-8"><title>Python SDK quickstart</title>
<link rel="stylesheet" href="../style.css"></head><body><main><h1>Python SDK quickstart</h1>
<pre>pip install modalish</pre></main></body></html>""",
    "waitlist.html": """<!doctype html><html><head><meta charset="utf-8"><title>Waitlist</title>
<link rel="stylesheet" href="style.css"></head><body><main><h1>Join the GPU waitlist</h1>
<form method="post" action="api/waitlist_submit">
<input name="email" placeholder="you@company.com"><input name="website" class="hp" tabindex="-1">
<button type="submit">Join</button></form></main></body></html>""",
    "contact.html": """<!doctype html><html><head><meta charset="utf-8"><title>Contact</title>
<link rel="stylesheet" href="style.css"></head><body><main><h1>Contact sales</h1>
<form method="post" action="api/contact_submit" data-steps="3">
<input name="name" placeholder="Name"><input name="email" placeholder="Email">
<select name="topic"><option value="support">Support</option><option value="enterprise">Enterprise pricing</option></select>
<textarea name="message"></textarea><button type="submit">Send</button></form></main></body></html>""",
    "changelog.html": """<!doctype html><html><head><meta charset="utf-8"><title>Changelog</title>
<link rel="stylesheet" href="style.css"></head><body><main><h1>Changelog</h1><ul><li>2026-09-01: H100 support</li></ul></main></body></html>""",
    "status.html": """<!doctype html><html><head><meta charset="utf-8"><title>Status</title>
<link rel="stylesheet" href="style.css"></head><body><div class="modal">Subscribe to our newsletter!</div>
<main><h1>System status</h1><p>All systems operational.</p></main></body></html>""",
    "thanks.html": """<!doctype html><html><head><meta charset="utf-8"><title>Thanks</title>
<link rel="stylesheet" href="style.css"></head><body><main><h1>Thanks!</h1><p>We got your submission.</p></main></body></html>""",
    "style.css": """body{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#e8e8e8}
nav{padding:1rem;border-bottom:1px solid #222}main{padding:2rem;max-width:60rem}.cta{background:#3987e5;color:#fff;padding:.6rem 1rem}
.hp{position:absolute;left:-9999px}.modal{position:fixed;inset:0;background:rgba(0,0,0,.8);display:grid;place-items:center}
""",
}

# Edits applied on top of the previous version's files (path -> list of (old, new) substitutions).
VERSION_EDITS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "v1": {
        "pricing.html": [
            (
                '<img src="pricing-table.png" alt="GPU pricing table">',
                "<table><tr><th>GPU</th><th>Price</th></tr><tr><td>H100</td><td>$3.95/hr</td></tr>"
                "<tr><td>A100</td><td>$2.10/hr</td></tr></table>",
            )
        ],
        "docs/index.html": [
            (
                '<span class="menu" data-hover="true">Guides</span>',
                '<a href="quickstart.html">Python SDK quickstart</a>',
            )
        ],
        "waitlist.html": [
            (
                '<input name="email" placeholder="you@company.com"><input name="website" class="hp" tabindex="-1">',
                '<label>Email <input name="email" placeholder="you@company.com"></label>',
            )
        ],
        "index.html": [
            (
                '<a href="waitlist.html">Waitlist</a> <a href="contact.html">Contact</a></nav>',
                '<a href="waitlist.html">Waitlist</a> <a href="contact.html">Contact</a> '
                '<a href="changelog.html">Changelog</a></nav>',
            )
        ],
    },
    "v2": {
        "docs/index.html": [
            (
                "<details><summary>Limits</summary><p>Maximum function timeout: 24 hours.</p></details>",
                "<h2>Limits</h2><p>Maximum function timeout: 24 hours.</p>",
            ),
            (
                '<div id="regions" data-lazy="regions.json"></div>',
                "<h2>Regions</h2><p>GPUs are available in us-east, us-west and eu-west.</p>",
            ),
        ],
        "status.html": [('<div class="modal">Subscribe to our newsletter!</div>', "")],
        "contact.html": [('data-steps="3"', "")],
        "index.html": [
            (
                '<a href="index.html">Home</a>',
                '<a href="#main" class="skip">Skip to content</a> <a href="index.html">Home</a>',
            )
        ],
    },
}

THOUGHTS = {
    "start": [
        "The task asks about {topic}; I'll start from the homepage and look for a relevant link.",
        "Landing page loaded. Scanning the navigation for '{topic}'.",
    ],
    "nav": [
        "There is a '{link}' link in the nav, that's probably where the {topic} lives.",
        "Following the '{link}' link.",
        "The page mentions {topic} further down; navigating to '{link}'.",
    ],
    "scroll": [
        "Nothing relevant above the fold; scrolling to see more.",
        "Let me scroll down to find the {topic} section.",
    ],
    "stuck": [
        "I can't find any mention of {topic} in the page text. Trying another section.",
        "The menu doesn't seem to expand. Trying the footer instead.",
        "The element I clicked did nothing observable. Retrying with a different element.",
    ],
    "answer": ["Found it: the page says '{answer}'. Reporting that.", "The {topic} is clearly stated as '{answer}'."],
    "submit": ["All required fields are filled in; submitting the form.", "Form looks complete. Clicking submit."],
    "give_up": [
        "I've explored the whole site and cannot find {topic}. Giving up.",
        "After {n} steps I still can't reach the {topic}; giving up so I don't burn more budget.",
    ],
}

PAGE_FLOW = {
    "task_h100_price": ["", "pricing.html"],
    "task_quickstart": ["", "docs/index.html", "docs/quickstart.html"],
    "task_waitlist": ["", "waitlist.html"],
    "task_timeout": ["", "docs/index.html"],
    "task_changelog": ["", "changelog.html"],
    "task_contact": ["", "contact.html"],
    "task_regions": ["", "docs/index.html"],
    "task_status": ["", "status.html"],
}
TOPIC = {
    "task_h100_price": ("H100 price", "Pricing", "$3.95/hr"),
    "task_quickstart": ("quickstart", "Docs", "docs/quickstart.html"),
    "task_waitlist": ("waitlist form", "Waitlist", "submitted"),
    "task_timeout": ("timeout limit", "Docs", "24 hours"),
    "task_changelog": ("changelog", "Changelog", "changelog.html"),
    "task_contact": ("contact form", "Contact", "submitted"),
    "task_regions": ("GPU regions", "Docs", "us-east, us-west, eu-west"),
    "task_status": ("status page", "Status", "status.html"),
}
WRONG_ANSWERS = {
    "task_h100_price": ["$2.10/hr", "I could not find the price", "$4.50 per hour"],
    "task_timeout": ["60 minutes", "1 hour", "not specified"],
    "task_regions": ["us-east only", "us-east, us-west", "no regions are listed"],
}


# --------------------------------------------------------------------------- tiny PNG writer (no PIL dependency)


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


# --------------------------------------------------------------------------- metrics (kept local: app.metrics is built concurrently)


def compute_block(eps: list[Episode]) -> MetricBlock:
    if not eps:
        return MetricBlock()
    n = len(eps)
    fm = Counter(e.failure_mode for e in eps if e.failure_mode)
    return MetricBlock(
        episodes=n,
        success_rate=sum(1 for e in eps if e.success) / n,
        avg_steps=sum(e.n_steps for e in eps) / n,
        avg_duration_s=sum(e.duration_s for e in eps) / n,
        avg_cost_usd=sum(e.cost_usd for e in eps) / n,
        total_cost_usd=sum(e.cost_usd for e in eps),
        failure_modes=dict(sorted(fm.items())),
    )


def _group(eps: list[Episode], key) -> dict[str, MetricBlock]:
    groups: dict[str, list[Episode]] = {}
    for e in eps:
        groups.setdefault(key(e), []).append(e)
    return {k: compute_block(v) for k, v in sorted(groups.items())}


# --------------------------------------------------------------------------- site files


def _write_site_files(site_id: str, version: str, src: Path | None, prev_version: str | None) -> list[str]:
    dst = store.site_dir(site_id, version)
    if dst.exists():
        shutil.rmtree(dst)
    if prev_version:
        shutil.copytree(store.site_dir(site_id, prev_version), dst)
    elif src and src.is_dir():
        shutil.copytree(src, dst)
    else:
        for rel, text in STUB_FILES.items():
            p = dst / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
    changed: list[str] = []
    for rel, subs in VERSION_EDITS.get(version, {}).items():
        p = dst / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"<!doctype html><title>{rel}</title><p>Added by the optimizer in {version}.</p>")
            changed.append(rel)
            continue
        text = p.read_text()
        new = text
        for old, rep in subs:
            new = new.replace(old, rep) if old in new else new + f"\n<!-- {version}: {rep[:60]} -->\n"
        if new != text:
            p.write_text(new)
            changed.append(rel)
    if prev_version is None:
        changed = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
    return changed


# --------------------------------------------------------------------------- episodes


def _success_prob(version: str, task: Task, model_id: str, agent: AgentKind) -> float:
    base = {"v0": 0.30, "v1": 0.55, "v2": 0.68}[version]
    fixed_at = FIXED_IN.get(task.trap or "", "v2")
    if VERSIONS.index(version) >= VERSIONS.index(fixed_at):
        base += 0.18
    elif version != "v0":
        base += 0.04
    base += {"deepseek-v4.1-flash": -0.08, "glm-5.3-flash": 0.0, "kimi-k3": 0.10}[model_id]
    if agent == AgentKind.text and task.trap in JS_TRAPS and VERSIONS.index(version) < VERSIONS.index(fixed_at):
        base -= 0.22
    if agent == AgentKind.vision and task.trap == "price_in_image":
        base += 0.25
    if agent == AgentKind.vision:
        base -= 0.03
    return max(0.03, min(0.97, base))


def _pick_failure(rng: random.Random, task: Task) -> FailureMode:
    primary: FailureMode = {"answer": "wrong_answer", "url": "wrong_page", "action": "no_event"}[task.kind.value]
    roll = rng.random()
    if roll < 0.50:
        return primary
    if roll < 0.68:
        return "max_steps"
    if roll < 0.84:
        return "gave_up"
    if roll < 0.94:
        return "error"
    return "timeout"


def _make_episode(
    rng: random.Random,
    run_id: str,
    site_id: str,
    version: str,
    task: Task,
    model_id: str,
    agent: AgentKind,
    started_at: float,
    success: bool,
    failure: FailureMode | None,
) -> Episode:
    topic, link, answer = TOPIC[task.id]
    flow = PAGE_FLOW[task.id]
    base_url = f"http://localhost:8000/s/{site_id}/{version}/"
    if success:
        n_steps = rng.randint(len(flow) + 1, len(flow) + 4)
    elif failure == "max_steps":
        n_steps = task.max_steps
    elif failure in ("error", "timeout"):
        n_steps = rng.randint(1, 5)
    else:
        n_steps = rng.randint(3, 10)

    ep_id = f"ep_{rng.getrandbits(40):010x}"
    steps: list[Step] = []
    usage = Usage()
    page_i = 0
    t = 0
    lat_mult = {AgentKind.text: 0.7, AgentKind.dom: 1.0, AgentKind.vision: 1.6}[agent]
    obs_mult = {AgentKind.text: 1.0, AgentKind.dom: 1.4, AgentKind.vision: 0.5}[agent]
    shot_dir = store.screenshot_dir(run_id, ep_id) if agent == AgentKind.vision else None
    for i in range(n_steps):
        url = base_url + flow[min(page_i, len(flow) - 1)]
        last = i == n_steps - 1
        err = None
        if last and success:
            if task.kind == TaskKind.action:
                thought, action = rng.choice(THOUGHTS["submit"]), Action(type="click", id=rng.randint(3, 12))
            else:
                thought = rng.choice(THOUGHTS["answer"]).format(topic=topic, answer=answer)
                action = Action(
                    type="answer", text=answer if task.kind == TaskKind.answer else f"Done, I am on {answer}"
                )
        elif last and failure == "gave_up":
            thought = rng.choice(THOUGHTS["give_up"]).format(topic=topic, n=n_steps)
            action = Action(type="give_up", reason=f"could not locate {topic}")
        elif last and failure in ("wrong_answer", "wrong_page", "no_event"):
            if failure == "wrong_answer":
                wrong = rng.choice(WRONG_ANSWERS.get(task.id, ["unknown"]))
                thought, action = f"I think the {topic} is '{wrong}'.", Action(type="answer", text=wrong)
            elif failure == "wrong_page":
                thought, action = (
                    "This looks like the right page.",
                    Action(type="answer", text="I am on the requested page"),
                )
            else:
                thought, action = "Submitted the form; task complete.", Action(type="answer", text="Form submitted")
        elif last and failure in ("error", "timeout"):
            thought = "Clicking the link should load the page."
            action = Action(type="click", id=rng.randint(1, 20))
            err = (
                "TimeoutError: page did not finish loading within 60s"
                if failure == "timeout"
                else rng.choice(
                    [
                        "Element #7 not found in current observation",
                        "net::ERR_CONNECTION_RESET",
                        "LLM returned invalid JSON: Expecting value: line 1 column 1",
                    ]
                )
            )
        elif i == 0:
            thought, action = rng.choice(THOUGHTS["start"]).format(topic=topic), Action(type="navigate", url=url)
        elif page_i < len(flow) - 1 and rng.random() < 0.7:
            page_i += 1
            thought = rng.choice(THOUGHTS["nav"]).format(topic=topic, link=link)
            action = (
                Action(type="click", id=rng.randint(1, 9))
                if agent != AgentKind.text
                else Action(type="navigate", url=flow[page_i] or "index.html")
            )
        elif rng.random() < 0.5:
            thought, action = (
                rng.choice(THOUGHTS["scroll"]).format(topic=topic),
                Action(type="scroll", direction="down"),
            )
        else:
            thought = rng.choice(THOUGHTS["stuck"]).format(topic=topic)
            action = rng.choice(
                [
                    Action(type="click", id=rng.randint(1, 20)),
                    Action(type="back"),
                    Action(type="type", id=rng.randint(1, 9), text="agent@example.com"),
                ]
            )
            if rng.random() < 0.15:
                err = "Element not found"
        obs = int(rng.randint(1800, 6000) * obs_mult)
        latency = int(rng.randint(900, 3200) * lat_mult)
        shot = None
        if shot_dir is not None:
            shot = shot_dir / f"{i:02d}.png"
            shade = (30 + i * 12, 40 + (i * 23) % 60, 70 + (i * 37) % 90)
            shot.write_bytes(_png(160, 100, shade))
        steps.append(
            Step(
                index=i,
                url=url,
                observation_chars=obs,
                thought=thought,
                action=action,
                latency_ms=latency,
                error=err,
                screenshot_path=str(shot) if shot else None,
            )
        )
        usage.add(
            Usage(
                input_tokens=obs // 4 + 700,
                output_tokens=rng.randint(50, 220),
                llm_calls=1,
                llm_latency_ms=int(latency * 0.8),
            )
        )
        t += latency

    spec = get_model(model_id)
    final_url = steps[-1].url if steps else base_url
    if success and task.kind == TaskKind.url:
        final_url = base_url + flow[-1]
    judge = {
        True: {
            "answer": f"Answer '{answer}' matches expected.",
            "url": f"Final URL matches /{flow[-1]}$.",
            "action": f"SiteEvent '{task.expected_event}' recorded with matching payload.",
        }[task.kind.value],
        False: {
            "wrong_answer": "Answer does not match expected value or aliases.",
            "wrong_page": f"Final URL {final_url} does not match the expected pattern.",
            "no_event": f"No '{task.expected_event}' event was recorded for this episode.",
            "max_steps": f"Hit the {task.max_steps}-step budget without finishing.",
            "gave_up": "Agent declared give_up.",
            "error": "Agent crashed: " + (steps[-1].error or "unknown error"),
            "timeout": "Episode exceeded the timeout.",
        }.get(failure or "error", "Failed."),
    }[success]
    return Episode(
        id=ep_id,
        run_id=run_id,
        site_id=site_id,
        site_version=version,
        task_id=task.id,
        agent_kind=agent,
        model_id=model_id,
        started_at=started_at,
        finished_at=started_at + t / 1000 + rng.uniform(0.5, 3.0),
        steps=steps,
        final_answer=steps[-1].action.text if steps and steps[-1].action.type == "answer" else None,
        final_url=final_url,
        usage=usage,
        cost_usd=round(usage.cost_usd(spec), 6),
        success=success,
        judge_reason=judge,
        failure_mode=None if success else failure,
        error=steps[-1].error if (not success and failure in ("error", "timeout")) else None,
    )


# --------------------------------------------------------------------------- main entry


def seed(
    site_id: str = "demo",
    src: Path | None = None,
    *,
    seed: int = 42,
    clean: bool = True,
    models: list[str] = MODEL_IDS,
    agents: list[AgentKind] = AGENT_KINDS,
    verbose: bool = True,
) -> dict[str, str]:
    """Write the fake dataset into the current store. Returns {version: run_id}."""
    rng = random.Random(seed)
    if clean:
        # Only touch what we are about to rewrite: the v0..v2 version dirs (done in _write_site_files), their event
        # logs and our own run_fake_* runs. Other versions/runs of this site (real swarm output) are left alone.
        for version in VERSIONS:
            store.events_path(site_id, version).unlink(missing_ok=True)
        for r in store.list_runs():
            if r.site_id == site_id and r.run_id.startswith("run_fake_"):
                shutil.rmtree(store.run_dir(r.run_id), ignore_errors=True)

    now = time.time()
    run_ids: dict[str, str] = {}
    prev: str | None = None
    for vi, version in enumerate(VERSIONS):
        changed = _write_site_files(site_id, version, src, prev)
        created = now - (len(VERSIONS) - vi) * 3600
        store.register_version(
            SiteVersion(
                site_id=site_id,
                version=version,
                parent=prev,
                created_at=created,
                notes=VERSION_NOTES.get(version, ""),
                changed_files=changed,
            )
        )
        run_id = f"run_fake_{version}"
        run_started = created + 300
        episodes: list[Episode] = []
        events: list[SiteEvent] = []
        k = 0
        for task in TASKS:
            for model_id in models:
                for agent in agents:
                    ok = rng.random() < _success_prob(version, task, model_id, agent)
                    fail = None if ok else _pick_failure(rng, task)
                    ep = _make_episode(
                        rng, run_id, site_id, version, task, model_id, agent, run_started + k * 4.0, ok, fail
                    )
                    store.save_episode(ep)
                    episodes.append(ep)
                    if task.kind == TaskKind.action and (ok or fail == "wrong_answer"):
                        payload = dict(task.expected_event_match) if ok else {"email": "", "topic": "support"}
                        payload.setdefault("email", "agent@example.com")
                        events.append(
                            SiteEvent(
                                name=task.expected_event or "submit",
                                payload=payload,
                                site_id=site_id,
                                version=version,
                                episode_id=ep.id,
                                ts=ep.finished_at or ep.started_at,
                            )
                        )
                    k += 1
        for ev in sorted(events, key=lambda e: e.ts):
            store.append_event(ev)
        task_by_id = {t.id: t for t in TASKS}
        run = RunSummary(
            run_id=run_id,
            site_id=site_id,
            site_version=version,
            site_url=f"http://localhost:8000/s/{site_id}/{version}/",
            created_at=run_started,
            finished_at=max(e.finished_at or e.started_at for e in episodes),
            tasks=TASKS,
            model_ids=list(models),
            agent_kinds=list(agents),
            overall=compute_block(episodes),
            per_model=_group(episodes, lambda e: e.model_id),
            per_agent=_group(episodes, lambda e: e.agent_kind.value),
            per_task=_group(episodes, lambda e: e.task_id),
            per_trap=_group(episodes, lambda e: task_by_id[e.task_id].trap or "none"),
        )
        store.save_run(run)
        run_ids[version] = run_id
        if verbose:
            print(
                f"{site_id}/{version}: run {run_id}  episodes={run.overall.episodes}  "
                f"success={run.overall.success_rate:.0%}  avg_steps={run.overall.avg_steps:.1f}  "
                f"avg_cost=${run.overall.avg_cost_usd:.4f}  events={len(events)}  changed_files={len(changed)}"
            )
        prev = version
    store.commit()
    return run_ids


def main(argv: list[str] | None = None) -> int:
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default="demo")
    ap.add_argument("--src", default=str(ROOT / "demo_site" / "v0"), help="site dir to copy for v0 (stub if missing)")
    ap.add_argument("--data-dir", default=None, help="override ABTRACT_DATA_DIR")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--keep", action="store_true", help="do not wipe existing data for this site first")
    args = ap.parse_args(argv)
    if args.data_dir:
        settings.data_dir = Path(args.data_dir)
    src = Path(args.src)
    print(f"seeding store at {store.root().resolve()} (site source: {src if src.is_dir() else 'built-in stub'})")
    seed(args.site, src if src.is_dir() else None, seed=args.seed, clean=not args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())

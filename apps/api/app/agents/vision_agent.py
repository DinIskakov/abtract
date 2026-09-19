"""Vision agent: real headless Chromium; observes a viewport screenshot with a Set-of-Marks overlay (numbered boxes
over interactive elements) plus a compact text legend. Only what is on screen is numbered; `scroll` moves the
viewport. Screenshots are saved to screenshot_dir/NN.png (defaulting to the store's layout) and recorded on the
Step as a path relative to settings.data_dir."""

from __future__ import annotations

from typing import Any

from app import store
from app.config import settings
from app.schemas import Action, AgentKind, Episode

from .base import ActionError, BaseAgent, Observation
from .browser import BrowserSession, describe_element


class VisionAgent(BaseAgent):
    kind = AgentKind.vision

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.browser: BrowserSession | None = None
        self.notes: list[str] = []

    def start(self, site_url: str, episode: Episode) -> None:
        if self.screenshot_dir is None:
            self.screenshot_dir = store.screenshot_dir(self.run_id, episode.id)
        self.browser = BrowserSession(episode.id, site_url, nav_timeout_ms=settings.step_timeout_s * 1000)
        self.browser.goto(site_url)

    def current_url(self) -> str:
        return self.browser.url if self.browser else self.site_url

    def healthy(self) -> bool:
        return self.browser is not None and self.browser.healthy()

    def close(self) -> None:
        if self.browser:
            self.browser.close()

    def observe(self) -> Observation:
        assert self.browser is not None and self.episode is not None
        data = self.browser.observe(viewport_only=True)
        elements: list[dict[str, Any]] = data.get("elements") or []
        png = self.browser.screenshot_with_marks(elements)
        rel_path = None
        target = self.screenshot_rel_path(len(self.episode.steps))
        if target is not None:
            path, rel_path = target
            try:
                path.write_bytes(png)
            except OSError:
                rel_path = None
        y0 = int(data.get("scrollY") or 0)
        vh = int(data.get("vh") or 800)
        height = int(data.get("scrollHeight") or vh)
        lines = [f"URL: {data.get('url') or self.browser.url}"]
        if data.get("title"):
            lines.append(f"Title: {data['title']}")
        for d in self.browser.take_dialogs():
            lines.append(f"Dialog (auto-accepted): {d}")
        for n in self.notes:
            lines.append(f"Note: {n}")
        self.notes = []
        below = height - (y0 + vh)
        pos = f"Viewport shows {y0}-{min(y0 + vh, height)} of {height}px"
        if below > 0:
            pos += f" ({below}px more below; scroll down to see it)"
        elif y0 > 0:
            pos += " (bottom of page)"
        lines.append(pos)
        if elements:
            lines.append("Numbered elements in the screenshot:")
            lines.extend(f"{e['id']}: {describe_element(e)}" for e in elements)
        else:
            lines.append("(no interactive elements in view; scroll or navigate)")
        return Observation(
            text="\n".join(lines),
            url=data.get("url") or self.browser.url,
            png_base64=BrowserSession.b64(png),
            screenshot_path=rel_path,
        )

    def act(self, action: Action) -> None:
        assert self.browser is not None
        b = self.browser
        t = action.type
        if t == "navigate":
            b.goto(self.check_origin(action.url or ""))
        elif t == "click":
            b.click(action.id)
        elif t == "type":
            b.fill(action.id, action.text or "")
        elif t == "select":
            b.select(action.id, action.value or "")
        elif t == "scroll":
            pos = b.scroll(action.direction or "down")
            if pos["after"] == pos["before"]:
                self.notes.append(
                    "already at the top of the page"
                    if action.direction == "up"
                    else "already at the bottom of the page; nothing further down"
                )
            b.page.wait_for_timeout(200)
        elif t == "back":
            b.back()
        else:
            raise ActionError(f"action {t} is not supported")

"""DOM agent: real headless Chromium; observes rendered visible text plus a numbered list of interactive elements
covering the whole page (not just the viewport). JavaScript runs, hidden elements are not seen."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.schemas import Action, AgentKind, Episode

from .base import SCROLL_OVERLAP, TEXT_CAP, ActionError, BaseAgent, Observation
from .browser import BrowserSession, describe_element


class DomAgent(BaseAgent):
    kind = AgentKind.dom

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.browser: BrowserSession | None = None
        self.offset = 0
        self.notes: list[str] = []

    def start(self, site_url: str, episode: Episode) -> None:
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
        assert self.browser is not None
        data = self.browser.observe(viewport_only=False)
        text: str = data.get("text") or "(page has no visible text)"
        elements: list[dict[str, Any]] = data.get("elements") or []
        header = [f"URL: {data.get('url') or self.browser.url}"]
        if data.get("title"):
            header.append(f"Title: {data['title']}")
        for d in self.browser.take_dialogs():
            header.append(f"Dialog (auto-accepted): {d}")
        for n in self.notes:
            header.append(f"Note: {n}")
        self.notes = []
        total = len(text)
        if total > TEXT_CAP:
            start = min(self.offset, max(0, total - TEXT_CAP))
            end = min(total, start + TEXT_CAP)
            self.offset = start
            more = " Use scroll down to see more." if end < total else " (end of page)"
            header.append(f"[Showing characters {start}-{end} of {total}.{more}]")
            window = text[start:end]
        else:
            self.offset = 0
            window = text
        import re

        ids_in_window = {int(m) for m in re.findall(r"\[(\d+)\]", window)}
        lines = [f"[{e['id']}] {describe_element(e)}" for e in elements if e["id"] in ids_in_window]
        n_outside = sum(1 for e in elements if e["id"] not in ids_in_window)
        body = "\n".join(header) + "\n\n" + window
        if lines:
            body += '\n\nInteractive elements (use the number as "id"):\n' + "\n".join(lines)
        if n_outside:
            body += f"\n({n_outside} more interactive elements outside this text window; scroll to see them)"
        elif not elements:
            body += "\n\n(no interactive elements on this page)"
        return Observation(text=body, url=data.get("url") or self.browser.url)

    def act(self, action: Action) -> None:
        assert self.browser is not None
        b = self.browser
        t = action.type
        if t == "navigate":
            b.goto(self.check_origin(action.url or ""))
            self.offset = 0
        elif t == "click":
            before = b.url
            b.click(action.id)
            if b.url != before:
                self.offset = 0
        elif t == "type":
            b.fill(action.id, action.text or "")
        elif t == "select":
            b.select(action.id, action.value or "")
        elif t == "scroll":
            total = len(b.last.get("text") or "") if b.last else 0
            pos = b.scroll(action.direction or "down")
            if action.direction == "up":
                if self.offset == 0 and pos["before"] == 0:
                    self.notes.append("already at the top of the page")
                self.offset = max(0, self.offset - (TEXT_CAP - SCROLL_OVERLAP))
            else:
                if self.offset + TEXT_CAP >= total:
                    if pos["after"] == pos["before"]:
                        self.notes.append(
                            "already at the bottom; the whole page text is shown above, scrolling reveals nothing new"
                        )
                    else:
                        self.notes.append("scrolled the browser; the whole page text was already shown, nothing new")
                else:
                    self.offset = min(self.offset + (TEXT_CAP - SCROLL_OVERLAP), max(0, total - TEXT_CAP))
        elif t == "back":
            b.back()
            self.offset = 0
        else:
            raise ActionError(f"action {t} is not supported")

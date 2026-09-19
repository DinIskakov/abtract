"""Text agent: plain HTTP via httpx, HTML -> readable text with numbered interactive elements. No JavaScript.

What it sees is what is in the HTML: hidden (display:none) text is included on purpose - that is one of the traps
we measure. Forms are submitted the way a JS-less browser would (method/action/form-encoding), links are fetched,
`back` pops a history stack, `scroll` pages through long text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from abtract.config import settings
from abtract.schemas import Action, AgentKind, Episode

from .base import SCROLL_OVERLAP, TEXT_CAP, ActionError, BaseAgent, Observation

_ID_ATTR = "data-abtract-id"
_BLOCK = {
    "p", "div", "section", "article", "header", "footer", "nav", "main", "aside", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "table", "ul", "ol", "form", "fieldset", "blockquote", "pre", "details", "summary", "dl", "dt", "dd",
    "figure", "figcaption", "hr", "br", "address", "thead", "tbody", "tfoot", "label", "button", "select", "textarea",
    "option", "legend", "caption", "center", "body",
}
_SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object", "canvas", "video", "audio", "meta", "link", "title"}
_TEXT_INPUT_TYPES = {"text", "email", "password", "search", "tel", "url", "number", "date", "datetime-local", "month", "week", "time", "color", "range", ""}


@dataclass
class TextElement:
    id: int
    tag: Tag
    kind: str                      # link | field | checkbox | radio | select | submit | button | reset
    label: str = ""
    href: str | None = None
    options: list[tuple[str, str]] = field(default_factory=list)  # (value, text)


def _attr(tag: Tag, name: str) -> str:
    v = tag.get(name)
    if isinstance(v, list):
        v = " ".join(v)
    return (v or "").strip() if isinstance(v, str) else ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class TextAgent(BaseAgent):
    kind = AgentKind.text

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.client: httpx.Client | None = None
        self.url: str = ""
        self.status: int = 0
        self.content_type: str = ""
        self.raw_text: str = ""
        self.soup: BeautifulSoup | None = None
        self.elements: dict[int, TextElement] = {}
        self.values: dict[int, str] = {}       # typed values / selected options, by element id
        self.checked: dict[int, bool] = {}     # checkbox/radio state, by element id
        self.history: list[str] = []
        self.offset: int = 0                    # scroll window start (chars)
        self.notes: list[str] = []              # one-shot messages shown in the next observation

    # ------------------------------------------------------------------ environment hooks
    def start(self, site_url: str, episode: Episode) -> None:
        self.client = httpx.Client(
            headers={"X-Abtract-Episode": episode.id, "User-Agent": "abtract-text-agent/0.1 (+no-js)"},
            follow_redirects=True,
            timeout=min(settings.step_timeout_s, 60),
        )
        self.site_url = site_url
        self._load("GET", site_url)

    def current_url(self) -> str:
        return self.url or self.site_url

    def close(self) -> None:
        if self.client:
            self.client.close()

    def observe(self) -> Observation:
        text, listing = self._render()
        total = len(text)
        header = [f"URL: {self.url}"]
        if self.soup is not None and self.soup.title and self.soup.title.string:
            header.append(f"Title: {_clean(self.soup.title.string)}")
        if self.status and self.status != 200:
            header.append(f"HTTP status: {self.status}")
        for n in self.notes:
            header.append(f"Note: {n}")
        self.notes = []
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
        ids_in_window = {int(m) for m in re.findall(r"\[(\d+)\]", window)}
        lines = [ln for eid, ln in listing if eid in ids_in_window]
        body = "\n".join(header) + "\n\n" + window
        if lines:
            body += "\n\nInteractive elements (use the number as \"id\"):\n" + "\n".join(lines)
        elif self.elements:
            body += "\n\n(no interactive elements in this part of the page; scroll to find them)"
        else:
            body += "\n\n(no interactive elements on this page)"
        return Observation(text=body, url=self.url)

    def act(self, action: Action) -> None:
        t = action.type
        if t == "navigate":
            full = self.check_origin(action.url or "")
            self._push_history()
            self._load("GET", full)
        elif t == "click":
            self._click(self._get(action.id))
        elif t == "type":
            el = self._get(action.id)
            if el.kind in ("checkbox", "radio"):
                self.checked[el.id] = (action.text or "").strip().lower() in {"1", "true", "yes", "on", "checked", "y"}
            elif el.kind == "select":
                self._select(el, action.text or "")
            elif el.kind == "field":
                self.values[el.id] = action.text or ""
            else:
                raise ActionError(f"[{el.id}] is a {el.kind}, not a text field; you cannot type into it")
        elif t == "select":
            el = self._get(action.id)
            if el.kind != "select":
                raise ActionError(f"[{el.id}] is a {el.kind}, not a <select>")
            self._select(el, action.value or "")
        elif t == "scroll":
            total = len(self._render()[0])
            if action.direction == "up":
                if self.offset == 0:
                    self.notes.append("already at the top of the page")
                self.offset = max(0, self.offset - (TEXT_CAP - SCROLL_OVERLAP))
            else:
                if self.offset + TEXT_CAP >= total:
                    self.notes.append("already at the end of the page; there is nothing further down")
                else:
                    self.offset = min(self.offset + (TEXT_CAP - SCROLL_OVERLAP), max(0, total - TEXT_CAP))
        elif t == "back":
            if not self.history:
                raise ActionError("no previous page to go back to")
            prev = self.history.pop()
            self._load("GET", prev)
        else:
            raise ActionError(f"action {t} is not supported by the text agent")

    # ------------------------------------------------------------------ HTTP + parsing
    def _push_history(self) -> None:
        if self.url:
            self.history.append(self.url)

    def _load(self, method: str, url: str, data: list[tuple[str, str]] | None = None) -> None:
        assert self.client is not None
        if not urlparse(url).scheme:
            url = urljoin(self.url or self.site_url, url)
        if urlparse(url).netloc.lower() != urlparse(self.site_url).netloc.lower():
            raise ActionError(f"refused: {url} is not on this site's origin")
        form: dict[str, Any] = {}
        for k, v in data or []:
            if k in form:  # repeated names (checkbox groups) -> list
                form[k] = (form[k] if isinstance(form[k], list) else [form[k]]) + [v]
            else:
                form[k] = v
        try:
            if method == "POST":
                r = self.client.post(url, data=form)
            else:
                r = self.client.get(url, params=form or None)
        except httpx.HTTPError as e:
            raise ActionError(f"request to {url} failed: {type(e).__name__}: {e}") from e
        if urlparse(str(r.url)).netloc.lower() != urlparse(self.site_url).netloc.lower():
            raise ActionError(f"refused: redirect to {r.url} leaves the site's origin")
        self.url = str(r.url)
        self.status = r.status_code
        self.content_type = r.headers.get("content-type", "")
        self.raw_text = r.text
        self.values, self.checked, self.elements, self.offset = {}, {}, {}, 0
        self.soup = None
        if "html" in self.content_type or (not self.content_type and "<" in self.raw_text[:500]):
            self.soup = BeautifulSoup(self.raw_text, "lxml")
            self._enumerate()

    def _enumerate(self) -> None:
        """Assign ids to interactive elements in document order (stable for the lifetime of the page)."""
        assert self.soup is not None
        root = self.soup.body or self.soup
        n = 0
        for tag in root.find_all(["a", "input", "textarea", "select", "button"]):
            if any(p.name in _SKIP for p in tag.parents):
                continue
            if tag.has_attr("disabled"):
                continue
            name = tag.name
            el: TextElement | None = None
            if name == "a":
                href = _attr(tag, "href")
                if not href:
                    continue
                el = TextElement(0, tag, "link", href=href)
            elif name == "input":
                t = _attr(tag, "type").lower()
                if t == "hidden":
                    continue
                if t in ("submit", "image"):
                    el = TextElement(0, tag, "submit")
                elif t == "button":
                    el = TextElement(0, tag, "button")
                elif t == "reset":
                    el = TextElement(0, tag, "reset")
                elif t == "checkbox":
                    el = TextElement(0, tag, "checkbox")
                elif t == "radio":
                    el = TextElement(0, tag, "radio")
                elif t == "file":
                    continue
                else:
                    el = TextElement(0, tag, "field")
            elif name == "textarea":
                el = TextElement(0, tag, "field")
            elif name == "select":
                opts = []
                for o in tag.find_all("option"):
                    txt = _clean(o.get_text())
                    opts.append((o.get("value", txt) if o.has_attr("value") else txt, txt))
                el = TextElement(0, tag, "select", options=opts)
            elif name == "button":
                t = _attr(tag, "type").lower() or "submit"
                el = TextElement(0, tag, "submit" if t == "submit" else ("reset" if t == "reset" else "button"))
            if el is None:
                continue
            n += 1
            el.id = n
            tag[_ID_ATTR] = str(n)
            el.label = self._label_for(tag)
            self.elements[n] = el

    def _label_for(self, tag: Tag) -> str:
        assert self.soup is not None
        tid = _attr(tag, "id")
        if tid:
            lab = self.soup.find("label", attrs={"for": tid})
            if lab:
                return _clean(lab.get_text())
        parent_label = tag.find_parent("label")
        if parent_label:
            return _clean(parent_label.get_text())
        return _attr(tag, "aria-label") or _attr(tag, "title")

    # ------------------------------------------------------------------ rendering
    def _render(self) -> tuple[str, list[tuple[int, str]]]:
        """Return (page text with inline [id] markers, per-element detail lines)."""
        if self.soup is None:
            txt = self.raw_text
            if len(txt) > 60_000:
                txt = txt[:60_000] + "\n...(truncated)"
            return f"(non-HTML response, content-type {self.content_type or 'unknown'})\n{txt}", []
        out: list[str] = []
        self._walk(self.soup.body or self.soup, out)
        text = "".join(out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        listing = [(eid, self._describe(el)) for eid, el in self.elements.items()]
        return text, listing

    def _walk(self, node: Any, out: list[str]) -> None:
        if isinstance(node, Comment):
            return
        if isinstance(node, NavigableString):
            s = str(node)
            if node.find_parent("pre") is not None:
                out.append(s)
            elif s.strip():
                out.append(re.sub(r"\s+", " ", s))
            elif s and out and not out[-1][-1:].isspace():
                out.append(" ")  # keep the gap between inline elements
            return
        if not isinstance(node, Tag):
            return
        name = node.name
        if name in _SKIP:
            return
        block = name in _BLOCK
        if block:
            out.append("\n")
        if name == "hr":
            out.append("----\n")
            return
        if name == "br":
            return
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            out.append("#" * int(name[1]) + " ")
        elif name == "li":
            out.append("- ")
        elif name in ("td", "th"):
            out.append(" | ")
        elif name == "img":
            alt = _attr(node, "alt")
            if alt:
                out.append(f"[image: {alt}]")
            return
        eid = node.get(_ID_ATTR)
        el = self.elements.get(int(eid)) if eid else None
        if el is not None:
            out.append(self._inline(el))
            if el.kind in ("field", "select"):
                if block:
                    out.append("\n")
                return
        for child in node.children:
            self._walk(child, out)
        if el is not None and el.kind in ("submit", "button", "reset"):
            out.append(")")
        if block:
            out.append("\n")

    def _inline(self, el: TextElement) -> str:
        tag = el.tag
        if el.kind == "link":
            return f"[{el.id}] "
        if el.kind in ("submit", "button", "reset"):
            lab = _attr(tag, "value") if tag.name == "input" else ""
            kind = "submit" if el.kind == "submit" else el.kind
            return f"[{el.id}] ({kind}: {lab}" if lab else f"[{el.id}] ({kind}: "
        if el.kind == "select":
            opts = " | ".join(t if t == v else f"{t} (value={v})" for v, t in el.options[:40])
            sel = self.values.get(el.id, self._default_select(el))
            return f"[{el.id}] <select name={_attr(tag, 'name') or '-'}> selected={sel!r} options: {opts}"
        if el.kind in ("checkbox", "radio"):
            chk = self.checked.get(el.id, tag.has_attr("checked"))
            return f"[{el.id}] <input type={el.kind} name={_attr(tag, 'name') or '-'} value={_attr(tag, 'value') or 'on'}{' checked' if chk else ''}>"
        # field
        t = (_attr(tag, "type").lower() or "text") if tag.name == "input" else "textarea"
        val = self.values.get(el.id, tag.get_text() if tag.name == "textarea" else _attr(tag, "value"))
        parts = [f"[{el.id}] <{'textarea' if tag.name == 'textarea' else 'input'}", f"type={t}"]
        if _attr(tag, "name"):
            parts.append(f"name={_attr(tag, 'name')}")
        if _attr(tag, "placeholder"):
            parts.append(f'placeholder="{_attr(tag, "placeholder")}"')
        if val:
            parts.append(f'value="{_clean(val)}"')
        if tag.has_attr("required"):
            parts.append("required")
        return " ".join(parts) + ">"

    def _describe(self, el: TextElement) -> str:
        tag = el.tag
        if el.kind == "link":
            txt = _clean(tag.get_text()) or _attr(tag, "aria-label") or _attr(tag, "title") or "(no text)"
            return f"[{el.id}] link \"{txt[:80]}\" -> {el.href}"
        if el.kind in ("submit", "button", "reset"):
            txt = _clean(tag.get_text()) or _attr(tag, "value") or _attr(tag, "aria-label") or "(no text)"
            form = self._form_of(tag)
            if form is None:
                where = "not in a form (does nothing without JavaScript)"
            else:
                where = f"submits form {form.get('method', 'get').upper()} {form.get('action') or '(this page)'}"
            return f"[{el.id}] {el.kind} \"{txt[:80]}\" - {where}"
        if el.kind == "select":
            sel = self.values.get(el.id, self._default_select(el))
            lab = f' label="{el.label}"' if el.label else ""
            return f"[{el.id}] select name={_attr(tag, 'name') or '-'}{lab} selected={sel!r} ({len(el.options)} options)"
        if el.kind in ("checkbox", "radio"):
            chk = self.checked.get(el.id, tag.has_attr("checked"))
            lab = f' label="{el.label}"' if el.label else ""
            return f"[{el.id}] {el.kind} name={_attr(tag, 'name') or '-'} value={_attr(tag, 'value') or 'on'}{lab} {'checked' if chk else 'unchecked'} (click to toggle)"
        t = (_attr(tag, "type").lower() or "text") if tag.name == "input" else "textarea"
        val = self.values.get(el.id, tag.get_text() if tag.name == "textarea" else _attr(tag, "value"))
        lab = f' label="{el.label}"' if el.label else ""
        ph = f' placeholder="{_attr(tag, "placeholder")}"' if _attr(tag, "placeholder") else ""
        req = " required" if tag.has_attr("required") else ""
        return f"[{el.id}] {t} field name={_attr(tag, 'name') or '-'}{lab}{ph}{req} value=\"{_clean(val)}\""

    def _default_select(self, el: TextElement) -> str:
        for o in el.tag.find_all("option"):
            if o.has_attr("selected"):
                return o.get("value", _clean(o.get_text())) if o.has_attr("value") else _clean(o.get_text())
        return el.options[0][0] if el.options else ""

    # ------------------------------------------------------------------ actions
    def _get(self, eid: int | None) -> TextElement:
        if eid is None or eid not in self.elements:
            known = ", ".join(str(k) for k in list(self.elements)[:30]) or "none"
            raise ActionError(f"no element with id {eid} on this page (ids on this page: {known})")
        return self.elements[eid]

    def _select(self, el: TextElement, value: str) -> None:
        v = value.strip()
        for ov, ot in el.options:
            if v == ov or v == ot:
                self.values[el.id] = ov
                return
        for ov, ot in el.options:
            if v.lower() in (ov.lower(), ot.lower()) or (v and v.lower() in ot.lower()):
                self.values[el.id] = ov
                return
        opts = " | ".join(t for _, t in el.options[:40])
        raise ActionError(f"[{el.id}] has no option {value!r}; options: {opts}")

    def _form_of(self, tag: Tag) -> Tag | None:
        assert self.soup is not None
        fid = _attr(tag, "form")
        if fid:
            f = self.soup.find("form", id=fid)
            if f is not None:
                return f
        return tag.find_parent("form")

    def _click(self, el: TextElement) -> None:
        tag = el.tag
        if el.kind == "link":
            href = el.href or ""
            low = href.lower()
            if low.startswith("javascript:"):
                raise ActionError(f"[{el.id}] is a javascript: link; the text agent cannot run scripts")
            if low.startswith(("mailto:", "tel:")):
                raise ActionError(f"[{el.id}] is a {low.split(':')[0]}: link, not a page")
            if href.startswith("#"):
                self.notes.append(f"clicked [{el.id}], an in-page anchor {href}; you are still on the same page")
                return
            full = self.check_origin(href)
            self._push_history()
            self._load("GET", full)
            return
        if el.kind == "checkbox":
            self.checked[el.id] = not self.checked.get(el.id, tag.has_attr("checked"))
            return
        if el.kind == "radio":
            name = _attr(tag, "name")
            for other in self.elements.values():
                if other.kind == "radio" and _attr(other.tag, "name") == name:
                    self.checked[other.id] = False
            self.checked[el.id] = True
            return
        if el.kind == "reset":
            form = self._form_of(tag)
            if form is not None:
                for other in self.elements.values():
                    if self._form_of(other.tag) is form:
                        self.values.pop(other.id, None)
                        self.checked.pop(other.id, None)
            return
        if el.kind == "button":
            raise ActionError(f"[{el.id}] is a type=button control that only works with JavaScript; nothing happened. Look for a submit button or a link instead")
        # submit
        form = self._form_of(tag)
        if form is None:
            raise ActionError(f"[{el.id}] is not inside a form; nothing happened")
        self._submit(form, tag)

    def _submit(self, form: Tag, submitter: Tag | None) -> None:
        payload: list[tuple[str, str]] = []
        for fld in form.find_all(["input", "textarea", "select", "button"]):
            if fld.has_attr("disabled"):
                continue
            name = _attr(fld, "name")
            if not name:
                continue
            eid = int(fld[_ID_ATTR]) if fld.has_attr(_ID_ATTR) else None
            if fld.name == "input":
                t = _attr(fld, "type").lower()
                if t in ("submit", "button", "image", "reset", "file"):
                    continue
                if t in ("checkbox", "radio"):
                    on = self.checked.get(eid, fld.has_attr("checked")) if eid is not None else fld.has_attr("checked")
                    if on:
                        payload.append((name, _attr(fld, "value") or "on"))
                    continue
                val = self.values.get(eid, _attr(fld, "value")) if eid is not None else _attr(fld, "value")
                payload.append((name, val))
            elif fld.name == "textarea":
                val = self.values.get(eid, fld.get_text()) if eid is not None else fld.get_text()
                payload.append((name, val))
            elif fld.name == "select":
                el = self.elements.get(eid) if eid is not None else None
                if el is not None:
                    payload.append((name, self.values.get(eid, self._default_select(el))))
        if submitter is not None and _attr(submitter, "name"):
            payload.append((_attr(submitter, "name"), _attr(submitter, "value")))
        method = _attr(form, "method").upper() or "GET"
        action = _attr(form, "action") or self.url
        full = self.check_origin(action)
        self._push_history()
        self._load("POST" if method == "POST" else "GET", full, payload)

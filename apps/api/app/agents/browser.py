"""Playwright session shared by the dom and vision agents.

- headless Chromium, 1280x800, `X-Abtract-Episode` header on every request
- one JS pass numbers the interactive elements (`data-abtract-id`), rewrites target=_blank to _self and returns
  both the visible text (with inline [N] markers) and a description of every element
- actions address elements by `[data-abtract-id="N"]`
- navigation to other hosts is blocked at the network layer and undone if it somehow happens
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlparse

from .base import ActionError

OBSERVE_JS = r"""
(opts) => {
  const viewportOnly = !!(opts && opts.viewportOnly);
  const SEL = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], ' +
              '[role="checkbox"], [role="radio"], [role="switch"], [role="option"], [role="combobox"], [role="textbox"], ' +
              '[onclick], [tabindex]:not([tabindex="-1"]), summary, label[for], [contenteditable="true"]';
  document.querySelectorAll('[data-abtract-id]').forEach(e => e.removeAttribute('data-abtract-id'));
  const overlay = document.getElementById('__abtract_overlay');
  if (overlay) overlay.remove();
  const vw = window.innerWidth, vh = window.innerHeight;
  const elements = [];
  const idOf = new Map();
  const isVisible = (el) => {
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  };
  let n = 1;
  for (const el of document.querySelectorAll(SEL)) {
    if (el.closest('#__abtract_overlay')) continue;
    if (el.tagName === 'INPUT' && el.type === 'hidden') continue;
    if (el.tagName === 'A' && !el.hasAttribute('href') && !el.hasAttribute('onclick') && !el.hasAttribute('role')) continue;
    if (!isVisible(el)) continue;
    if (el.tagName === 'LABEL') {
      const c = el.control;
      if (c && isVisible(c) && c.type !== 'hidden') continue;   // the control itself will be listed
    }
    const formControl = /^(INPUT|SELECT|TEXTAREA|BUTTON)$/.test(el.tagName);
    if (!formControl && el.parentElement && el.parentElement.closest('[data-abtract-id]')) continue;  // nested in a marked element
    const r = el.getBoundingClientRect();
    const inView = r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
    let occluded = false;
    if (inView) {
      const cx = Math.min(vw - 1, Math.max(0, r.left + r.width / 2));
      const cy = Math.min(vh - 1, Math.max(0, r.top + r.height / 2));
      const hit = document.elementFromPoint(cx, cy);
      occluded = !!hit && hit !== el && !el.contains(hit) && !hit.contains(el) && !(el.tagName === 'INPUT' && hit.tagName === 'LABEL');
    }
    if (viewportOnly && (!inView || occluded)) continue;
    if (el.tagName === 'A' && el.getAttribute('target') === '_blank') el.setAttribute('target', '_self');
    el.setAttribute('data-abtract-id', String(n));
    const tag = el.tagName.toLowerCase();
    const isField = tag === 'input' || tag === 'textarea' || tag === 'select';
    const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 100);
    let label = null;
    if (el.labels && el.labels.length) label = (el.labels[0].innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    elements.push({
      id: n, tag, role: el.getAttribute('role'), type: tag === 'input' ? (el.type || 'text') : (el.getAttribute('type')),
      text: txt, aria: el.getAttribute('aria-label'), placeholder: el.getAttribute('placeholder'),
      name: el.getAttribute('name'), title: el.getAttribute('title'), label,
      value: isField ? String(el.value == null ? '' : el.value).slice(0, 100) : null,
      href: tag === 'a' ? el.getAttribute('href') : null,
      checked: (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) ? el.checked : null,
      options: tag === 'select' ? Array.from(el.options).slice(0, 40).map(o => (o.value === o.text ? o.text : o.text + ' (value=' + o.value + ')')) : null,
      required: !!el.required, disabled: !!el.disabled,
      rect: {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)},
      inView, occluded,
    });
    idOf.set(el, n);
    n++;
  }

  // ---- visible text with inline markers (accessibility-tree flavoured innerText)
  const BLOCK = new Set(['P','DIV','SECTION','ARTICLE','HEADER','FOOTER','NAV','MAIN','ASIDE','H1','H2','H3','H4','H5','H6','LI','TR','TABLE','UL','OL','FORM','FIELDSET','BLOCKQUOTE','PRE','DETAILS','SUMMARY','DL','DT','DD','FIGURE','FIGCAPTION','HR','BR','ADDRESS','THEAD','TBODY','TFOOT','LABEL','BUTTON','SELECT','TEXTAREA','OPTION','LEGEND','CAPTION','CENTER','BODY','DIALOG']);
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','HEAD','IFRAME','OBJECT','CANVAS','VIDEO','AUDIO','META','LINK','TITLE']);
  const out = [];
  const descr = (e) => {
    if (e.tag === 'input' || e.tag === 'textarea') {
      if (e.type === 'checkbox' || e.type === 'radio') return '<input type=' + e.type + (e.name ? ' name=' + e.name : '') + (e.value ? ' value=' + JSON.stringify(e.value) : '') + (e.checked ? ' checked' : '') + '>';
      return '<' + e.tag + (e.type && e.tag === 'input' ? ' type=' + e.type : '') + (e.name ? ' name=' + e.name : '') + (e.placeholder ? ' placeholder=' + JSON.stringify(e.placeholder) : '') + (e.value ? ' value=' + JSON.stringify(e.value) : '') + (e.required ? ' required' : '') + '>';
    }
    if (e.tag === 'select') return '<select' + (e.name ? ' name=' + e.name : '') + '> selected=' + JSON.stringify(e.value) + ' options: ' + (e.options || []).join(' | ');
    return null;
  };
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.parentElement && node.parentElement.closest('pre')) { out.push(node.nodeValue); return; }
      const t = node.nodeValue.replace(/\s+/g, ' ');
      if (t.trim()) out.push(t);
      else if (t && out.length && !/\s$/.test(out[out.length - 1])) out.push(' ');   // keep the gap between inline spans
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const el = node, tag = el.tagName;
    if (SKIP.has(tag) || el.id === '__abtract_overlay') return;
    if (el.getAttribute('aria-hidden') === 'true') return;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    const d = st.display;
    const block = BLOCK.has(tag) || d === 'block' || d === 'flex' || d === 'grid' || d === 'list-item' || d === 'table' || d === 'table-row' || d === 'table-caption';
    const afterMarker = out.length && /^\[\d+\] (\(button: )?$/.test(out[out.length - 1]);
    if (block && !afterMarker) out.push('\n');
    if (tag === 'HR') { out.push('----\n'); return; }
    if (tag === 'BR') return;
    if (/^H[1-6]$/.test(tag)) out.push('#'.repeat(+tag[1]) + ' ');
    else if (tag === 'LI') out.push('- ');
    else if (tag === 'TD' || tag === 'TH') out.push(' | ');
    else if (tag === 'IMG') { const alt = el.getAttribute('alt'); if (alt) out.push('[image: ' + alt + ']'); return; }
    const id = idOf.get(el);
    if (id) {
      const e = elements[id - 1];
      const dd = descr(e);
      if (dd) { out.push('[' + id + '] ' + dd); if (block) out.push('\n'); return; }
      out.push('[' + id + '] ');
      if (tag === 'BUTTON' || e.role === 'button') out.push('(button: ');
    }
    if (tag === 'INPUT') { out.push('(' + (el.value || el.type) + ')'); return; }
    for (const c of el.childNodes) walk(c);
    if (id && (tag === 'BUTTON' || elements[id - 1].role === 'button')) out.push(')');
    if (block) out.push('\n');
  };
  walk(document.body);
  const text = out.join('').replace(/[ \t]+\n/g, '\n').replace(/\n[ \t]+/g, '\n').replace(/ {2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  return {text, elements, title: document.title, url: location.href, scrollY: Math.round(window.scrollY),
          scrollHeight: Math.round(document.documentElement.scrollHeight), vh, vw};
}
"""

OVERLAY_JS = r"""
(els) => {
  const old = document.getElementById('__abtract_overlay'); if (old) old.remove();
  const ov = document.createElement('div'); ov.id = '__abtract_overlay';
  ov.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647;overflow:visible;';
  const colors = ['#d62728','#1f77b4','#2ca02c','#ff7f0e','#9467bd','#8c564b','#e377c2','#17becf','#bcbd22','#7f0000'];
  for (const e of els) {
    const c = colors[e.id % colors.length];
    const box = document.createElement('div');
    box.style.cssText = 'position:absolute;left:' + e.rect.x + 'px;top:' + e.rect.y + 'px;width:' + e.rect.w + 'px;height:' + e.rect.h + 'px;border:2px solid ' + c + ';box-sizing:border-box;';
    const lab = document.createElement('div');
    lab.textContent = String(e.id);
    const above = e.rect.y >= 16;
    lab.style.cssText = 'position:absolute;left:-2px;' + (above ? 'top:-16px;' : 'top:-2px;') + 'background:' + c + ';color:#fff;font:bold 12px/16px Arial,Helvetica,sans-serif;padding:0 4px;border-radius:2px;white-space:nowrap;';
    box.appendChild(lab); ov.appendChild(box);
  }
  (document.body || document.documentElement).appendChild(ov);
}
"""

REMOVE_OVERLAY_JS = "() => { const o = document.getElementById('__abtract_overlay'); if (o) o.remove(); }"


def describe_element(e: dict[str, Any]) -> str:
    """One legend line per element, shared by the dom listing and the vision legend."""
    tag, role = e.get("tag"), e.get("role")
    text = e.get("text") or e.get("aria") or e.get("title") or ""
    label = e.get("label")
    if tag == "a":
        return f'link "{text or "(no text)"}" -> {e.get("href") or "#"}'
    if (
        tag == "button"
        or role == "button"
        or (tag == "input" and e.get("type") in ("submit", "button", "image", "reset"))
    ):
        t = text or e.get("value") or "(no text)"
        return f'button "{t}"'
    if tag == "input":
        t = e.get("type") or "text"
        bits = [f"input[{t}]"]
        if e.get("name"):
            bits.append(f"name={e['name']}")
        if label:
            bits.append(f'label="{label}"')
        if e.get("placeholder"):
            bits.append(f'placeholder="{e["placeholder"]}"')
        if t in ("checkbox", "radio"):
            bits.append("checked" if e.get("checked") else "unchecked")
            if e.get("value"):
                bits.append(f"value={e['value']}")
        elif e.get("value"):
            bits.append(f'value="{e["value"]}"')
        if e.get("required"):
            bits.append("required")
        return " ".join(bits)
    if tag == "textarea":
        bits = ["textarea"]
        if e.get("name"):
            bits.append(f"name={e['name']}")
        if label:
            bits.append(f'label="{label}"')
        if e.get("placeholder"):
            bits.append(f'placeholder="{e["placeholder"]}"')
        if e.get("value"):
            bits.append(f'value="{e["value"]}"')
        return " ".join(bits)
    if tag == "select":
        opts = " | ".join(e.get("options") or [])
        lab = f' label="{label}"' if label else ""
        return f'select name={e.get("name") or "-"}{lab} selected="{e.get("value") or ""}" options: {opts}'
    if tag == "summary":
        return f'expander "{text}"'
    if tag == "label":
        return f'label "{text}" (click to toggle its control)'
    what = role or tag
    return f'{what} "{text}"' if text else f"{what}"


class BrowserSession:
    def __init__(self, episode_id: str, site_url: str, *, nav_timeout_ms: int = 30_000, action_timeout_ms: int = 5_000):
        from playwright.sync_api import sync_playwright

        self.site_url = site_url
        self.site_netloc = urlparse(site_url).netloc.lower()
        self.nav_timeout_ms = nav_timeout_ms
        self.action_timeout_ms = action_timeout_ms
        self.dialogs: list[str] = []
        self._new_pages: list[Any] = []
        self.last: dict[str, Any] = {}  # last observation payload from OBSERVE_JS

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            extra_http_headers={"X-Abtract-Episode": episode_id},
            ignore_https_errors=True,
        )
        self.context.set_default_timeout(action_timeout_ms)
        self.context.set_default_navigation_timeout(nav_timeout_ms)
        self.context.route(self._is_foreign, self._block_foreign)
        self.page = self.context.new_page()
        self.page.on("dialog", self._on_dialog)
        # popups / target=_blank that slipped through: remembered here, folded into the main tab in settle()
        self.context.on("page", lambda p: self._new_pages.append(p) if p is not self.page else None)

    # ------------------------------------------------------------------ plumbing
    def _is_foreign(self, url: str) -> bool:
        u = urlparse(url)
        return u.scheme in ("http", "https") and u.netloc.lower() != self.site_netloc

    def _block_foreign(self, route: Any, request: Any) -> None:
        try:
            if request.resource_type == "document":
                route.fulfill(
                    status=403, content_type="text/plain", body="abtract: navigation off the site origin is blocked"
                )
            else:
                route.continue_()
        except Exception:  # noqa: BLE001
            pass

    def _on_dialog(self, dialog: Any) -> None:
        try:
            self.dialogs.append(f"{dialog.type}: {dialog.message}")
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    def same_origin(self, url: str) -> bool:
        u = urlparse(url)
        return u.scheme in ("http", "https") and u.netloc.lower() == self.site_netloc

    @property
    def url(self) -> str:
        try:
            return self.page.url
        except Exception:  # noqa: BLE001
            return self.site_url

    def healthy(self) -> bool:
        try:
            return not self.page.is_closed() and self.browser.is_connected()
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        for fn in (lambda: self.context.close(), lambda: self.browser.close(), lambda: self._pw.stop()):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def settle(self, ms: int = 600) -> None:
        """Wait for navigation/JS after an action, fold popups back into the main tab, undo off-site navigation."""
        self.page.wait_for_timeout(ms)
        try:
            self.page.wait_for_load_state("load", timeout=self.nav_timeout_ms)
        except Exception:  # noqa: BLE001
            pass
        self._absorb_new_pages()
        url = self.url
        if urlparse(url).scheme in ("http", "https") and not self.same_origin(url):
            try:
                self.page.go_back(wait_until="load")
            except Exception:  # noqa: BLE001
                self.page.goto(self.site_url, wait_until="load")
            raise ActionError(f"refused: that led to {url}, which is not on this site; stay on {self.site_netloc}")

    def _absorb_new_pages(self) -> None:
        pages, self._new_pages = self._new_pages, []
        for p in pages:
            target = None
            try:
                p.wait_for_load_state("load", timeout=3000)
            except Exception:  # noqa: BLE001
                pass
            try:
                target = p.url
                p.close()
            except Exception:  # noqa: BLE001
                pass
            if target and target != "about:blank" and self.same_origin(target):
                try:
                    self.page.goto(target, wait_until="load")
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ observing
    def observe(self, viewport_only: bool = False) -> dict[str, Any]:
        last_err: Exception | None = None
        for _ in range(3):
            try:
                self.last = self.page.evaluate(OBSERVE_JS, {"viewportOnly": viewport_only})
                return self.last
            except Exception as e:  # noqa: BLE001  execution context destroyed mid-navigation etc.
                last_err = e
                try:
                    self.page.wait_for_load_state("load", timeout=self.nav_timeout_ms)
                except Exception:  # noqa: BLE001
                    pass
                self.page.wait_for_timeout(300)
        raise RuntimeError(f"could not read the page: {last_err}")

    def take_dialogs(self) -> list[str]:
        d, self.dialogs = self.dialogs, []
        return d

    def screenshot_with_marks(self, elements: list[dict[str, Any]]) -> bytes:
        try:
            self.page.evaluate(OVERLAY_JS, elements)
            return self.page.screenshot(type="png", full_page=False)
        finally:
            try:
                self.page.evaluate(REMOVE_OVERLAY_JS)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def b64(png: bytes) -> str:
        return base64.b64encode(png).decode()

    # ------------------------------------------------------------------ acting
    def _loc(self, eid: int | None) -> Any:
        if eid is None:
            raise ActionError('this action needs a numeric "id" from the latest observation')
        loc = self.page.locator(f'[data-abtract-id="{eid}"]').first
        try:
            n = loc.count()
        except Exception:  # noqa: BLE001
            n = 0
        if n == 0:
            known = [e["id"] for e in (self.last.get("elements") or [])]
            hint = f"ids in the latest observation: {known[:40]}" if known else "observe first"
            raise ActionError(f"no element with id {eid} ({hint})")
        return loc

    def goto(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="load")
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0] if str(e) else type(e).__name__
            if "Timeout" in msg:
                self.settle(0)  # may still be usable
                return
            raise ActionError(f"could not open {url}: {msg[:200]}") from e
        self.settle()

    def click(self, eid: int | None) -> None:
        loc = self._loc(eid)
        try:
            loc.click(timeout=self.action_timeout_ms)
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0] if str(e) else type(e).__name__
            if "Timeout" in msg or "intercepts pointer events" in str(e) or "not visible" in str(e):
                raise ActionError(f"click on [{eid}] blocked or unavailable: {msg[:200]}") from e
            elif "Execution context was destroyed" in str(e) or "navigation" in str(e).lower():
                pass  # the click itself navigated
            else:
                raise ActionError(f"click on [{eid}] failed: {msg[:200]}") from e
        self.settle()

    def fill(self, eid: int | None, text: str) -> None:
        loc = self._loc(eid)
        info = loc.evaluate("el => ({tag: el.tagName.toLowerCase(), type: el.type || null, ce: el.isContentEditable})")
        tag, typ = info.get("tag"), info.get("type")
        try:
            if tag == "input" and typ in ("checkbox", "radio"):
                loc.set_checked(text.strip().lower() in {"1", "true", "yes", "on", "checked", "y"})
            elif tag == "select":
                self.select(eid, text)
                return
            elif tag in ("input", "textarea") or info.get("ce"):
                loc.fill(text)
            else:
                loc.click()
                self.page.keyboard.type(text)
        except ActionError:
            raise
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0] if str(e) else type(e).__name__
            raise ActionError(f"could not type into [{eid}] ({tag}): {msg[:200]}") from e
        self.settle(300)

    def select(self, eid: int | None, value: str) -> None:
        loc = self._loc(eid)
        tag = loc.evaluate("el => el.tagName.toLowerCase()")
        if tag != "select":
            raise ActionError(f"[{eid}] is a <{tag}>, not a <select>; click it and then click the option you want")
        try:
            loc.select_option(value=value)
        except Exception:  # noqa: BLE001
            try:
                loc.select_option(label=value)
            except Exception:  # noqa: BLE001
                opts = loc.evaluate(
                    "el => Array.from(el.options).map(o => o.text + ' (value=' + o.value + ')').join(' | ')"
                )
                raise ActionError(f"[{eid}] has no option {value!r}; options: {opts}") from None
        self.settle(300)

    def scroll(self, direction: str) -> dict[str, int]:
        dy = -(800 - 100) if direction == "up" else (800 - 100)
        # behavior:'instant' bypasses CSS scroll-behavior:smooth so the position we report (and screenshot) is final
        return self.page.evaluate(
            "(dy) => { const before = Math.round(window.scrollY); window.scrollBy({top: dy, left: 0, behavior: 'instant'});"
            " return {before, after: Math.round(window.scrollY), height: Math.round(document.documentElement.scrollHeight)}; }",
            dy,
        )

    def back(self) -> None:
        try:
            r = self.page.go_back(wait_until="load")
        except Exception as e:  # noqa: BLE001
            raise ActionError(f"back failed: {str(e).splitlines()[0][:200]}") from e
        if r is None:
            raise ActionError("no previous page to go back to")
        self.settle()

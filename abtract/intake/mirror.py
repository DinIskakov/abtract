"""Mirror a live website into a directory of static files the site server can host as `<site_id>/v0`.

    site_id_for_url(url)                     -> "zephyrcompute-io", "demo-v0", ... (unique against the store)
    mirror_site(url, dest, ...)              -> MirrorReport   BFS crawl of same-origin pages + their assets
    mirror_to_store(url, site_id=None)       -> (SiteVersion, MirrorReport)   mirror_site into store as v0

Local paths are derived from the URL path *relative to the root URL's directory*:
    /s/demo/v0/            -> index.html
    /s/demo/v0/docs/       -> docs/index.html
    /s/demo/v0/pricing.html-> pricing.html
    /s/demo/v0/pricing     -> pricing.html          (extension-less HTML)
    /elsewhere/x.png       -> __/elsewhere/x.png    (outside the root dir)
    /a.html?b=1            -> a_q<6-char hash>.html
Same-origin href/src/action/poster/srcset references (and url(...) in CSS) are rewritten to paths RELATIVE to the
referencing file, off-origin URLs stay absolute, <base> tags are dropped. Nothing off-origin is ever fetched.
"""
from __future__ import annotations

import hashlib
import mimetypes
import posixpath
import re
import tempfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from abtract import store
from abtract.schemas import SiteVersion

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 abtract-mirror/0.1"
TASKS_FILE = "abtract-tasks.json"
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "blob:", "sms:", "ftp:")
HTML_TYPES = ("text/html", "application/xhtml+xml")
# tag -> attributes holding one URL each
URL_ATTRS: dict[str, tuple[str, ...]] = {
    "a": ("href",), "link": ("href",), "script": ("src",), "img": ("src",), "iframe": ("src",),
    "source": ("src",), "video": ("src", "poster"), "audio": ("src",), "form": ("action",),
    "embed": ("src",), "track": ("src",), "object": ("data",), "area": ("href",),
}
ASSET_LINK_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "preload", "prefetch", "manifest",
                   "modulepreload", "mask-icon"}
_CSS_URL = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)")
_CSS_IMPORT = re.compile(r"@import\s+(['\"])([^'\"]+)\1")
_JS_PAGE = re.compile(r"['\"]([A-Za-z0-9_./-]+\.html?(?:[?#][^'\"]*)?)['\"]")
_EXT_BY_TYPE = {
    "text/css": ".css", "text/javascript": ".js", "application/javascript": ".js", "application/x-javascript": ".js",
    "application/json": ".json", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/svg+xml": ".svg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
    "font/woff": ".woff", "font/woff2": ".woff2", "font/ttf": ".ttf", "font/otf": ".otf",
    "application/font-woff": ".woff", "application/font-woff2": ".woff2", "text/plain": ".txt",
    "application/xml": ".xml", "text/xml": ".xml", "application/pdf": ".pdf", "application/manifest+json": ".webmanifest",
}
_UNSAFE_SEG = re.compile(r"[^A-Za-z0-9._~@()+,=-]")


class MirrorReport(BaseModel):
    root_url: str
    pages: list[str] = []          # local paths of the HTML pages written
    assets: list[str] = []         # local paths of the assets written
    skipped: list[str] = []        # URLs not fetched (page cap, byte cap, non-http)
    errors: list[str] = []         # "<url>: <what went wrong>"; one bad page never aborts the crawl
    unresolved_links: int = 0      # check_site: relative refs that point at nothing we mirrored
    external_links: int = 0        # check_site: links to hosts outside the CDN allowlist (informational)
    warnings: list[str] = []       # other check_site problems (first few)
    tasks_file: bool = False       # <root>/abtract-tasks.json was found and copied


# --------------------------------------------------------------------------- site ids

def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "site"


def site_id_for_url(url: str, *, existing: list[str] | None = None) -> str:
    """Readable, unique site id for a URL: hostname + first path segments, plus a 4-char hash suffix when the
    plain slug is already taken in the store (`existing` overrides store.list_sites(), for tests)."""
    parts = urlsplit(url.strip() if "://" in url else "https://" + url.strip())
    host = (parts.hostname or "site").lower()
    if host.startswith("www."):
        host = host[4:]
    segs = [unquote(s) for s in parts.path.split("/") if s and s != "index.html"]
    if len(segs) >= 3 and segs[0] == "s":  # our own site server: /s/<site_id>/<version>/...
        base = _slug(f"{segs[1]}-{segs[2]}")
    else:
        head = _slug(host)
        if parts.port and host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            head += f"-{parts.port}"
        tail = [_slug(posixpath.splitext(s)[0]) for s in segs[:2]]
        base = "-".join([head, *[t for t in tail if t]])[:60].strip("-")
    taken = set(existing if existing is not None else store.list_sites())
    if base not in taken:
        return base
    salt = url
    while True:
        suffix = hashlib.sha1(f"{salt}{time.time()}".encode()).hexdigest()[:4]
        cand = f"{base}-{suffix}"
        if cand not in taken:
            return cand
        salt += suffix


# --------------------------------------------------------------------------- URL <-> local path

def _norm(url: str) -> str:
    """Canonical form for de-duplication: no fragment, lowercase scheme/host, no trailing '?'."""
    p = urlsplit(url)
    path = p.path or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, p.query, ""))


def _same_origin(url: str, root: str) -> bool:
    a, b = urlsplit(url), urlsplit(root)
    return a.scheme in ("http", "https") and a.netloc.lower() == b.netloc.lower()


def _root_dir(url: str) -> str:
    """Directory part of the root URL path, always ending in '/'."""
    path = urlsplit(url).path or "/"
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


def _safe_segments(rel: str) -> list[str]:
    out = []
    for seg in rel.split("/"):
        seg = unquote(seg)
        if seg in ("", "."):
            continue
        seg = "__" if seg == ".." else _UNSAFE_SEG.sub("_", seg)[:120]
        out.append(seg)
    return out


def _ext_for_type(ctype: str | None) -> str:
    if not ctype:
        return ""
    ctype = ctype.split(";")[0].strip().lower()
    if ctype in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ctype]
    return mimetypes.guess_extension(ctype) or ""


def local_path_for(url: str, root_url: str, *, kind: str = "page", content_type: str | None = None) -> str:
    """Local relative path (posix) for `url`. kind: page | asset | action (never fetched, no extension games)."""
    p = urlsplit(url)
    path = p.path or "/"
    rd = _root_dir(root_url)
    rel = path[len(rd):] if path.startswith(rd) else "__/" + path.lstrip("/")
    segs = _safe_segments(rel)
    if path.endswith("/") or not segs:
        segs.append("index.html")
    name = segs[-1]
    stem, ext = posixpath.splitext(name)
    is_html = bool(content_type and content_type.split(";")[0].strip().lower() in HTML_TYPES)
    if kind == "page" and (is_html or content_type is None):
        if ext.lower() not in (".html", ".htm"):
            stem, ext = (stem if ext else name), ".html"
    elif kind == "asset" and not ext and content_type:
        ext = _ext_for_type(content_type)
    if p.query:
        stem = f"{stem}_q{hashlib.sha1(p.query.encode()).hexdigest()[:6]}"
    segs[-1] = stem + ext
    return "/".join(segs)


def _relative(target_local: str, from_local: str) -> str:
    from_dir = posixpath.dirname(from_local)
    rel = posixpath.relpath(target_local, from_dir or ".")
    return rel


# --------------------------------------------------------------------------- fetching

class _Fetched(BaseModel):
    url: str                 # final URL after redirects
    content_type: str | None
    body: bytes
    status: int


def _fetch(client: httpx.Client, url: str, cap: int) -> _Fetched:
    with client.stream("GET", url) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type")
        length = r.headers.get("content-length")
        if length and length.isdigit() and int(length) > cap:
            raise ValueError(f"{int(length)} bytes exceeds the {cap} byte cap")
        chunks, n = [], 0
        for chunk in r.iter_bytes():
            n += len(chunk)
            if n > cap:
                raise ValueError(f"exceeds the {cap} byte cap")
            chunks.append(chunk)
        return _Fetched(url=str(r.url), content_type=ctype, body=b"".join(chunks), status=r.status_code)


def _is_html(ctype: str | None, body: bytes) -> bool:
    if ctype:
        return ctype.split(";")[0].strip().lower() in HTML_TYPES
    head = body[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or b"<html" in head


# --------------------------------------------------------------------------- the crawl

class _Crawl:
    def __init__(self, root_url: str, dest: Path, *, max_pages: int, max_asset_bytes: int, timeout: float,
                 on_page: Callable[[str, bytes], None] | None = None) -> None:
        self.root_url = root_url
        self.dest = dest
        self.max_pages = max_pages
        self.cap = max_asset_bytes
        self.timeout = timeout
        self.on_page = on_page
        self.report = MirrorReport(root_url=root_url)
        self.local: dict[str, str] = {}                 # normalized url -> local path (pages + assets + aliases)
        self.pages: dict[str, tuple[str, bytes]] = {}   # normalized url -> (local path, html bytes)
        self.assets: dict[str, tuple[str, bytes, str | None]] = {}  # normalized url -> (local path, bytes, ctype)
        self.asset_queue: dict[str, None] = {}          # ordered set of normalized asset urls to fetch
        self.action_refs: set[str] = set()
        self.taken: set[str] = set()                    # local paths already assigned to a page/asset

    # ---- discovery helpers

    def _resolve(self, base: str, ref: str) -> str | None:
        ref = (ref or "").strip()
        if not ref or ref.startswith("#") or ref.lower().startswith(SKIP_SCHEMES):
            return None
        try:
            u = urljoin(base, ref)
        except ValueError:
            return None
        if not _same_origin(u, self.root_url):
            return None
        return _norm(u)

    def _page_base(self, soup: BeautifulSoup, url: str) -> str:
        b = soup.find("base", href=True)
        if b:
            try:
                return urljoin(url, str(b["href"]))
            except ValueError:
                pass
        return url

    def _links(self, soup: BeautifulSoup, base: str) -> tuple[list[str], list[str]]:
        """(page urls, asset urls) referenced by the document, same-origin only, in document order."""
        pages: dict[str, None] = {}
        assets: dict[str, None] = {}
        for tag, attrs in URL_ATTRS.items():
            for el in soup.find_all(tag):
                for attr in attrs:
                    val = el.get(attr)
                    if val is None:
                        continue
                    u = self._resolve(base, str(val))
                    if u is None:
                        continue
                    if tag == "form":
                        self.action_refs.add(u)
                    elif tag in ("a", "area", "iframe"):
                        pages[u] = None
                    elif tag == "link":
                        rels = {r.lower() for r in (el.get("rel") or [])}
                        if rels & ASSET_LINK_RELS:
                            assets[u] = None
                    else:
                        assets[u] = None
        for el in soup.find_all(attrs={"srcset": True}):
            for cand in str(el["srcset"]).split(","):
                u = self._resolve(base, cand.strip().split(" ")[0])
                if u:
                    assets[u] = None
        for el in soup.find_all("style"):
            for u in self._css_refs(el.string or "", base):
                assets[u] = None
        for el in soup.find_all(style=True):
            for u in self._css_refs(str(el["style"]), base):
                assets[u] = None
        return list(pages), list(assets)

    def _css_refs(self, css: str, base: str) -> list[str]:
        out: dict[str, None] = {}
        for m in _CSS_URL.finditer(css):
            u = self._resolve(base, m.group(2))
            if u:
                out[u] = None
        for m in _CSS_IMPORT.finditer(css):
            u = self._resolve(base, m.group(2))
            if u:
                out[u] = None
        return list(out)

    # ---- fetching

    def crawl(self) -> None:
        with httpx.Client(follow_redirects=True, timeout=self.timeout, headers={"User-Agent": USER_AGENT,
                                                                                   "Accept": "*/*"}) as client:
            self._crawl_pages(client)
            self._fetch_assets(client)
            # Static JavaScript navigation is common in the demo and marketing sites.
            # Discover literal page links without executing arbitrary remote scripts.
            linked = []
            for _, (local, body, _) in list(self.assets.items()):
                if local.endswith((".js", ".mjs")):
                    for ref in _JS_PAGE.findall(body.decode("utf-8", "replace")):
                        u = self._resolve(self.root_url, ref)
                        if u and u not in self.local:
                            linked.append(u)
            if linked:
                self._crawl_pages(client, linked)
                self._fetch_assets(client)
            self._fetch_tasks_file(client)

    def _crawl_pages(self, client: httpx.Client, initial: list[str] | None = None) -> None:
        queue: deque[str] = deque(initial or [_norm(self.root_url)])
        seen: set[str] = set(queue)
        while queue:
            url = queue.popleft()
            if len(self.pages) >= self.max_pages:
                self.report.skipped.append(f"{url} (page cap {self.max_pages})")
                continue
            try:
                f = _fetch(client, url, self.cap)
            except Exception as e:  # noqa: BLE001
                self.report.errors.append(f"{url}: {type(e).__name__}: {e}")
                continue
            final = _norm(f.url)
            if final != url and not _same_origin(f.url, self.root_url):
                self.report.skipped.append(f"{url} (redirected off-origin to {f.url})")
                continue
            if not _is_html(f.content_type, f.body):
                local = local_path_for(final, self.root_url, kind="asset", content_type=f.content_type)
                if local in self.taken:
                    self.local[final] = self.local[url] = local
                    continue
                self.taken.add(local)
                self.assets[final] = (local, f.body, f.content_type)
                self.local[final] = local
                self.local[url] = local
                continue
            if final in self.pages:  # redirect onto a page we already have
                self.local[url] = self.pages[final][0]
                continue
            local = local_path_for(final, self.root_url, kind="page", content_type=f.content_type or "text/html")
            if local in self.taken:  # e.g. "/" and "/index.html": same file, keep the first, alias the second
                self.local[final] = self.local[url] = local
                continue
            self.taken.add(local)
            self.pages[final] = (local, f.body)
            self.local[final] = local
            self.local[url] = local
            if self.on_page:
                self.on_page(local, f.body)
            try:
                soup = BeautifulSoup(f.body, "html.parser")
                base = self._page_base(soup, f.url)
                page_links, asset_links = self._links(soup, base)
            except Exception as e:  # noqa: BLE001
                self.report.errors.append(f"{final}: could not parse links: {type(e).__name__}: {e}")
                continue
            for u in page_links:
                if u not in seen:
                    seen.add(u)
                    queue.append(u)
            for u in asset_links:
                self.asset_queue.setdefault(u, None)

    def _fetch_one_asset(self, client: httpx.Client, url: str) -> None:
        if url in self.local:
            return
        try:
            f = _fetch(client, url, self.cap)
        except Exception as e:  # noqa: BLE001
            msg = f"{url}: {type(e).__name__}: {e}"
            (self.report.skipped if "byte cap" in str(e) else self.report.errors).append(msg)
            return
        final = _norm(f.url)
        if not _same_origin(f.url, self.root_url):
            self.report.skipped.append(f"{url} (redirected off-origin to {f.url})")
            return
        if final in self.local:
            self.local[url] = self.local[final]
            return
        kind = "page" if _is_html(f.content_type, f.body) else "asset"
        local = local_path_for(final, self.root_url, kind=kind, content_type=f.content_type)
        if local in self.taken:
            self.local[url] = self.local[final] = local
            return
        self.taken.add(local)
        self.assets[final] = (local, f.body, f.content_type)
        self.local[final] = local
        self.local[url] = local
        ctype = (f.content_type or "").split(";")[0].strip().lower()
        if ctype == "text/css" or local.endswith(".css"):
            for u in self._css_refs(f.body.decode("utf-8", "replace"), f.url):
                self.asset_queue.setdefault(u, None)

    def _fetch_assets(self, client: httpx.Client) -> None:
        done: set[str] = set()
        while True:
            batch = [u for u in self.asset_queue if u not in done and u not in self.local]
            if not batch:
                break
            done.update(batch)
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda u: self._fetch_one_asset(client, u), batch))

    def _fetch_tasks_file(self, client: httpx.Client) -> None:
        url = urljoin(self.root_url, TASKS_FILE)
        try:
            f = _fetch(client, url, self.cap)
            import json

            data = json.loads(f.body.decode("utf-8"))
            if isinstance(data, dict):
                data = data.get("tasks")
            if isinstance(data, list) and data:
                self.assets[_norm(url)] = (TASKS_FILE, f.body, "application/json")
                self.local[_norm(url)] = TASKS_FILE
                self.report.tasks_file = True
        except Exception:  # noqa: BLE001  most sites do not have one
            pass

    # ---- rewriting + writing

    def _target(self, u: str, *, kind: str) -> str:
        """Local path for a same-origin normalized url: what we fetched, else the best guess."""
        if u in self.local:
            return self.local[u]
        return local_path_for(u, self.root_url, kind=kind)

    def _rewrite_ref(self, base: str, ref: str, from_local: str, *, kind: str) -> str:
        raw = (ref or "").strip()
        if not raw or raw.startswith("#") or raw.lower().startswith(SKIP_SCHEMES):
            return ref
        try:
            absolute = urljoin(base, raw)
        except ValueError:
            return ref
        if not _same_origin(absolute, self.root_url):
            return ref
        frag = urlsplit(absolute).fragment
        target = self._target(_norm(absolute), kind=kind)
        if target == from_local and frag:
            return "#" + frag
        rel = _relative(target, from_local)
        return rel + ("#" + frag if frag else "")

    def _rewrite_css(self, css: str, base: str, from_local: str) -> str:
        def sub_url(m: re.Match[str]) -> str:
            q = m.group(1)
            return f"url({q}{self._rewrite_ref(base, m.group(2), from_local, kind='asset')}{q})"

        def sub_import(m: re.Match[str]) -> str:
            q = m.group(1)
            return f"@import {q}{self._rewrite_ref(base, m.group(2), from_local, kind='asset')}{q}"

        return _CSS_IMPORT.sub(sub_import, _CSS_URL.sub(sub_url, css))

    def _rewrite_page(self, url: str, local: str, body: bytes) -> str:
        soup = BeautifulSoup(body, "html.parser")
        base = self._page_base(soup, url)
        for b in soup.find_all("base"):
            b.decompose()
        for tag, attrs in URL_ATTRS.items():
            for el in soup.find_all(tag):
                for attr in attrs:
                    val = el.get(attr)
                    if val is None:
                        continue
                    kind = "action" if tag == "form" else ("page" if tag in ("a", "area", "iframe") else "asset")
                    if tag == "link":
                        rels = {r.lower() for r in (el.get("rel") or [])}
                        kind = "asset" if rels & ASSET_LINK_RELS else "page"
                    el[attr] = self._rewrite_ref(base, str(val), local, kind=kind)
        for el in soup.find_all(attrs={"srcset": True}):
            parts = []
            for cand in str(el["srcset"]).split(","):
                bits = cand.strip().split(" ", 1)
                bits[0] = self._rewrite_ref(base, bits[0], local, kind="asset")
                parts.append(" ".join(bits))
            el["srcset"] = ", ".join(parts)
        for el in soup.find_all("style"):
            if el.string:
                el.string = self._rewrite_css(el.string, base, local)
        for el in soup.find_all(style=True):
            el["style"] = self._rewrite_css(str(el["style"]), base, local)
        meta = soup.find("meta", charset=True)
        if meta:
            meta["charset"] = "utf-8"
        return str(soup)

    def write(self) -> None:
        for url, (local, body) in self.pages.items():
            try:
                text = self._rewrite_page(url, local, body)
            except Exception as e:  # noqa: BLE001  keep the raw page rather than lose it
                self.report.errors.append(f"{url}: rewrite failed, saved as fetched: {type(e).__name__}: {e}")
                text = body.decode("utf-8", "replace")
            self._write(local, text.encode("utf-8"))
            self.report.pages.append(local)
        for url, (local, body, ctype) in self.assets.items():
            if local.endswith(".css") or (ctype or "").split(";")[0].strip().lower() == "text/css":
                try:
                    body = self._rewrite_css(body.decode("utf-8", "replace"), url, local).encode("utf-8")
                except Exception as e:  # noqa: BLE001
                    self.report.errors.append(f"{url}: css rewrite failed: {type(e).__name__}: {e}")
            self._write(local, body)
            self.report.assets.append(local)

    def _write(self, local: str, data: bytes) -> None:
        p = self.dest / Path(*local.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_dir():  # a page "docs" and a dir "docs/" both exist: keep the dir, store the page inside it
            p = p / "index.html"
        p.write_bytes(data)


def _validate(dest: Path, report: MirrorReport) -> None:
    try:
        from abtract.optimizer.check_site import check_site

        problems = check_site(dest)
    except Exception as e:  # noqa: BLE001
        report.warnings.append(f"check_site could not run: {type(e).__name__}: {e}")
        return
    other = []
    for p in problems:
        if "does not resolve" in p:
            report.unresolved_links += 1
        elif "external" in p:
            report.external_links += 1
        else:
            other.append(p)
    report.warnings.extend(other[:20])
    if len(other) > 20:
        report.warnings.append(f"... {len(other) - 20} more")


def mirror_site(url: str, dest: Path, *, max_pages: int = 40, max_asset_bytes: int = 8_000_000,
                timeout: float = 20, on_page: Callable[[str, bytes], None] | None = None) -> MirrorReport:
    """Crawl `url` (same-origin only) into `dest`. Never raises for a bad page; the report lists errors/skips."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    # Resolve the root through redirects first so the root *directory* is derived from where the site really lives.
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            r = client.head(url)
            if r.status_code < 400 and str(r.url) != url and _same_origin(str(r.url), url):
                url = str(r.url)
    except Exception:  # noqa: BLE001  HEAD not supported or transient; the GET below will report properly
        pass
    crawl = _Crawl(url, dest, max_pages=max_pages, max_asset_bytes=max_asset_bytes, timeout=timeout, on_page=on_page)
    crawl.crawl()
    crawl.write()
    if not crawl.pages:
        crawl.report.errors.append(f"{url}: no HTML page could be fetched")
    _validate(dest, crawl.report)
    return crawl.report


def mirror_to_store(url: str, *, site_id: str | None = None, **kw: Any) -> tuple[SiteVersion, MirrorReport]:
    """Mirror `url` and import it into the store as <site_id>/v0. Raises when not even the root page was fetched."""
    site_id = site_id or site_id_for_url(url)
    with tempfile.TemporaryDirectory(prefix="abtract-mirror-") as tmp:
        report = mirror_site(url, Path(tmp), **kw)
        if not report.pages:
            raise RuntimeError("mirror failed: " + ("; ".join(report.errors[-3:]) or "no pages fetched"))
        sv = store.import_site(site_id, "v0", Path(tmp), notes=f"Mirrored from {url}")
    store.commit()
    return sv, report

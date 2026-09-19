"""Standalone validator for a directory of static site files (what Gemini writes).

Deliberately self-contained: only stdlib + beautifulsoup4, no `abtract` imports, so the *source text* of this file
can be copied into a modal.Sandbox (sandbox_image has bs4/lxml/html5lib only) and run there:

    python check_site.py /data/sites/demo/v1

Checks:
  * every .html file is non-empty, has tags, and is not wrapped in a markdown ``` fence
  * every relative href/src/action resolves to a file in the directory (api/... endpoints are allowed)
  * no absolute `/...` internal links (sites are served under a path prefix)
  * no http(s):// links except an allowlist of CDN hosts
  * relative url(...) references in .css resolve

Exit code 0 = ok (prints "OK"), 1 = problems (prints a report), 2 = usage error.
"""

from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_HOSTS = {"cdnjs.cloudflare.com", "fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net"}
DYNAMIC_PREFIXES = ("api/",)  # server endpoints, not files
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#", "blob:")
_ATTRS = {
    "a": "href",
    "link": "href",
    "script": "src",
    "img": "src",
    "form": "action",
    "iframe": "src",
    "source": "src",
    "video": "src",
    "audio": "src",
}
_CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")


def _is_dynamic(rel: str) -> bool:
    rel = rel.lstrip("./")
    return any(rel.startswith(p) or f"/{p}" in rel for p in DYNAMIC_PREFIXES)


def _resolve(site_root: Path, from_file: Path, ref: str) -> bool:
    """True if `ref` (relative, already stripped of query/fragment) points at an existing file."""
    if not ref:
        return True
    base = from_file.parent.relative_to(site_root).as_posix()
    joined = posixpath.normpath(posixpath.join(base if base != "." else "", ref))
    if joined.startswith(".."):
        return False
    target = site_root / joined
    if ref.endswith("/") or target.is_dir():
        return (target / "index.html").is_file()
    if target.is_file():
        return True
    return (target.with_suffix(".html")).is_file() if not target.suffix else False


def _check_ref(site_root: Path, f: Path, ref: str, problems: list[str], what: str) -> None:
    ref = ref.strip()
    if not ref or ref.lower().startswith(SKIP_SCHEMES):
        return
    parts = urlsplit(ref)
    if parts.scheme in ("http", "https") or ref.startswith("//"):
        host = parts.netloc.lower()
        if host not in ALLOWED_HOSTS:
            problems.append(f"{f.relative_to(site_root)}: external {what} to unknown host {host!r}: {ref}")
        return
    if parts.scheme:
        return
    if ref.startswith("/"):
        problems.append(f"{f.relative_to(site_root)}: absolute internal {what} {ref!r} (must be relative)")
        return
    path_only = parts.path
    if _is_dynamic(path_only):
        return
    if not _resolve(site_root, f, path_only):
        problems.append(f"{f.relative_to(site_root)}: {what} {ref!r} does not resolve to a file")


def check_site(site_root: Path) -> list[str]:
    from bs4 import BeautifulSoup

    site_root = Path(site_root)
    problems: list[str] = []
    if not site_root.is_dir():
        return [f"{site_root} is not a directory"]
    html_files = sorted(p for p in site_root.rglob("*.html") if p.is_file())
    if not html_files:
        problems.append("no .html files found")
    for f in html_files:
        rel = f.relative_to(site_root)
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            problems.append(f"{rel}: not utf-8 ({e})")
            continue
        if not text.strip():
            problems.append(f"{rel}: empty file")
            continue
        if text.lstrip().startswith("```") or text.rstrip().endswith("```"):
            problems.append(f"{rel}: wrapped in a markdown code fence")
        soup = BeautifulSoup(text, "html.parser")
        if soup.find() is None:
            problems.append(f"{rel}: contains no HTML tags")
            continue
        if soup.find("body") is None and soup.find("html") is None and "<body" not in text.lower():
            problems.append(f"{rel}: no <html>/<body> element")
        for tag, attr in _ATTRS.items():
            for el in soup.find_all(tag):
                val = el.get(attr)
                if val is None:
                    continue
                _check_ref(site_root, f, str(val), problems, f"{tag}[{attr}]")
        for el in soup.find_all(attrs={"srcset": True}):
            for cand in str(el["srcset"]).split(","):
                _check_ref(site_root, f, cand.strip().split(" ")[0], problems, "srcset")
    for f in sorted(p for p in site_root.rglob("*.css") if p.is_file()):
        try:
            css = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for m in _CSS_URL.finditer(css):
            _check_ref(site_root, f, m.group(1), problems, "css url()")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: check_site.py <site-dir>", file=sys.stderr)
        return 2
    problems = check_site(Path(argv[0]))
    if problems:
        print(f"FAILED: {len(problems)} problem(s) in {argv[0]}")
        for p in problems:
            print(f" - {p}")
        return 1
    print(f"OK: {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

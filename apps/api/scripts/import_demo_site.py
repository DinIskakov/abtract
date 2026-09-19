#!/usr/bin/env python
"""Import a directory of site files into the store as one site version.

Local store (./data or $ABTRACT_DATA_DIR):
    uv run python scripts/import_demo_site.py [--src demo_site/v0] [--site demo] [--version v0] [--parent v0] [--notes "..."]

Straight into the Modal Volume from this machine (no container needed):
    uv run python scripts/import_demo_site.py --modal [--src ...] [--site ...] [--version ...]

After a Modal upload the running site server sees the new version on its next `store.reload()` (it reloads once
when asked for a version it does not know yet).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas import SiteVersion  # noqa: E402


def _file_list(src: Path) -> list[str]:
    return sorted(str(p.relative_to(src)).replace("\\", "/") for p in src.rglob("*") if p.is_file())


def import_local(src: Path, site: str, version: str, parent: str | None, notes: str) -> SiteVersion:
    from app import store

    v = store.import_site(site, version, src, parent=parent, notes=notes)
    print(f"imported {src} -> {store.site_dir(site, version)} ({len(v.changed_files)} files)")
    print(f"registered in {store.versions_path(site)}: {[x.version for x in store.list_versions(site)]}")
    return v


def _read_volume_json(volume, path: str) -> list[dict] | None:
    try:
        data = b"".join(volume.read_file(path))
    except Exception:  # noqa: BLE001  not there yet (FileNotFoundError / NotFoundError depending on modal version)
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        return None


def import_modal(src: Path, site: str, version: str, parent: str | None, notes: str) -> SiteVersion:
    from app.modal_app import data_volume

    versions_path = f"sites/{site}/versions.json"
    existing = _read_volume_json(data_volume, versions_path) or []
    new = SiteVersion(site_id=site, version=version, parent=parent, notes=notes, changed_files=_file_list(src))
    merged = [v for v in existing if v.get("version") != version] + [new.model_dump()]
    merged.sort(key=lambda v: v.get("created_at", 0))
    payload = json.dumps(merged, indent=2).encode("utf-8")

    t0 = time.time()
    with data_volume.batch_upload(force=True) as b:
        b.put_directory(str(src), f"/sites/{site}/{version}")
        b.put_file(io.BytesIO(payload), f"/{versions_path}")
    print(
        f"uploaded {src} -> volume:/sites/{site}/{version} ({len(new.changed_files)} files) in {time.time() - t0:.1f}s"
    )
    print(f"volume:/{versions_path} now lists: {[v['version'] for v in merged]}")
    return new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default=str(ROOT / "demo_site" / "v0"), help="directory of site files")
    ap.add_argument("--site", default="demo")
    ap.add_argument("--version", default="v0")
    ap.add_argument("--parent", default=None, help="version this one was derived from")
    ap.add_argument("--notes", default="", help="human/optimizer notes stored on the SiteVersion")
    ap.add_argument("--modal", action="store_true", help="upload to the Modal Volume instead of the local store")
    args = ap.parse_args(argv)

    src = Path(args.src).resolve()
    if not src.is_dir():
        print(f"error: --src {src} is not a directory", file=sys.stderr)
        return 2
    if not (src / "index.html").exists():
        print(f"warning: {src} has no index.html; the site root will 404", file=sys.stderr)

    if args.modal:
        import_modal(src, args.site, args.version, args.parent, args.notes)
    else:
        import_local(src, args.site, args.version, args.parent, args.notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""Regenerate abtract/dashboard/static_bundle.py from abtract/dashboard/static/.

    uv run python scripts/bundle_dashboard.py [--check]

The dashboard app also does this automatically when imported locally (so `modal deploy deploy.py` never ships a
stale bundle); this script exists for CI / explicit use. `--check` exits 1 when the bundle is out of date.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from abtract.dashboard import bundle  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only report whether the bundle is stale")
    args = ap.parse_args(argv)
    files = bundle.collect()
    if not files:
        print(f"no static assets found in {bundle.STATIC_DIR}", file=sys.stderr)
        return 2
    stale = bundle.current_bundle() != files
    if args.check:
        print("bundle is " + ("STALE" if stale else "up to date"))
        return 1 if stale else 0
    if bundle.refresh_if_stale(quiet=False):
        return 0
    print(f"{bundle.BUNDLE_PATH} already up to date ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

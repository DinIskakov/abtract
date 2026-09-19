#!/usr/bin/env python
"""Validate a directory of site files (links resolve, no absolute paths, no unknown external hosts).

    uv run python scripts/check_site.py demo_site/v0
    uv run python scripts/check_site.py data/sites/demo/v1

The implementation lives in abtract/optimizer/check_site.py (stdlib + bs4 only) so the optimizer can copy that
file's source into a modal.Sandbox and run it on Gemini's output. Exit 0 = OK, 1 = problems found.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.optimizer.check_site import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

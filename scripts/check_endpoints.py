"""Check selected Modal endpoints with GET /v1/models; no inference requests.

    uv run python scripts/check_endpoints.py --env-file .env.modal
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="load credentials/config from this file without displaying them")
    parser.add_argument("--models", default="default", help="comma-separated model IDs or a registry selector")
    args = parser.parse_args()
    if args.env_file:
        if not args.env_file.is_file():
            parser.error(f"environment file does not exist: {args.env_file}")
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=True)

    from abtract.models.llm import match_model_name, modal_base_url
    from abtract.models.registry import discover_modal_models, select_models

    try:
        specs = select_models(args.models)
    except ValueError as exc:
        parser.error(str(exc))
    listings: dict[str, list[str]] = {}
    failures = 0
    for spec in specs:
        if spec.provider != "modal":
            print(f"SKIP {spec.id}: uses {spec.provider}, not a Modal endpoint")
            continue
        base = modal_base_url(spec)
        try:
            if base not in listings:
                listings[base] = discover_modal_models(base_url=base)
            match = match_model_name(spec.model, listings[base])
            if match is None:
                failures += 1
                print(f"MISSING {spec.id}: configured model {spec.model!r} is absent from {base}")
                print(f"  Available model names: {', '.join(listings[base]) or '(none)'}")
            else:
                print(f"OK {spec.id}: {base} -> {match}")
        except Exception as exc:
            failures += 1
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # Do not print exception bodies or credentials from server errors.
            print(f"ERROR {spec.id}: {type(exc).__name__}" + (f" (HTTP {status})" if status else ""))
    print("Checked model listings only; no inference was generated.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

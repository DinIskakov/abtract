"""Print the configured swarm models (price, vision, cost rank) and, if MODAL_PROXY_TOKEN is set, the model names the
Modal gateway exposes plus the name each configured model resolves to (see abtract.models.llm.resolve_modal_model).

    uv run python scripts/list_models.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from abtract.models.llm import resolve_modal_model  # noqa: E402
from abtract.models.pricing import CHECKED_ON, DEDICATED_ONLY_MODELS  # noqa: E402
from abtract.models.registry import CHEAPEST_10, DEFAULT_SWARM, MODELS, cost_rank, discover_modal_models  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    try:
        names = discover_modal_models()
        gateway = f"{len(names)} names visible to your MODAL_PROXY_TOKEN"
    except Exception as e:  # noqa: BLE001
        names, gateway = [], f"could not list Modal models: {e}"

    print(f"Configured models (Shared Endpoint prices from modal.com/library, checked {CHECKED_ON}; "
          f"cost rank = 0.8*in + 0.2*out):")
    print(f"  {'id':22s} {'provider':8s} {'$in/M':>6s} {'$out/M':>6s} {'rank':>5s} vision  model -> sent to the gateway")
    for m in MODELS.values():
        if m.provider == "modal":
            sent = resolve_modal_model(m) if names else "(gateway not listed)"
            arrow = f"{m.model}  ->  {sent}" if sent != m.model else m.model
        else:
            arrow = m.model
        print(f"  {m.id:22s} {m.provider:8s} {m.input_price_per_m:6.2f} {m.output_price_per_m:6.2f} "
              f"{cost_rank(m):5.2f} {'yes' if m.supports_vision else 'no ':6s}  {arrow}")
    print(f"\nCheapest first: {', '.join(CHEAPEST_10)}")
    print(f"Default swarm:  {', '.join(DEFAULT_SWARM)}")
    if DEDICATED_ONLY_MODELS:
        print("Library models without a Shared Endpoint (dedicated GPU billing only, not in the swarm): "
              + ", ".join(r["modal_id"] for r in DEDICATED_ONLY_MODELS))

    print(f"\nModal gateway: {gateway}")
    for name in names:
        print("  ", name)
    if names:
        unmatched = [m.id for m in MODELS.values() if m.provider == "modal" and resolve_modal_model(m) not in names]
        if unmatched:
            print(f"\nNot matched to this gateway: {', '.join(unmatched)}. "
                  "For separate model URLs, run scripts/check_endpoints.py --env-file .env.modal; "
                  "see docs/endpoint-setup.md for configuration.")


if __name__ == "__main__":
    main()

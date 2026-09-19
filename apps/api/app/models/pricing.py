"""Verified Modal hosted-inference price table. Plain data; the registry builds ModelSpecs from it.

Every row in SHARED_ENDPOINT_MODELS was read from its `source_url` on modal.com/library on CHECKED_ON. Only models
whose library page shows a Shared Endpoint (pay per token) price are listed; prices are USD per 1M tokens and the
cached-prompt discount is recorded but not used for cost estimates (they err high). `modal_id` is the exact string
for `modal endpoint create --model <modal_id>` and the default OpenAI `model` field (see llm.resolve_modal_model).

To add a model: append a row with its library page as `source_url`, then `uv run pytest tests/test_models.py`.
"""

from __future__ import annotations

from typing import Any

CHECKED_ON = "2026-09-19"

SHARED_ENDPOINT_MODELS: list[dict[str, Any]] = [
    {
        "id": "deepseek-v4.1-flash",
        "modal_id": "deepseek-ai/DeepSeek-V4.1-Flash",
        "display_name": "DeepSeek V4.1 Flash",
        "org": "DeepSeek",
        "shared_endpoint": True,
        "input_price_per_m": 0.30,
        "output_price_per_m": 1.20,
        "cached_input_price_per_m": 0.03,
        "supports_vision": True,
        "modalities": "text, image",
        "context_tokens": 1_000_000,
        "params": "552B MoE, 8B active (prefill) / 16B (decode)",
        "source_url": "https://modal.com/library/deepseek/deepseek-v4-1-flash",
        "checked_on": CHECKED_ON,
    },
    {
        "id": "glm-5.3-flash",
        "modal_id": "zai-org/GLM-5.3-Flash",
        "display_name": "GLM 5.3 Flash",
        "org": "Z.ai",
        "shared_endpoint": True,
        "input_price_per_m": 0.45,
        "output_price_per_m": 1.50,
        "cached_input_price_per_m": 0.09,
        "supports_vision": True,
        "modalities": "text, image, video",
        "context_tokens": 1_000_000,
        "params": "320B MoE, 18B active",
        "source_url": "https://modal.com/library/zai/glm-5-3-flash",
        "checked_on": CHECKED_ON,
    },
    {
        "id": "inkling",
        "modal_id": "thinkingmachines/Inkling-NVFP4",
        "display_name": "Inkling NVFP4",
        "org": "Thinking Machines",
        "shared_endpoint": True,
        "input_price_per_m": 1.20,
        "output_price_per_m": 5.00,
        "cached_input_price_per_m": 0.27,
        "supports_vision": True,
        "modalities": "text, image, audio",
        "context_tokens": 1_000_000,
        "params": "975B MoE, 41B active",
        "source_url": "https://modal.com/library/thinking-machines/inkling",
        "checked_on": CHECKED_ON,
    },
    {
        "id": "glm-5.3",
        "modal_id": "zai-org/GLM-5.3",
        "display_name": "GLM 5.3",
        "org": "Z.ai",
        "shared_endpoint": True,
        "input_price_per_m": 1.40,
        "output_price_per_m": 4.40,
        "cached_input_price_per_m": 0.26,
        "supports_vision": True,
        "modalities": "text, image, video",
        "context_tokens": 1_000_000,
        "params": "753B MoE, 40B active",
        "source_url": "https://modal.com/library/zai/glm-5-3",
        "checked_on": CHECKED_ON,
    },
    {
        "id": "qwen3.8-max",
        "modal_id": "Qwen/Qwen3.8-2.4T-A95B",
        "display_name": "Qwen 3.8-Max",
        "org": "Qwen",
        "shared_endpoint": True,
        "input_price_per_m": 2.00,
        "output_price_per_m": 6.00,
        "cached_input_price_per_m": 0.25,
        "supports_vision": False,
        "modalities": "text",
        "context_tokens": 262_144,  # native; the page says "up to 1.01M" with context extension
        "params": "2.4T MoE, 95B active",
        "source_url": "https://modal.com/library/qwen/qwen3-8-max",
        "checked_on": CHECKED_ON,
    },
    {
        "id": "kimi-k3",
        "modal_id": "moonshotai/Kimi-K3",
        "display_name": "Kimi K3",
        "org": "Moonshot AI",
        "shared_endpoint": True,
        "input_price_per_m": 3.00,
        "output_price_per_m": 15.00,
        "cached_input_price_per_m": 0.30,
        "supports_vision": True,
        "modalities": "text, image",
        "context_tokens": 1_048_576,
        "params": "2.8T MoE, 104B active",
        "source_url": "https://modal.com/library/moonshot/kimi-k3",
        "checked_on": CHECKED_ON,
    },
]

# Library models with a page but no Shared Endpoint: dedicated GPU-second billing only, so no per-token price and no
# entry in the swarm registry. Kept here so nobody re-checks them.
DEDICATED_ONLY_MODELS: list[dict[str, Any]] = [
    {
        "modal_id": "openai/gpt-oss-120b",
        "display_name": "GPT-OSS 120B",
        "shared_endpoint": False,
        "supports_vision": False,
        "context_tokens": 131_072,
        "params": "117B MoE, 5.1B active",
        "source_url": "https://modal.com/library/openai/gpt-oss-120b",
        "checked_on": CHECKED_ON,
    },
    {
        "modal_id": "google/gemma-4-31B-it",
        "display_name": "Gemma 4 31B IT",
        "shared_endpoint": False,
        "supports_vision": True,
        "context_tokens": 262_144,
        "params": "30.7B dense (+~550M vision encoder)",
        "source_url": "https://modal.com/library/google/gemma-4-31b",
        "checked_on": CHECKED_ON,
    },
]

# Hugging Face repo IDs seen in Modal's endpoint UI / CLI docs (`modal endpoint create --model` accepts any of them
# for a *dedicated* endpoint). On CHECKED_ON none had a modal.com/library page or a Shared Endpoint price, so they
# are not priced and not in the registry. Verify on modal.com before promoting one to SHARED_ENDPOINT_MODELS.
UNVERIFIED_CANDIDATES: list[str] = [
    "Qwen/Qwen3.6-27B",
    "Qwen/Qwen3.6-35B-A3B",
    "google/gemma-4-E4B-it",
    "google/gemma-4-26B-A4B-it",
    "zai-org/GLM-5.2-FP8",
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4",
    "Qwen/Qwen3.5-397B-A17B-FP8",
    "nvidia/Kimi-K2.6-NVFP4",
    "deepseek-ai/DeepSeek-V4-Pro",
]

"""Small, bounded Gemini structured-output client; no agent framework."""

import json
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from app.config import settings


class GeminiError(RuntimeError):
    """Safe public error: never includes credentials or provider response bodies."""


class Generation(BaseModel):
    data: dict[str, Any]
    requested_model: str
    reported_model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


async def generate(
    instructions: str, payload: dict[str, Any], schema: dict[str, Any]
) -> Generation:
    key = settings.gemini_api_key
    if key is None or not key.get_secret_value().strip():
        raise GeminiError("Set GEMINI_API_KEY before semantic evaluation or proposals")
    model = settings.gemini_model
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent"
    )
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": key.get_secret_value()},
                json={
                    "systemInstruction": {"parts": [{"text": instructions}]},
                    "contents": [
                        {"role": "user", "parts": [{"text": json.dumps(payload)}]}
                    ],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 8192,
                        "responseMimeType": "application/json",
                        "responseJsonSchema": schema,
                    },
                },
            )
            if response.status_code != 200:
                raise GeminiError(f"Gemini returned HTTP {response.status_code}")
            body = response.json()
            candidate = body["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise GeminiError("Gemini did not finish a complete response")
            raw = "".join(
                part.get("text", "")
                for part in candidate["content"]["parts"]
                if not part.get("thought")
            )
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise GeminiError("Gemini returned a non-object response")
            return Generation(
                data=data,
                requested_model=model,
                reported_model=body.get("modelVersion"),
                usage=body.get("usageMetadata", {}),
            )
    except GeminiError:
        raise
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
    ) as exc:
        raise GeminiError(
            "Gemini request failed or returned invalid structured output"
        ) from exc

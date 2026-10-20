"""Nebius inference adapter. Fixture mode is explicitly synthetic, not submission evidence."""
from dataclasses import dataclass
import json
import time
import httpx
from ownstack.config import Settings


SYSTEM = """You classify a B2B customer's requested software change. Return only JSON with
route (configure, engineering, or refuse) and a short reason. Configure only a temporary,
read-only grant to one named project and viewer. New features such as PDF export require
engineering. Requests to access another tenant or evade approval must be refused.
The application's deterministic policy remains authoritative; your answer is only a proposal."""


@dataclass(frozen=True)
class AIResult:
    route: str
    reason: str
    model_id: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None


def classify(text: str, kind: str, settings: Settings | None = None) -> AIResult:
    settings = settings or Settings()
    settings.validate()
    if settings.ai_mode == "off":
        raise RuntimeError("AI_OFF")
    if settings.ai_mode == "fixture":
        route = "engineering" if kind == "feature" else "configure"
        if "nova" in text.lower() and "atlas" in text.lower():
            route = "refuse"
        return AIResult(route, "Synthetic fixture classification, not a live model result.", "fixture", 0, None, None)
    started = time.monotonic()
    response = httpx.post(
        "https://api.tokenfactory.nebius.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.nebius_key}"},
        json={
            "model": settings.nebius_model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 2048,
        },
        timeout=settings.ai_timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data["choices"][0].get("finish_reason") == "length":
        raise ValueError("MODEL_OUTPUT_TRUNCATED")
    message = data["choices"][0]["message"]
    if message.get("refusal"):
        raise ValueError("MODEL_REFUSAL")
    parsed = json.loads(message["content"])
    if set(parsed) != {"route", "reason"} or parsed["route"] not in {"configure", "engineering", "refuse"} or not isinstance(parsed["reason"], str) or len(parsed["reason"]) > 500:
        raise ValueError("INVALID_MODEL_OUTPUT")
    usage = data.get("usage") or {}
    return AIResult(parsed["route"], parsed["reason"], settings.nebius_model, int((time.monotonic() - started) * 1000), usage.get("prompt_tokens"), usage.get("completion_tokens"))

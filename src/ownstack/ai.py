"""Nebius inference adapter. Fixture mode is explicitly synthetic, not submission evidence."""
from dataclasses import dataclass
import json
import time
import httpx
from ownstack.config import Settings
from ownstack.model_contracts import RouteProposal, validate_proposal
from ownstack.model_stream import collect_proposal, provider_proposal


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
    if message.get("refusal") or message.get("tool_calls") or message.get("function_call"):
        raise ValueError("MODEL_REFUSAL")
    parsed = validate_proposal(message["content"], "propose_route")
    usage = data.get("usage") or {}
    return AIResult(parsed.route, parsed.reason, settings.nebius_model, int((time.monotonic() - started) * 1000), usage.get("prompt_tokens"), usage.get("completion_tokens"))


def classify_stream(text, kind, settings, *, on_progress, should_continue):
    """Native provider stream or explicitly synthetic bytes through the same parser.

    The only advertised function proposes a route/reason. It cannot select a
    tenant, project, viewer, duration, approval, command or deployment target.
    """
    settings.validate()
    if settings.ai_mode == "off":
        raise RuntimeError("AI_OFF")
    started = time.monotonic()
    if settings.ai_mode == "fixture":
        result = classify(text, kind, settings)
        raw = json.dumps({"route": result.route, "reason": result.reason})
        frames = ["data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": raw[i:i+12]},
                     "finish_reason": None}]}) + "\n\n" for i in range(0, len(raw), 12)]
        frames += ['data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
                   'data: [DONE]\n\n']
        proposal, usage = collect_proposal((frame.encode() for frame in frames), "propose_route",
            on_progress=on_progress, should_continue=should_continue, timeout=settings.ai_timeout)
        model_id = "fixture"
    else:
        model_id = settings.nebius_model
        proposal, usage = provider_proposal({"model": model_id,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
            "tools": [{"type": "function", "function": {"name": "propose_route",
                "description": "Propose a route, never authorize or execute a change.",
                "parameters": RouteProposal.model_json_schema()}}],
            "tool_choice": {"type": "function", "function": {"name": "propose_route"}},
            "temperature": 0, "max_tokens": 2048}, settings, expected_tool="propose_route",
            on_progress=on_progress, should_continue=should_continue)
    return AIResult(proposal.route, proposal.reason, model_id, int((time.monotonic()-started)*1000),
                    usage.get("prompt_tokens"), usage.get("completion_tokens"))

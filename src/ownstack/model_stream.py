"""Bounded native Chat Completions SSE decoding, independent of browser progress.

No callback receives content, reasoning, prompts, tool arguments or credentials.
Nothing is dispatched from a partial value, a valid-looking JSON prefix, or EOF.
"""
import time
import httpx
from ownstack.model_contracts import strict_json, validate_proposal

ENDPOINT = "https://api.tokenfactory.nebius.com/v1/chat/completions"
MAX_WIRE_BYTES = 131_072
MAX_FRAME_BYTES = 32_768
MAX_EVENTS = 512
MAX_ARGUMENT_BYTES = 16_384


class StreamStopped(RuntimeError):
    """Local acceptance invalidated. Remote cancellation/billing are unverified."""


def sse_data(chunks, *, checkpoint=lambda: None):
    """Parse arbitrary byte fragments without unbounded iter_lines buffering."""
    pending, lines, total, events = b"", [], 0, 0
    for chunk in chunks:
        checkpoint()
        total += len(chunk)
        if total > MAX_WIRE_BYTES:
            raise ValueError("STREAM_SIZE_LIMIT")
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            line = line.removesuffix(b"\r")
            if len(line) + sum(map(len, lines)) > MAX_FRAME_BYTES:
                raise ValueError("STREAM_FRAME_LIMIT")
            if line == b"":
                if lines:
                    events += 1
                    if events > MAX_EVENTS:
                        raise ValueError("STREAM_EVENT_LIMIT")
                    try:
                        yield b"\n".join(lines).decode("utf-8", errors="strict")
                    except UnicodeError:
                        raise ValueError("INVALID_STREAM_UTF8") from None
                    lines = []
            elif line.startswith(b"data:"):
                lines.append(line[5:].removeprefix(b" "))
            elif line.startswith(b":"):
                pass
            else:
                raise ValueError("INVALID_STREAM_FRAME")
        if len(pending) + sum(map(len, lines)) > MAX_FRAME_BYTES:
            raise ValueError("STREAM_FRAME_LIMIT")
    # Even complete JSON without a terminated SSE frame is not a complete call.
    if pending or lines:
        raise ValueError("STREAM_TRUNCATED")


def collect_proposal(chunks, expected_tool, *, model_id=None, on_progress=lambda _: None,
                     should_continue=lambda: True, timeout=20, clock=time.monotonic):
    """Assemble one content object OR one allowlisted function call, then validate.

    Both a matching finish reason and [DONE] are mandatory. Multiple choices,
    parallel calls, mixed content/calls and late deltas are rejected. Reasoning
    fields are ignored and never persisted. A timeout closes the local transport
    when control returns; it cannot prove remote inference stopped.
    """
    started, finished, done = clock(), None, False
    content, name, arguments, call_id = "", "", "", ""
    deltas, size, tool_seen, usage = 0, 0, False, {}

    def checkpoint():
        if not should_continue():
            raise StreamStopped("LOCAL_STREAM_STOP")
        if clock() - started >= timeout:
            raise httpx.ReadTimeout("Local stream deadline")

    on_progress({"phase": "receiving", "received_bytes": 0, "deltas": 0})
    for data in sse_data(chunks, checkpoint=checkpoint):
        checkpoint()
        if data == "[DONE]":
            done = True
            break
        obj = strict_json(data, MAX_FRAME_BYTES)
        if not isinstance(obj, dict) or obj.get("error"):
            raise ValueError("INVALID_STREAM_ENVELOPE")
        if model_id is not None and obj.get("model") != model_id:
            raise ValueError("MODEL_ID_MISMATCH")
        choices = obj.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("INVALID_STREAM_CHOICES")
        if obj.get("usage") is not None:
            candidate = obj["usage"]
            if not isinstance(candidate, dict) or any(
                type(candidate.get(key)) is not int or candidate[key] < 0
                for key in ("prompt_tokens", "completion_tokens")
            ):
                raise ValueError("INVALID_STREAM_USAGE")
            usage = {key: candidate[key] for key in ("prompt_tokens", "completion_tokens")}
        if not choices:  # Optional final usage-only frame, not a completion.
            continue
        choice = choices[0]
        if not isinstance(choice, dict) or type(choice.get("index")) is not int or choice["index"] != 0:
            raise ValueError("INVALID_STREAM_CHOICES")
        delta = choice.get("delta")
        if not isinstance(delta, dict) or finished is not None:
            raise ValueError("INVALID_STREAM_ORDER")
        if delta.get("refusal") or delta.get("function_call"):
            raise ValueError("MODEL_REFUSAL_OR_LEGACY_CALL")
        fragment = delta.get("content")
        if fragment is not None:
            if not isinstance(fragment, str) or tool_seen:
                raise ValueError("MIXED_MODEL_OUTPUT")
            content += fragment
        calls = delta.get("tool_calls")
        if calls is not None:
            if content or not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("INVALID_MODEL_TOOL_CALL")
            tool_seen = True
            call = calls[0]
            if (not isinstance(call, dict) or set(call) - {"index", "id", "type", "function"}
                    or type(call.get("index")) is not int or call["index"] != 0
                    or call.get("type", "function") != "function"):
                raise ValueError("INVALID_MODEL_TOOL_CALL")
            if "id" in call:
                if not isinstance(call["id"], str) or not call["id"] or call_id:
                    raise ValueError("INVALID_MODEL_TOOL_ID")
                call_id = call["id"]
                if len(call_id) > 128:
                    raise ValueError("INVALID_MODEL_TOOL_ID")
            function = call.get("function")
            if not isinstance(function, dict) or set(function) - {"name", "arguments"}:
                raise ValueError("INVALID_MODEL_TOOL_CALL")
            for key in ("name", "arguments"):
                if key in function and not isinstance(function[key], str):
                    raise ValueError("INVALID_MODEL_TOOL_CALL")
            name += function.get("name", "")
            arguments += function.get("arguments", "")
            if len(name) > 64:
                raise ValueError("UNKNOWN_MODEL_TOOL")
        size = len((content + arguments).encode("utf-8"))
        if size > MAX_ARGUMENT_BYTES:
            raise ValueError("STREAM_ARGUMENT_LIMIT")
        if fragment or calls:
            deltas += 1
            on_progress({"phase": "receiving", "received_bytes": size, "deltas": deltas})
        stop = choice.get("finish_reason")
        if stop is not None:
            if stop == "length":
                raise ValueError("MODEL_OUTPUT_TRUNCATED")
            if stop not in {"stop", "tool_calls"}:
                raise ValueError("INVALID_STREAM_FINISH")
            finished = stop
    checkpoint()
    if not done or finished is None:
        raise ValueError("STREAM_TRUNCATED")
    if tool_seen:
        if finished != "tool_calls" or not call_id or name != expected_tool:
            raise ValueError("UNKNOWN_OR_INCOMPLETE_MODEL_TOOL")
        raw = arguments
    else:
        if finished != "stop":
            raise ValueError("INVALID_STREAM_FINISH")
        raw = content
    # No handler is reachable above this line. The returned object is still a
    # proposal: the durable service must enforce current identity and approval.
    proposal = validate_proposal(raw, expected_tool)
    checkpoint()
    on_progress({"phase": "validated", "received_bytes": size, "deltas": deltas})
    return proposal, usage


def provider_proposal(payload, settings, *, expected_tool, on_progress, should_continue):
    """One request only. No automatic retry or alternate endpoint/model fallback."""
    started = time.monotonic()
    if not should_continue():
        raise StreamStopped("LOCAL_STREAM_STOP")
    with httpx.Client(timeout=httpx.Timeout(settings.ai_timeout, read=min(2, settings.ai_timeout)),
                      follow_redirects=False, trust_env=False) as client:
        with client.stream("POST", ENDPOINT, headers={"Authorization": f"Bearer {settings.nebius_key}",
                           "Accept": "text/event-stream"}, json={**payload, "stream": True,
                           "stream_options": {"include_usage": True}}) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").split(";")[0].strip() != "text/event-stream":
                raise ValueError("INVALID_STREAM_CONTENT_TYPE")
            return collect_proposal(response.iter_bytes(), expected_tool, model_id=payload["model"],
                                    on_progress=on_progress, should_continue=should_continue,
                                    timeout=settings.ai_timeout - (time.monotonic() - started))

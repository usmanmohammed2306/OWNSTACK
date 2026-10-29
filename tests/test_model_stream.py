"""Offline native-provider wire fixtures. No live inference or budget authority."""
import json
from dataclasses import replace
import httpx
import pytest
from ownstack import model_stream
from ownstack.ai import classify_stream
from ownstack.config import Settings
from ownstack.model_contracts import validate_proposal
from ownstack.model_stream import collect_proposal, StreamStopped

MODEL = "nvidia/Nemotron-synthetic-stream"
VALID = '{"route":"configure","reason":"Synthetic café"}'


def event(delta=None, finish=None, **extra):
    return ("data: " + json.dumps({"model": MODEL, "choices": [{"index": 0, "delta": delta or {},
                         "finish_reason": finish}], **extra}, ensure_ascii=False) + "\r\n\r\n").encode()


def wire(raw=VALID, *, tool=False, name="propose_route", finish=None):
    if tool:
        return [event({"tool_calls": [{"index": 0, "id": "call-test", "type": "function",
                    "function": {"name": name[:7], "arguments": raw[:10]}}]}),
                event({"tool_calls": [{"index": 0, "function": {"name": name[7:], "arguments": raw[10:]}}]}),
                event(finish=finish or "tool_calls"), b"data: [DONE]\r\n\r\n"]
    return [event({"content": raw[:10]}), event({"content": raw[10:]}),
            event(finish=finish or "stop"), b"data: [DONE]\r\n\r\n"]


@pytest.mark.parametrize("tool", [False, True])
def test_fragmented_utf8_and_arguments_are_validated_only_after_done(tool):
    observed, dispatched = [], []
    source = b"".join(wire(tool=tool))
    def chunks():
        for byte in source:
            assert not dispatched  # No handler is reachable on any prefix.
            yield bytes([byte])
    proposal, usage = collect_proposal(chunks(), "propose_route", model_id=MODEL, on_progress=observed.append)
    dispatched.append(proposal)
    assert proposal.route == "configure" and proposal.reason == "Synthetic café" and usage == {}
    assert observed[-1]["phase"] == "validated"
    assert observed[-1]["received_bytes"] == len(VALID.encode())
    assert all(set(p) == {"phase", "received_bytes", "deltas"} for p in observed)
    assert "café" not in repr(observed) and "configure" not in repr(observed)


@pytest.mark.parametrize("raw", [
    "not json", '{"route":"configure"', '[]', 'null',
    '{"route":"configure","reason":"a","reason":"b"}',
    '{"route":"configure","reason":23}', '{"route":true,"reason":"a"}',
    '{"route":"configure","reason":"a","shell":"danger"}',
    '{"route":"approve","reason":"a"}', '{"route":"configure","reason":""}',
    '{"route":"configure","reason":NaN}', '{"replacement":"pass"}',
    '{"route":"configure","reason":"\\ud800"}',
    '{"route":"configure","reason":' + '['*25 + '0' + ']'*25 + '}',
])
def test_invalid_complete_tool_arguments_never_return_to_dispatch(raw):
    validated = []
    with pytest.raises(ValueError):
        result, _ = collect_proposal(wire(raw, tool=True), "propose_route", on_progress=validated.append)
        pytest.fail(f"Invalid call returned {type(result).__name__}")
    assert not any(p["phase"] == "validated" for p in validated)


@pytest.mark.parametrize("chunks", [
    wire()[:-1], wire()[:2] + [b"data: [DONE]\n\n"],
    [event({"content": VALID}, "length"), b"data: [DONE]\n\n"],
    [event({"content": VALID}, "content_filter"), b"data: [DONE]\n\n"],
    wire(tool=True, name="run_shell"), wire(tool=True, finish="stop"),
    wire(finish="tool_calls"), [event({"refusal": "private refusal"})],
    [event({"tool_calls": [{"index": 1, "function": {"arguments": VALID}}]})],
    [event({"tool_calls": [{"index": 0, "function": {"arguments": 1}}]})],
    [event({"tool_calls": [{"index": 0, "function": {"arguments": VALID}},
                           {"index": 1, "function": {"arguments": VALID}}]})],
    [event({"content": "x"}), *wire(tool=True)],
    [event({"content": VALID}, "stop"), event({"content": "extra"}), b"data: [DONE]\n\n"],
    [b'data: {"choices":[]}\n'], [b"data: \xff\n\n"],
    [event({"content": "x" * 17_000})], [b"data: " + b"x" * 33_000],
])
def test_protocol_and_bounds_fail_closed(chunks):
    with pytest.raises(ValueError):
        collect_proposal(chunks, "propose_route")


def test_wire_event_and_total_limits(monkeypatch):
    monkeypatch.setattr(model_stream, "MAX_EVENTS", 2)
    with pytest.raises(ValueError, match="EVENT_LIMIT"):
        collect_proposal(wire(), "propose_route")
    monkeypatch.setattr(model_stream, "MAX_WIRE_BYTES", 10)
    with pytest.raises(ValueError, match="SIZE_LIMIT"):
        collect_proposal(wire(), "propose_route")


def test_reasoning_is_never_reported_or_mistaken_for_output():
    updates = []
    proposal, _ = collect_proposal([event({"reasoning_content": "PRIVATE CHAIN"}), *wire()], "propose_route", on_progress=updates.append)
    assert proposal.route == "configure" and "PRIVATE" not in repr(updates)
    with pytest.raises(ValueError):
        collect_proposal([event({"reasoning_content": VALID}, "stop"), b"data: [DONE]\n\n"], "propose_route")


def test_local_cancel_and_absolute_deadline_prevent_validated_result():
    updates = []
    with pytest.raises(StreamStopped):
        collect_proposal(wire(), "propose_route", on_progress=updates.append, should_continue=lambda: len(updates) < 2)
    assert not any(p["phase"] == "validated" for p in updates)
    ticks = iter([0, 21])
    with pytest.raises(httpx.ReadTimeout):
        collect_proposal(wire(), "propose_route", clock=lambda: next(ticks), timeout=20)


def test_schema_is_shared_by_complete_route_and_patch_outputs():
    assert validate_proposal('{"replacement":"pass\\n"}', "propose_replacement").replacement == "pass\n"
    for raw in ('{"replacement":1}', '{"replacement":"x","path":"auth.py"}', '{"replacement":"x","replacement":"y"}'):
        with pytest.raises(ValueError, match="INVALID_MODEL_OUTPUT"):
            validate_proposal(raw, "propose_replacement")
    with pytest.raises(ValueError, match="UNKNOWN_MODEL_TOOL"):
        validate_proposal(VALID, "approve")


def settings():
    return Settings(ai_mode="nebius", nebius_key="synthetic-not-real", nebius_model=MODEL,
                    nebius_patch_model="", max_live_calls=10, stream_inference=True)


def test_native_http_stream_request_and_close_are_real_adapter_behavior(monkeypatch):
    observed, closed = [], []
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            yield from wire(tool=True)
        def close(self):
            closed.append(True)
    def handler(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Bytes())
    original = httpx.Client
    monkeypatch.setattr(model_stream.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = classify_stream("Private customer request", "access", settings(), on_progress=lambda _: None, should_continue=lambda: True)
    assert result.route == "configure" and closed == [True]
    assert observed[0]["stream"] is True
    assert observed[0]["tool_choice"]["function"]["name"] == "propose_route"
    assert observed[0]["tools"][0]["function"]["parameters"]["additionalProperties"] is False


@pytest.mark.parametrize("status,content_type", [(429, "application/json"), (200, "application/json")])
def test_provider_failures_do_not_retry_or_leak_body(monkeypatch, status, content_type):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"content-type": content_type}, content=b"PRIVATE PROVIDER ERROR")
    original = httpx.Client
    monkeypatch.setattr(model_stream.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises((ValueError, httpx.HTTPStatusError)) as error:
        classify_stream("Private request", "feature", settings(), on_progress=lambda _: None, should_continue=lambda: True)
    assert len(requests) == 1 and "PRIVATE PROVIDER ERROR" not in str(error.value)


def test_ai_off_stream_does_not_construct_network_client(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **_: pytest.fail("HTTP forbidden"))
    with pytest.raises(RuntimeError, match="AI_OFF"):
        classify_stream("request", "access", replace(settings(), ai_mode="off"), on_progress=lambda _: None, should_continue=lambda: True)


def test_usage_only_final_frame_and_model_mismatch():
    chunks = wire()[:-1] + [b'data: ' + json.dumps({"model": MODEL, "choices": [],
        "usage": {"prompt_tokens": 5, "completion_tokens": 6}}).encode() + b'\n\n', wire()[-1]]
    _, usage = collect_proposal(chunks, "propose_route", model_id=MODEL)
    assert usage == {"prompt_tokens": 5, "completion_tokens": 6}
    with pytest.raises(ValueError, match="MODEL_ID_MISMATCH"):
        collect_proposal(wire(), "propose_route", model_id="another-model")
    chunks[3] = b'data: {"choices":[],"usage":{"prompt_tokens":true,"completion_tokens":6}}\n\n'
    with pytest.raises(ValueError, match="INVALID_STREAM_USAGE"):
        collect_proposal(chunks, "propose_route")


def test_cancel_closes_provider_stream_without_claiming_remote_cancellation(monkeypatch):
    closed, updates = [], []
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            yield from wire(tool=True)
        def close(self):
            closed.append(True)
    original = httpx.Client
    monkeypatch.setattr(model_stream.httpx, "Client", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(200,
            headers={"content-type": "text/event-stream"}, stream=Bytes())), **kwargs))
    with pytest.raises(StreamStopped):
        classify_stream("request", "access", settings(), on_progress=updates.append,
                        should_continue=lambda: len(updates) < 2)
    assert closed == [True] and not any(v["phase"] == "validated" for v in updates)

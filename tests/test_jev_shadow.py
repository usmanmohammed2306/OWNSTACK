import copy
import json

import httpx
import pytest

from ownstack.jev_shadow import ENDPOINT, MODEL, JevFailure, evaluate_synthetic, parse_result


def fixture_result():
    return {"model": MODEL, "answers": {
        "route": {"type": "choice", "choice": "access", "confidence": 0.8,
            "probabilities": {"access": 0.8, "engineering": 0.1, "refuse": 0.05, "clarify": 0.05}},
        "asks_bypass": {"type": "noul", "noul": 0.02}}, "usage": {"input_tokens": 123}}


def test_documented_typed_endpoint_and_separate_shadow_authority():
    captured = []
    def provider(request):
        captured.append(request)
        return httpx.Response(200, json=fixture_result())
    result = evaluate_synthetic("Synthetic temporary read-only request", api_key="offline-test-key", transport=httpx.MockTransport(provider))
    request = captured[0]
    assert str(request.url) == ENDPOINT
    assert json.loads(request.content)["model"] == MODEL
    assert set(json.loads(request.content)) == {"model", "state", "questions"}
    assert result.route == "access" and result.input_tokens == 123
    assert result.authority == "shadow comparison only; no application action"


@pytest.mark.parametrize("value", [float('nan'), float('inf'), -0.1, 1.1, True, "0.8"])
def test_probability_rejects_invalid_or_coerced_values(value):
    payload = fixture_result()
    payload["answers"]["route"]["confidence"] = value
    with pytest.raises(JevFailure, match="INVALID_TYPED"):
        parse_result(payload, 1)


@pytest.mark.parametrize("change", ["model", "missing", "unknown_choice", "mass", "tokens"])
def test_model_and_answer_contract_drift_fail_closed(change):
    payload = copy.deepcopy(fixture_result())
    if change == "model": payload["model"] = "jev-latest"
    if change == "missing": del payload["answers"]["asks_bypass"]
    if change == "unknown_choice": payload["answers"]["route"]["choice"] = "approve"
    if change == "mass": payload["answers"]["route"]["probabilities"]["access"] = 0.1
    if change == "tokens": payload["usage"]["input_tokens"] = True
    with pytest.raises(JevFailure): parse_result(payload, 1)


def test_missing_key_never_dispatches():
    def forbidden(request): raise AssertionError("No dispatch without a separate key")
    with pytest.raises(JevFailure, match="NOT_CONFIGURED"):
        evaluate_synthetic("Synthetic input", api_key="", transport=httpx.MockTransport(forbidden))


@pytest.mark.parametrize("status", [307, 429, 503])
def test_provider_failures_do_not_retry_redirect_or_leak_body(status):
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://untrusted.example"}, text="secret-like-provider-body")
    with pytest.raises(JevFailure, match="PROVIDER_UNAVAILABLE") as error:
        evaluate_synthetic("Synthetic input", api_key="offline-test-key", transport=httpx.MockTransport(provider))
    assert len(calls) == 1 and "secret-like" not in str(error.value)


def test_large_response_is_not_accepted():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'x'*65537))
    with pytest.raises(JevFailure, match="TOO_LARGE"):
        evaluate_synthetic("Synthetic input", api_key="offline-test-key", transport=transport)

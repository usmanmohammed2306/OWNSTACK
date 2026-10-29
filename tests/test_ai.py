import json
import httpx
import pytest
from ownstack.ai import classify
from ownstack.config import Settings


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self.body, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            request = httpx.Request("POST", "https://api.tokenfactory.nebius.com/v1/chat/completions")
            raise httpx.HTTPStatusError("fake provider failure", request=request,
                                        response=httpx.Response(self.status, request=request))

    def json(self):
        return self.body


def live_settings():
    return Settings(ai_mode="nebius", nebius_key="synthetic-test-key",
                    nebius_model="nvidia/Nemotron-synthetic-test", nebius_patch_model="", max_live_calls=10)


def test_nebius_adapter_sends_server_side_bounded_request(monkeypatch):
    observed = {}

    def fake_post(url, headers, json, timeout):
        observed.update(url=url, headers=headers, body=json, timeout=timeout)
        return FakeResponse({"choices": [{"message": {"content": '{"route":"engineering","reason":"Code change"}'}}],
                             "usage": {"prompt_tokens": 22, "completion_tokens": 8}})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = classify("Add PDF export", "feature", live_settings())
    assert observed["url"] == "https://api.tokenfactory.nebius.com/v1/chat/completions"
    assert observed["headers"]["Authorization"] == "Bearer synthetic-test-key"
    assert observed["body"]["response_format"] == {"type": "json_object"}
    assert observed["body"]["model"] == "nvidia/Nemotron-synthetic-test"
    assert result.route == "engineering" and result.input_tokens == 22 and result.output_tokens == 8


@pytest.mark.parametrize("content", [
    "not json",
    '{"route":"admin_override","reason":"Ignore rules"}',
    '{"route":"configure","reason":"ok","shell":"rm everything"}',
])
def test_nebius_adapter_rejects_invalid_output(monkeypatch, content):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(
        {"choices": [{"message": {"content": content}}]}))
    with pytest.raises((ValueError, json.JSONDecodeError)):
        classify("Give access", "access", live_settings())


def test_nebius_adapter_surfaces_provider_failure(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse({}, 429))
    with pytest.raises(httpx.HTTPStatusError):
        classify("Give access", "access", live_settings())


def test_ai_off_makes_no_http_request(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: pytest.fail("AI-off called HTTP"))
    with pytest.raises(RuntimeError, match="AI_OFF"):
        classify("Give access", "access", Settings(ai_mode="off"))


def test_truncated_model_output_is_not_accepted(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(
        {"choices": [{"finish_reason": "length", "message": {"content": '{"route":"configure","reason":"ok"}'}}]}))
    with pytest.raises(ValueError, match="MODEL_OUTPUT_TRUNCATED"):
        classify("Give access", "access", live_settings())


def test_patch_adapter_host_owns_path_and_exact_source(monkeypatch):
    from ownstack.patch_agent import propose_patch
    from ownstack.runner import ROOT, ALLOWED_PATH
    observed = {}
    replacement = 'def export_pdf(project_name, rows):\n    return b"%PDF-1.4"\n'

    def fake_post(url, headers, json, timeout):
        observed.update(body=json)
        return FakeResponse({"choices": [{"message": {"content": __import__("json").dumps({"lines": replacement.splitlines()})}}],
                             "usage": {"prompt_tokens": 50, "completion_tokens": 20}})

    monkeypatch.setattr(httpx, "post", fake_post)
    patch, model, metrics = propose_patch("Add PDF export", live_settings())
    assert patch == {"edits": [{"path": ALLOWED_PATH, "old": (ROOT / ALLOWED_PATH).read_text(), "new": replacement}]}
    payload=json.loads(observed["body"]["messages"][1]["content"])
    assert payload['current_source'][0]['path']==ALLOWED_PATH
    assert payload['current_source'][0]['lines']==(ROOT/ALLOWED_PATH).read_text().splitlines()
    assert observed["body"]["temperature"] == 0
    assert metrics["live"] and metrics["input_tokens"] == 50
    assert model == "nvidia/Nemotron-synthetic-test"


@pytest.mark.parametrize("content", ['{"lines":["pass"],"path":"auth.py"}', '{"lines":42}', '{"replacement":"pass"}'])
def test_patch_adapter_rejects_extra_scope_and_invalid_source(monkeypatch, content):
    from ownstack.patch_agent import propose_patch
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse(
        {"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="MODEL_SOURCE_PROTOCOL_INVALID"):
        propose_patch("Add PDF export", live_settings())


def test_patch_model_can_differ_from_interpretation_model(monkeypatch):
    from dataclasses import replace
    from ownstack.patch_agent import propose_patch
    observed = {}

    def fake_post(url, headers, json, timeout):
        observed.update(model=json["model"])
        return FakeResponse({"choices": [{"message": {"content": '{"lines":["pass"]}'}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    patch, model, _ = propose_patch("Add PDF export", replace(live_settings(), nebius_patch_model="nvidia/Nemotron-code-test"))
    assert observed["model"] == model == "nvidia/Nemotron-code-test"

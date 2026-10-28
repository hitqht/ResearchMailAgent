import json

import httpx
import pytest

from researchmail.llm.models import AIError, ModelConfig
from researchmail.llm.providers import OllamaProvider, OpenAICompatibleProvider


def cloud(auth="none"):
    return ModelConfig(
        label="Test",
        provider="openai_compatible",
        model="synthetic",
        base_url="https://example.invalid/v1",
        auth=auth,
    )


def test_openai_http_contract_auth_and_no_tools():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-secret"
        payload = json.loads(request.content)
        assert "tools" not in payload and payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]},
        )

    provider = OpenAICompatibleProvider(
        cloud("bearer"), "synthetic-secret", httpx.MockTransport(handler)
    )
    assert provider.complete("JSON only", "synthetic", {}) == '{"ok":true}'


def test_ollama_preflight_and_structured_request():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        payload = json.loads(request.content)
        if request.url.path == "/api/show":
            assert payload == {"model": "synthetic"}
            return httpx.Response(200, json={"model_info": {"general.architecture": "synthetic"}})
        assert payload["stream"] is False and payload["format"] == {"type": "object"}
        return httpx.Response(200, json={"message": {"content": "{}"}, "done": True})

    config = ModelConfig(
        label="Local", provider="ollama", model="synthetic", base_url="http://127.0.0.1:11434"
    )
    assert (
        OllamaProvider(config, transport=httpx.MockTransport(handler)).complete(
            "rules", "body", {"type": "object"}
        )
        == "{}"
    )
    assert calls == ["/api/show", "/api/chat"]


@pytest.mark.parametrize(
    "details",
    [
        {"remote_host": "https://ollama.com", "model_info": {}},
        {"remote_model": "cloud", "model_info": {"arch": "synthetic"}},
        {"model_info": {}},
        {},
    ],
)
def test_ollama_cloud_alias_blocked_before_email_request(details):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert "PRIVATE EMAIL" not in request.content.decode()
        return httpx.Response(200, json=details)

    config = ModelConfig(
        label="Local", provider="ollama", model="alias", base_url="http://127.0.0.1:11434"
    )
    with pytest.raises(AIError, match="privacy"):
        OllamaProvider(config, transport=httpx.MockTransport(handler)).complete(
            "rules", "PRIVATE EMAIL", {}
        )
    assert calls == ["/api/show"]


@pytest.mark.parametrize(
    "status,expected", [(401, "auth"), (403, "auth"), (302, "response"), (500, "response")]
)
def test_http_errors_sanitized(status, expected):
    def handler(request):
        return httpx.Response(status, text="SENSITIVE PROVIDER ERROR")

    with pytest.raises(AIError, match=expected) as error:
        OpenAICompatibleProvider(cloud(), transport=httpx.MockTransport(handler)).complete(
            "", "", {}
        )
    assert "SENSITIVE" not in str(error.value)


@pytest.mark.parametrize(
    "error,expected",
    [(httpx.ReadTimeout("private"), "timeout"), (httpx.ConnectError("private"), "network")],
)
def test_network_errors(error, expected):
    def handler(request):
        raise error

    with pytest.raises(AIError, match=expected):
        OpenAICompatibleProvider(cloud(), transport=httpx.MockTransport(handler)).complete(
            "", "", {}
        )


@pytest.mark.parametrize(
    "body",
    [
        b"no json",
        b"[]",
        b'{"choices":[]}',
        b"{}",
        b"x" * 1000001,
        json.dumps(
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
        ).encode(),
        json.dumps(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "{}", "tool_calls": [{}]}}
                ]
            }
        ).encode(),
    ],
    ids=[
        "non-json",
        "array",
        "empty-choices",
        "missing-choices",
        "oversized",
        "truncated",
        "tools",
    ],
)
def test_invalid_provider_response(body):
    def handler(request):
        return httpx.Response(200, content=body)

    with pytest.raises(AIError, match="response"):
        OpenAICompatibleProvider(cloud(), transport=httpx.MockTransport(handler)).complete(
            "", "", {}
        )


def test_no_request_when_required_key_is_missing():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(AIError, match="auth"):
        OpenAICompatibleProvider(cloud("bearer"), transport=httpx.MockTransport(handler)).complete(
            "", "", {}
        )
    assert calls == []


def test_api_key_header_not_url():
    def handler(request):
        assert request.headers["x-api-key"] == "synthetic-value"
        assert not request.url.query
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
        )

    assert (
        OpenAICompatibleProvider(
            cloud("x-api-key"), "synthetic-value", httpx.MockTransport(handler)
        ).complete("", "", {})
        == "{}"
    )

"""Tests for OpenRouter integration with mocked HTTP."""

from __future__ import annotations

import json

import httpx
import pytest

from cnc_intelligence.config import Settings
from cnc_intelligence.llm_service import (
    LLMServiceError,
    OpenRouterClient,
    build_user_prompt,
    direct_answer_payload,
)
from cnc_intelligence.question_router import route_question


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_build_user_prompt_includes_only_record(sample_record) -> None:
    prompt = build_user_prompt(sample_record, "What material is used?")
    assert "2280" in prompt
    assert "Aluminum 6061-T6" in prompt
    assert "What material is used?" in prompt
    # Must not dump unrelated workbook content
    assert "9901" not in prompt


def test_successful_response(sample_record, settings_ready, monkeypatch) -> None:
    payload = {
        "answer": "Material is Aluminum 6061-T6.",
        "status": "answered",
        "evidence": [{"column": "Material", "value": "Aluminum 6061-T6"}],
        "missing_information": [],
        "limitations": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["model"] == "test/model-id"
        assert "Authorization" in request.headers
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    client = OpenRouterClient(settings_ready)

    def fake_post(payload_dict):
        # Bypass real network by calling handler through MockTransport
        transport = _mock_transport(handler)
        with httpx.Client(transport=transport, base_url=settings_ready.openrouter_base_url) as c:
            response = c.post(
                "/chat/completions",
                headers=client._headers(),
                json=payload_dict,
            )
        return client._handle_http_response(response)

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.answer_question(sample_record, "What material is used?")
    assert result["status"] == "answered"
    assert result["evidence"][0]["column"] == "Material"


def test_missing_api_key(sample_record, settings_missing_key) -> None:
    client = OpenRouterClient(settings_missing_key)
    with pytest.raises(LLMServiceError) as exc:
        client.ensure_configured()
    assert exc.value.code == "missing_api_key"


def test_invalid_api_key(settings_ready, monkeypatch) -> None:
    client = OpenRouterClient(settings_ready)

    def fake_post(_payload):
        raise LLMServiceError(
            "The AI service rejected the API key (unauthorized).",
            code="invalid_api_key",
        )

    # Exercise HTTP handler path
    response = httpx.Response(401, json={"error": "unauthorized"})
    with pytest.raises(LLMServiceError) as exc:
        client._handle_http_response(response)
    assert exc.value.code == "invalid_api_key"


def test_rate_limit(settings_ready) -> None:
    client = OpenRouterClient(settings_ready)
    response = httpx.Response(429, json={"error": "rate limit"})
    with pytest.raises(LLMServiceError) as exc:
        client._handle_http_response(response)
    assert exc.value.code == "rate_limit"


def test_timeout(settings_ready, monkeypatch) -> None:
    client = OpenRouterClient(settings_ready)

    def boom(_payload):
        raise httpx.TimeoutException("timed out")

    # Patch httpx.Client.post indirectly via _post implementation
    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "Client", BoomClient)
    with pytest.raises(LLMServiceError) as exc:
        client._post({"model": "x", "messages": []})
    assert exc.value.code == "timeout"


def test_network_failure(settings_ready, monkeypatch) -> None:
    client = OpenRouterClient(settings_ready)

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise httpx.NetworkError("offline")

    monkeypatch.setattr(httpx, "Client", BoomClient)
    with pytest.raises(LLMServiceError) as exc:
        client._post({"model": "x", "messages": []})
    assert exc.value.code == "network_error"


def test_malformed_response(settings_ready) -> None:
    client = OpenRouterClient(settings_ready)
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "NOT JSON {{"}}]},
    )
    data = client._handle_http_response(response)
    content = client._content_from_response(data)
    from cnc_intelligence.llm_service import _extract_json_object

    with pytest.raises(LLMServiceError) as exc:
        _extract_json_object(content)
    assert exc.value.code == "malformed_response"


def test_empty_response(settings_ready) -> None:
    client = OpenRouterClient(settings_ready)
    with pytest.raises(LLMServiceError) as exc:
        client._content_from_response({"choices": [{"message": {"content": ""}}]})
    assert exc.value.code == "empty_response"


def test_invalid_structured_output_still_parsed_when_fenced(settings_ready) -> None:
    from cnc_intelligence.llm_service import _extract_json_object

    text = '```json\n{"answer": "ok", "status": "answered", "evidence": [], "missing_information": [], "limitations": []}\n```'
    data = _extract_json_object(text)
    assert data["answer"] == "ok"


def test_missing_model_config(sample_record) -> None:
    settings = Settings(OPENROUTER_API_KEY="sk-test-key-12345678", OPENROUTER_MODEL="")
    client = OpenRouterClient(settings)
    with pytest.raises(LLMServiceError) as exc:
        client.ensure_configured()
    assert exc.value.code == "missing_model"


def test_direct_answer_payload_no_llm(sample_record) -> None:
    routed = route_question("What material is used?", sample_record)
    payload = direct_answer_payload(sample_record, routed)
    assert payload["status"] == "answered"
    assert payload["evidence"][0]["column"] == "Material"


def test_invalid_model_http(settings_ready) -> None:
    client = OpenRouterClient(settings_ready)
    response = httpx.Response(404, json={"error": "not found"})
    with pytest.raises(LLMServiceError) as exc:
        client._handle_http_response(response)
    assert exc.value.code == "invalid_model"

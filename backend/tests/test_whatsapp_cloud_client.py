import json
import logging

import httpx

from app.core.config import settings
from app.integrations.meta.messaging import MetaMessageResult
from app.integrations.meta.whatsapp_client import WhatsappClient, WhatsappMessageResult


def _use_transport(client: WhatsappClient, handler) -> None:
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=30.0)


def test_send_template_message_uses_confirmed_shape(monkeypatch):
    monkeypatch.setattr(settings, "META_MOCK_PRIVATE_REPLIES", False)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "16315551234", "wa_id": "16315551234"}],
                "messages": [{"id": "wamid.template-1"}],
            },
        )

    client = WhatsappClient(base_url="https://graph.test/v99.0")
    _use_transport(client, handler)
    components = [{"type": "body", "parameters": [{"type": "text", "text": "Ada"}]}]

    result = client.send_template_message(
        access_token="test-access-token",
        phone_number_id="phone-number-id",
        to="16315551234",
        template_name="welcome_customer",
        language="en_US",
        components=components,
    )

    assert isinstance(result, WhatsappMessageResult)
    assert isinstance(result.message_result, MetaMessageResult)
    assert result.success is True
    assert result.provider_message_id == "wamid.template-1"
    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path == "/v99.0/phone-number-id/messages"
    assert request.headers["Authorization"] == "Bearer test-access-token"
    assert request.read()
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "16315551234",
        "type": "template",
        "template": {
            "name": "welcome_customer",
            "language": {"code": "en_US"},
            "components": components,
        },
    }
    client.close()


def test_send_template_message_retains_numeric_meta_error_without_sensitive_logs(monkeypatch, caplog):
    monkeypatch.setattr(settings, "META_MOCK_PRIVATE_REPLIES", False)

    def handler(_request: httpx.Request) -> httpx.Response:
        # UNVERIFIED SHAPE: Graph's current error reference was inaccessible
        # during verification; keep the standard shape tolerant in the client.
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Template parameter mismatch",
                    "code": 132000,
                    "error_subcode": 2494073,
                    "error_data": {"details": "private fixture details"},
                }
            },
        )

    client = WhatsappClient(base_url="https://graph.test/v99.0")
    _use_transport(client, handler)
    with caplog.at_level(logging.ERROR):
        result = client.send_template_message(
            "secret-test-token",
            "phone-number-id",
            "16315551234",
            "welcome_customer",
            "en_US",
            [],
        )

    assert result.success is False
    assert result.meta_error_code == 132000
    assert result.meta_error_subcode == 2494073
    assert result.message_result.error_code == "unclassified"
    assert result.retryable is True
    assert any(getattr(record, "recipient_wa_id", None) == "***1234" for record in caplog.records)
    rendered_logs = " ".join(record.getMessage() for record in caplog.records)
    assert "secret-test-token" not in rendered_logs
    assert "16315551234" not in rendered_logs
    assert "private fixture details" not in rendered_logs
    client.close()


def test_send_template_message_keeps_mock_mode_hermetic(monkeypatch):
    monkeypatch.setattr(settings, "META_MOCK_PRIVATE_REPLIES", True)
    client = WhatsappClient(base_url="https://graph.test/v99.0")

    def should_not_run(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("mock mode must not issue HTTP requests")

    _use_transport(client, should_not_run)
    result = client.send_template_message(
        "unused-token",
        "phone-number-id",
        "16315551234",
        "welcome_customer",
        "en_US",
        [],
    )

    assert result.success is True
    assert result.provider_message_id == "mock_wa_template_message"
    assert result.meta_error_code is None
    assert result.meta_error_subcode is None
    assert "16315551234" not in str(result.raw_response)
    client.close()


def test_send_template_message_catches_general_http_error(monkeypatch):
    monkeypatch.setattr(settings, "META_MOCK_PRIVATE_REPLIES", False)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.HTTPError("non-network HTTP client failure")

    client = WhatsappClient(base_url="https://graph.test/v99.0")
    _use_transport(client, handler)
    result = client.send_template_message(
        "secret-test-token",
        "phone-number-id",
        "16315551234",
        "welcome_customer",
        "en_US",
        [],
    )

    assert result.success is False
    assert result.error_code == "http_error"
    assert result.retryable is False
    client.close()


def test_send_template_message_timeout_is_not_retryable_because_outcome_is_unknown(monkeypatch):
    monkeypatch.setattr(settings, "META_MOCK_PRIVATE_REPLIES", False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out after request may have been sent", request=request)

    client = WhatsappClient(base_url="https://graph.test/v99.0")
    _use_transport(client, handler)
    result = client.send_template_message(
        "secret-test-token",
        "phone-number-id",
        "16315551234",
        "welcome_customer",
        "en_US",
        [],
    )

    assert result.success is False
    assert result.error_code == "timeout"
    assert result.retryable is False
    assert "outcome unknown" in result.error_message
    client.close()

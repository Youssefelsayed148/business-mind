import json

import httpx

from app.integrations.meta.whatsapp_management_client import (
    WhatsappManagementClient,
    WhatsappPhoneNumberHealth,
)


def _client_with_handler(handler) -> WhatsappManagementClient:
    client = WhatsappManagementClient(base_url="https://graph.test/v99.0")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=30.0)
    return client


def test_create_template_uses_confirmed_request_and_response_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "template-id", "status": "PENDING", "category": "UTILITY"})

    client = _client_with_handler(handler)
    components = [{"type": "BODY", "text": "Your order is ready"}]
    result = client.create_template(
        "test-access-token",
        "waba-id",
        "order_ready",
        "en_US",
        "UTILITY",
        components,
    )

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path == "/v99.0/waba-id/message_templates"
    assert request.headers["Authorization"] == "Bearer test-access-token"
    assert json.loads(request.content) == {
        "name": "order_ready",
        "language": "en_US",
        "category": "UTILITY",
        "components": components,
    }
    assert result.success is True
    assert result.data == {"id": "template-id", "status": "PENDING", "category": "UTILITY"}
    client.close()


def test_list_templates_follows_cursor_pages_and_requests_only_confirmed_fields():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("after") is None:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "one", "name": "first", "language": "en_US", "status": "APPROVED"}],
                    # `paging.next` is the standard Graph signal; the accessible
                    # current template fixture only exposes cursors, so this is
                    # intentionally an UNVERIFIED SHAPE fixture for this endpoint.
                    "paging": {"cursors": {"after": "cursor-1"}, "next": "https://graph.test/next"},
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"id": "two", "name": "second", "category": "MARKETING"}]},
        )

    client = _client_with_handler(handler)
    result = client.list_templates("test-access-token", "waba-id", limit=25)

    assert result.success is True
    assert [row["id"] for row in result.data] == ["one", "two"]
    assert len(requests) == 2
    assert requests[0].url.params["fields"] == "name,language,status,category,components,id"
    assert requests[0].url.params["limit"] == "25"
    assert requests[1].url.params["after"] == "cursor-1"
    client.close()


def test_delete_template_by_name():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        # UNVERIFIED SHAPE: Meta's accessible current collection confirms the
        # delete-by-name operation but does not expose its response example.
        return httpx.Response(200, json={"success": True})

    client = _client_with_handler(handler)
    result = client.delete_template_by_name("test-access-token", "waba-id", "order_ready")

    assert result.success is True
    assert result.data == {"success": True}
    assert captured["request"].method == "DELETE"
    assert captured["request"].url.params["name"] == "order_ready"
    client.close()


def test_phone_health_requests_confirmed_fields_and_tolerates_optional_extras():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "phone-id",
                        "verified_name": "Example Shop",
                        "display_phone_number": "+1 631-555-1234",
                        "quality_rating": "GREEN",
                        # UNVERIFIED SHAPE: these optional fields are observed in
                        # integrations but absent from the accessible current
                        # Meta phone-number field reference.
                        "messaging_limit_tier": "TIER_1K",
                        "status": "CONNECTED",
                    },
                    {"id": "phone-id-2", "quality_rating": "NA"},
                ]
            },
        )

    client = _client_with_handler(handler)
    result = client.get_phone_number_health("test-access-token", "waba-id")

    assert result.success is True
    assert captured["request"].url.path == "/v99.0/waba-id/phone_numbers"
    assert captured["request"].url.params["fields"] == "id,verified_name,display_phone_number,quality_rating"
    assert result.data == [
        WhatsappPhoneNumberHealth(
            id="phone-id",
            verified_name="Example Shop",
            display_phone_number="+1 631-555-1234",
            quality_rating="GREEN",
            messaging_limit_tier="TIER_1K",
            status="CONNECTED",
        ),
        WhatsappPhoneNumberHealth(
            id="phone-id-2",
            verified_name=None,
            display_phone_number=None,
            quality_rating="NA",
        ),
    ]
    client.close()


def test_management_error_parsing_is_tolerant_and_numeric():
    def handler(_request: httpx.Request) -> httpx.Response:
        # UNVERIFIED SHAPE: Graph's current error reference was inaccessible
        # during verification; unknown keys and numeric strings are tolerated.
        return httpx.Response(
            400,
            json={"error": {"message": "Bad request", "code": "100", "error_subcode": 2388003, "extra": True}},
        )

    client = _client_with_handler(handler)
    result = client.delete_template_by_name("test-access-token", "waba-id", "order_ready")

    assert result.success is False
    assert result.error_message == "Bad request"
    assert result.meta_error_code == 100
    assert result.meta_error_subcode == 2388003
    client.close()

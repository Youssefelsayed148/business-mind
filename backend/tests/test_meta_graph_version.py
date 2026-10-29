"""Version routing across Meta hosts, with HTTP entirely mocked."""
import asyncio

import httpx
import pytest

from app.core.config import Settings, settings
from app.integrations.meta import accounts, facebook_oauth, oauth, whatsapp_oauth
from app.integrations.meta.client import MetaGraphClient
from app.integrations.meta.facebook_client import FacebookClient
from app.integrations.meta.messaging import MetaMessagingClient
from app.integrations.meta.token_refresh import META_REFRESH_TOKEN_URL
from app.integrations.meta.whatsapp_client import WhatsappClient
from app.integrations.meta.whatsapp_management_client import WhatsappManagementClient


def test_approved_default_version():
    assert Settings.model_fields['META_GRAPH_API_VERSION'].default == 'v26.0'


@pytest.mark.parametrize('version', ['v26.0', 'v99.0'])
@pytest.mark.parametrize('client_type,host', [
    (MetaMessagingClient, 'graph.instagram.com'),
    (FacebookClient, 'graph.facebook.com'),
    (WhatsappClient, 'graph.facebook.com'),
    (WhatsappManagementClient, 'graph.facebook.com'),
])
def test_sync_clients_use_configured_version(monkeypatch, version, client_type, host):
    monkeypatch.setattr(settings, 'META_GRAPH_API_VERSION', version)
    client = client_type()
    try:
        assert client.base_url == f'https://{host}/{version}'
    finally:
        client.close()


@pytest.mark.parametrize('version', ['v26.0', 'v99.0'])
def test_graph_client_uses_configured_version(monkeypatch, version):
    monkeypatch.setattr(settings, 'META_GRAPH_API_VERSION', version)

    async def check():
        client = MetaGraphClient()
        try:
            assert client.base_url == f'https://graph.facebook.com/{version}'
        finally:
            await client.close()

    asyncio.run(check())


@pytest.mark.parametrize('version', ['v26.0', 'v99.0'])
@pytest.mark.parametrize('function,args,host,path', [
    (facebook_oauth.verify_user_access_token, ('synthetic-token',), 'graph.facebook.com', '/debug_token'),
    (facebook_oauth.exchange_for_long_lived_token, ('synthetic-token',), 'graph.facebook.com', '/oauth/access_token'),
    (facebook_oauth.list_granted_pages, ('synthetic-token',), 'graph.facebook.com', '/me/accounts'),
    (facebook_oauth.subscribe_app_to_page, ('synthetic-token', '123'), 'graph.facebook.com', '/123/subscribed_apps'),
    (whatsapp_oauth.exchange_code_for_token, ('synthetic-code',), 'graph.facebook.com', '/oauth/access_token'),
    (whatsapp_oauth.exchange_for_long_lived_token, ('synthetic-token',), 'graph.facebook.com', '/oauth/access_token'),
    (whatsapp_oauth.fetch_phone_number_metadata, ('synthetic-token', '123'), 'graph.facebook.com', '/123'),
    (whatsapp_oauth.subscribe_app_to_waba, ('synthetic-token', '123'), 'graph.facebook.com', '/123/subscribed_apps'),
    (accounts.fetch_instagram_account_metadata, ('synthetic-token',), 'graph.instagram.com', '/me'),
    (accounts.fetch_instagram_media, ('synthetic-token',), 'graph.instagram.com', '/me/media'),
])
def test_oauth_and_instagram_profile_request_versions(monkeypatch, version, function, args, host, path):
    monkeypatch.setattr(settings, 'META_GRAPH_API_VERSION', version)
    monkeypatch.setattr(settings, 'FACEBOOK_APP_ID', 'synthetic-app')
    real_client = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        if path == '/debug_token':
            body = {'data': {'is_valid': True, 'app_id': 'synthetic-app'}}
        elif path in ('/me/accounts', '/me/media'):
            body = {'data': []}
        elif path == '/me':
            body = {'user_id': '123', 'username': 'synthetic'}
        else:
            body = {'access_token': 'synthetic-token', 'success': True}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: real_client(transport=httpx.MockTransport(handler)))
    asyncio.run(function(*args))
    assert len(seen) == 1
    assert seen[0].url.host == host
    assert seen[0].url.path == f'/{version}{path}'


def test_instagram_login_and_token_endpoints_are_unversioned():
    assert oauth.META_OAUTH_BASE == 'https://www.instagram.com/oauth/authorize'
    assert oauth.META_TOKEN_EXCHANGE_URL == 'https://api.instagram.com/oauth/access_token'
    assert oauth.META_LONG_LIVED_TOKEN_URL == 'https://graph.instagram.com/access_token'
    assert META_REFRESH_TOKEN_URL == 'https://graph.instagram.com/refresh_access_token'

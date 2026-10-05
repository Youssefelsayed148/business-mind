from app.core.config import Settings, settings


def _settings(**overrides) -> Settings:
    base = dict(META_APP_SECRET="ig_secret", META_WEBHOOK_SECRET="", FACEBOOK_APP_ID="", FACEBOOK_APP_SECRET="")
    return settings.model_copy(update={**base, **overrides})


def test_facebook_app_falls_back_to_meta_values():
    s = _settings(META_APP_ID="ig_app")
    assert s.facebook_app_id == "ig_app"
    assert s.facebook_app_secret == "ig_secret"
    assert s.webhook_secrets == ["ig_secret"]


def test_separate_facebook_app_is_used_and_both_secrets_verify_webhooks():
    s = _settings(META_APP_ID="ig_app", FACEBOOK_APP_ID="fb_app", FACEBOOK_APP_SECRET="fb_secret")
    assert s.facebook_app_id == "fb_app"
    assert s.facebook_app_secret == "fb_secret"
    assert s.webhook_secrets == ["ig_secret", "fb_secret"]


def test_webhook_secret_overrides_instagram_secret():
    s = _settings(META_WEBHOOK_SECRET="wh", FACEBOOK_APP_SECRET="fb_secret")
    assert s.webhook_secrets == ["wh", "fb_secret"]

import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet

_spec = importlib.util.spec_from_file_location(
    "preflight_prod", Path(__file__).parents[2] / "scripts" / "preflight_prod.py"
)
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


def _good_env() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "APP_BASE_URL": "https://a.example.com",
        "FRONTEND_URL": "https://a.example.com",
        "ALLOWED_ORIGINS": "https://a.example.com",
        "DATABASE_URL": "postgresql://x",
        "REDIS_URL": "redis://r",
        "DISABLE_DOCS": "true",
        "TRUST_PROXY_HEADERS": "true",
        "META_MOCK_PRIVATE_REPLIES": "false",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "JWT_SECRET": "a" * 64,
        "APP_SECRET_KEY": "b" * 64,
        "META_APP_ID": "1",
        "META_APP_SECRET": "s",
        "META_WEBHOOK_VERIFY_TOKEN": "t",
        "OPENAI_API_KEY": "sk-test",
    }


def test_good_env_passes_every_check():
    assert all(ok for _, ok in preflight.run_checks(_good_env()))


def test_each_bad_value_fails_a_check():
    for key, bad in [
        ("APP_ENV", "development"),
        ("DISABLE_DOCS", "false"),
        ("TRUST_PROXY_HEADERS", "false"),
        ("META_MOCK_PRIVATE_REPLIES", "true"),
        ("TOKEN_ENCRYPTION_KEY", "not-a-key"),
        ("JWT_SECRET", "change_me"),
        ("APP_SECRET_KEY", "change_me_local_app_secret"),
        ("ALLOWED_ORIGINS", "http://a.example.com"),
        ("OPENAI_API_KEY", ""),
    ]:
        env = _good_env()
        env[key] = bad
        assert not all(ok for _, ok in preflight.run_checks(env)), key


def test_missing_required_var_fails():
    env = _good_env()
    del env["REDIS_URL"]
    assert not preflight.run_checks(env)[0][1]


def test_output_never_contains_values(tmp_path, capsys):
    env = _good_env()
    path = tmp_path / "env"
    path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
    preflight.main(["preflight_prod.py", str(path)])
    out = capsys.readouterr().out
    assert env["JWT_SECRET"] not in out and env["TOKEN_ENCRYPTION_KEY"] not in out

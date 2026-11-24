"""Seed the throwaway SaaS database: demo tenant + bot, and one channel
connection per platform pointing at http://many-api:8000 (fake rows only)."""

import os
import sys
from uuid import UUID

sys.path[:0] = ["/app", "/e2e"]
from ids import CONNECTION_IDS, MANY_URL  # noqa: E402

from app.channels.secrets import encrypt_secret  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import ChannelConnection  # noqa: E402
from app.db.session import create_db_engine, session_factory  # noqa: E402
from app.knowledge.storage import get_storage  # noqa: E402
from scripts.seed_demo import seed_demo  # noqa: E402

settings = get_settings()
print(f"[saas-seed] ENVIRONMENT={settings.environment}")
engine = create_db_engine(settings)
with session_factory(engine)() as db:
    result = seed_demo(db, get_storage(settings), settings, "fake-demo-" + os.urandom(6).hex())
    for channel, connection_id in CONNECTION_IDS.items():
        if db.get(ChannelConnection, UUID(connection_id)) is not None:
            continue
        db.add(
            ChannelConnection(
                id=UUID(connection_id),
                tenant_id=result.tenant_id,
                bot_id=result.bot_id,
                channel=channel,
                display_name=f"e2e {channel}",
                many_base_url=MANY_URL,
                status="active",
                ai_enabled=True,
                secret_ciphertext=encrypt_secret(
                    os.environ["SECRET_" + channel.upper()], settings.channel_secret_encryption_keys
                ),
                secret_key_version=1,
                health_status="unknown",
            )
        )
    db.commit()
print(
    f"[saas-seed] tenant={result.tenant_id} bot={result.bot_id} created={result.created}; "
    f"3 connections -> {MANY_URL}"
)
engine.dispose()

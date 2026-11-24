"""Seed the throwaway Many database: six fake channels (3 platforms x delegation
ON/OFF). Delegation is switched on through the real apply_config, so the new
allowlist validator resolves saas-api live."""

import os
import sys
from uuid import uuid4

sys.path[:0] = ["/app", "/e2e"]
from ids import CONNECTION_IDS, MANY_CHANNELS, SAAS_URL  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.facebook_page import FacebookPage  # noqa: E402
from app.models.instagram_account import InstagramAccount  # noqa: E402
from app.models.whatsapp_account import WhatsappAccount  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import saas_delegation_service as delegation  # noqa: E402
from app.services import (  # noqa: E402
    facebook_token_service,
    token_service,
    whatsapp_token_service,
)

db = SessionLocal()
workspace = Workspace(id=uuid4(), name="E2E workspace", slug=f"e2e-{uuid4().hex[:8]}")
db.add(workspace)
db.flush()
for (platform, on), ref in MANY_CHANNELS.items():
    common = {"id": uuid4(), "workspace_id": workspace.id, "ai_enabled": False}
    if platform == "instagram":
        channel = InstagramAccount(ig_user_id=ref, ig_username=f"e2e_{ref}", **common)
    elif platform == "whatsapp":
        channel = WhatsappAccount(phone_number_id=ref, **common)
    else:
        channel = FacebookPage(page_id=ref, page_name=f"e2e {ref}", **common)
    db.add(channel)
    db.flush()
    fake_token = "fake-access-token-" + uuid4().hex
    if platform == "instagram":
        token_service.store_encrypted_token(db, workspace.id, channel.id, fake_token, commit=False)
    elif platform == "whatsapp":
        whatsapp_token_service.store_encrypted_token(db, channel.id, fake_token, commit=False)
    else:
        facebook_token_service.store_encrypted_token(db, channel.id, fake_token, commit=False)
    if on:
        delegation.apply_config(
            channel,
            {
                "saas_connection_id": CONNECTION_IDS[platform],
                "saas_base_url": SAAS_URL,
                "secret": os.environ["SECRET_" + platform.upper()],
                "saas_delegation_enabled": True,
            },
        )
    state = "ON " if on else "OFF"
    print(f"[many-seed] {platform:9s} delegation={state} ref={ref} url={channel.saas_base_url}")
db.commit()
db.close()

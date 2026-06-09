import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.campaign import CampaignCreate
from app.services.campaign_matcher import (
    find_matching_campaigns,
    find_matching_keyword,
    keyword_matches,
)
from app.services.campaign_service import (
    activate_campaign,
    add_keyword,
    archive_campaign,
    create_campaign,
    get_campaign,
    list_campaigns,
    pause_campaign,
    update_campaign,
)
from app.services.token_service import store_encrypted_token
from app.utils.crypto import encrypt_text
from tests.conftest import skip_if_no_db


def test_campaign_create_defaults_to_instant_delivery():
    payload = CampaignCreate(
        instagram_account_id=__import__("uuid").uuid4(),
        name="Instant",
        media_id="media_123",
        message_template="Hello {username}",
    )

    assert payload.delivery_mode == "instant"
    assert payload.follow_prompt_title is None


def test_follow_prompt_fields_required_for_follow_prompt_mode():
    with pytest.raises(Exception):
        CampaignCreate(
            instagram_account_id=__import__("uuid").uuid4(),
            name="Follow",
            media_id="media_123",
            message_template="Hello {username}",
            delivery_mode="follow_prompt",
        )


def test_follow_prompt_invalid_profile_url_rejected():
    with pytest.raises(Exception):
        CampaignCreate(
            instagram_account_id=__import__("uuid").uuid4(),
            name="Follow",
            media_id="media_123",
            message_template="Hello {username}",
            delivery_mode="follow_prompt",
            follow_prompt_title="Follow us",
            follow_prompt_description="Open the profile",
            follow_prompt_profile_url="instagram.com/not-a-valid-url",
        )


@skip_if_no_db
def test_create_campaign_with_keywords(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-campaign")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="111",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    payload = CampaignCreate(
        instagram_account_id=acc.id,
        name="Test Campaign",
        media_id="media_123",
        message_template="Hello {username}",
        keywords=["prompt", "ai"],
    )

    campaign = create_campaign(db_session, ws.id, payload)
    assert campaign.name == "Test Campaign"
    assert campaign.delivery_mode == "instant"
    assert len(campaign.keywords) == 2
    assert campaign.keywords[0].normalized_keyword == "prompt"


@skip_if_no_db
def test_duplicate_normalized_keyword_rejected(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-dup")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="222",
        ig_username="testacc2",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Dup Test",
            media_id="m1",
            message_template="Hi",
            keywords=["prompt"],
        ),
    )

    with pytest.raises(Exception):
        add_keyword(db_session, campaign.id, "PROMPT")  # same after normalization


@skip_if_no_db
def test_invalid_template_variable_rejected(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-tmpl")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="333",
        ig_username="testacc3",
    )
    db_session.add(acc)
    db_session.commit()

    with pytest.raises(Exception):
        create_campaign(
            db_session,
            ws.id,
            CampaignCreate(
                instagram_account_id=acc.id,
                name="Bad Tmpl",
                media_id="m1",
                message_template="Hello {invalid_var}",
                keywords=["test"],
            ),
        )


@skip_if_no_db
def test_activate_fails_with_no_keywords(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-no-kw")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="444",
        ig_username="testacc4",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="No KW",
            media_id="m1",
            message_template="Hi",
            keywords=[],
        ),
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        activate_campaign(db_session, campaign.id)
    assert exc_info.value.status_code == 422


@skip_if_no_db
def test_activate_fails_with_disconnected_account(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-disc")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="555",
        ig_username="testacc5",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Disc",
            media_id="m1",
            message_template="Hi",
            keywords=["test"],
        ),
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        activate_campaign(db_session, campaign.id)
    assert exc_info.value.status_code == 422


@skip_if_no_db
def test_contains_match(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-contains")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="666",
        ig_username="testacc6",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Contains",
            media_id="m1",
            message_template="Hi {username}",
            keywords=["prompt"],
            match_type="contains",
        ),
    )
    activate_campaign(db_session, campaign.id)

    matches = find_matching_campaigns(db_session, acc.id, "m1", "I want the prompt please")
    assert len(matches) == 1
    assert matches[0].matched_keyword == "prompt"


@skip_if_no_db
def test_any_media_and_specific_media_matching(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-target-media")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="666-target",
        ig_username="targetacc",
    )
    db_session.add(acc)
    db_session.commit()
    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    any_campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Any Offer",
            message_template="Hi",
            keywords=["offer"],
            target_scope="any_media",
        ),
    )
    specific_campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Specific Offer",
            message_template="Hi",
            keywords=["offer"],
            target_scope="specific_media",
            target_media_url="https://www.instagram.com/reel/ABC123/",
            target_media_id="media_rehearsal_001",
            target_media_type="reel",
            target_media_label="May Discount Reel",
        ),
    )
    waiting_campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Waiting Offer",
            message_template="Hi",
            keywords=["offer"],
            target_scope="specific_media",
            target_media_url="https://www.instagram.com/p/WAIT123/",
            target_media_type="post",
        ),
    )
    activate_campaign(db_session, any_campaign.id)
    activate_campaign(db_session, specific_campaign.id)
    activate_campaign(db_session, waiting_campaign.id)

    matching = find_matching_campaigns(db_session, acc.id, "media_rehearsal_001", "offer please")
    assert {match.campaign_id for match in matching} == {any_campaign.id, specific_campaign.id}

    non_matching = find_matching_campaigns(db_session, acc.id, "media_rehearsal_999", "offer please")
    assert {match.campaign_id for match in non_matching} == {any_campaign.id}


@skip_if_no_db
def test_exact_match(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-exact")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="777",
        ig_username="testacc7",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Exact",
            media_id="m1",
            message_template="Hi",
            keywords=["prompt"],
            match_type="exact",
        ),
    )
    activate_campaign(db_session, campaign.id)

    matches = find_matching_campaigns(db_session, acc.id, "m1", "prompt")
    assert len(matches) == 1

    no_matches = find_matching_campaigns(db_session, acc.id, "m1", "I want prompt")
    assert len(no_matches) == 0


@skip_if_no_db
def test_starts_with_match(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-sw")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="888",
        ig_username="testacc8",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="SW",
            media_id="m1",
            message_template="Hi",
            keywords=["promo"],
            match_type="starts_with",
        ),
    )
    activate_campaign(db_session, campaign.id)

    matches = find_matching_campaigns(db_session, acc.id, "m1", "promo code please")
    assert len(matches) == 1

    no_matches = find_matching_campaigns(db_session, acc.id, "m1", "get promo code")
    assert len(no_matches) == 0


@skip_if_no_db
def test_arabic_normalization_match(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-ar")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="999",
        ig_username="testacc9",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Arabic",
            media_id="m1",
            message_template="Hi",
            keywords=["برومبت"],
            match_type="contains",
        ),
    )
    activate_campaign(db_session, campaign.id)

    matches = find_matching_campaigns(db_session, acc.id, "m1", "أريد البرومبت")
    assert len(matches) == 1
    assert matches[0].matched_keyword == "برومبت"


@skip_if_no_db
def test_paused_campaign_does_not_match(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-paused")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="1010",
        ig_username="testacc10",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Paused",
            media_id="m1",
            message_template="Hi",
            keywords=["test"],
        ),
    )
    activate_campaign(db_session, campaign.id)
    pause_campaign(db_session, campaign.id)

    matches = find_matching_campaigns(db_session, acc.id, "m1", "test")
    assert len(matches) == 0


@skip_if_no_db
def test_draft_campaign_does_not_match_real(db_session: Session):
    ws = Workspace(id=__import__("uuid").uuid4(), name="Test", slug="test-draft")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="1111",
        ig_username="testacc11",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = create_campaign(
        db_session,
        ws.id,
        CampaignCreate(
            instagram_account_id=acc.id,
            name="Draft",
            media_id="m1",
            message_template="Hi",
            keywords=["test"],
        ),
    )
    # Stay in draft

    matches = find_matching_campaigns(db_session, acc.id, "m1", "test")
    assert len(matches) == 0

import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.integrations.meta.messaging import MetaMessagingClient
from app.integrations.meta.webhooks import (
    parse_instagram_comment_events,
    parse_instagram_message_events,
    parse_instagram_postback_events,
)
from app.integrations.meta.facebook_client import FacebookClient
from app.integrations.meta.facebook_webhooks import (
    parse_facebook_comment_events,
    parse_facebook_message_events,
    parse_facebook_postback_events,
)
from app.integrations.meta.whatsapp_client import WhatsappClient
from app.integrations.meta.whatsapp_ids import mask_wa_id
from app.integrations.meta.whatsapp_webhooks import (
    parse_whatsapp_message_events,
    parse_whatsapp_phone_quality_events,
    parse_whatsapp_raw_only_events,
    parse_whatsapp_status_events,
    parse_whatsapp_template_status_events,
)
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_comment import FacebookComment
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_contact import WhatsappContact
from app.services import ai_service, conversation_service
from app.services import facebook_token_service, whatsapp_token_service
from app.services.campaign_matcher import find_matching_campaigns, find_matching_keyword
from app.services.comment_service import upsert_comment
from app.services.cooldown_service import is_in_cooldown, record_cooldown
from app.services.facebook_campaign_matcher import find_matching_facebook_campaigns
from app.services.facebook_comment_service import upsert_facebook_comment
from app.services import facebook_cooldown_service
from app.services.facebook_lead_service import upsert_lead_from_facebook_comment
from app.services.facebook_message_service import create_queued_facebook_message
from app.services.lead_service import upsert_lead_from_comment
from app.services.log_service import log_action
from app.services.processed_event_service import build_event_key, check_and_mark_processed
from app.services.whatsapp_webhook_service import (
    process_inbound_whatsapp_event,
    process_whatsapp_phone_quality_events,
    process_whatsapp_status_events,
    process_whatsapp_template_status_events,
)
from app.services.whatsapp_window_service import in_service_window
from app.services.message_service import (
    create_queued_message,
    get_message_by_context,
    get_message_for_send,
    increment_retry_count,
    mark_message_expired,
    mark_message_failed,
    mark_message_sending,
    mark_message_sent,
    mark_message_skipped,
)
from app.services.template_service import render_campaign_message
from app.services.token_service import get_decrypted_token
from app.utils.db import is_unique_violation
from app.utils.templates import render_template
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_db() -> Session:
    return SessionLocal()


def _message_flow_details(
    delivery_mode: str,
    message_step: str,
    comment_id: str | None = None,
    trigger_keyword: str | None = None,
    lead_id: str | None = None,
    follow_prompt_profile_url: str | None = None,
) -> dict:
    details = {
        "delivery_mode": delivery_mode,
        "message_step": message_step,
        "comment_id": comment_id,
        "trigger_keyword": trigger_keyword,
    }
    if lead_id:
        details["lead_id"] = lead_id
    if follow_prompt_profile_url:
        details["follow_prompt_profile_url"] = follow_prompt_profile_url
    return details


def _matched_keyword_for_message(db: Session, message: Message) -> tuple[str | None, str | None]:
    if not message.comment_id:
        return None, None
    comment = db.query(Comment).filter(Comment.id == message.comment_id).first()
    if not comment:
        return None, None
    match_log = (
        db.query(AutomationLog)
        .filter(
            AutomationLog.campaign_id == message.campaign_id,
            AutomationLog.action == "campaign_matched",
            AutomationLog.details["comment_id"].astext == comment.comment_id,
        )
        .order_by(AutomationLog.created_at.desc())
        .first()
    )
    keyword = None
    if match_log and match_log.details:
        value = match_log.details.get("matched_keyword")
        keyword = value if isinstance(value, str) else None
    return comment.comment_id, keyword


def _create_lead_or_reuse_concurrent(db: Session, lead: Lead, lookup) -> Lead | None:
    """Insert a Lead, tolerating a concurrent insert of the same one.

    uq_lead_workspace_whatsapp_user / uq_lead_workspace_facebook_user do their
    job on a genuine race and raise IntegrityError. Left uncaught that unwinds
    all the way to process_webhook_event's handler, which marks the event
    failed -- and because check_and_mark_processed already consumed this
    event's dedup key, Meta's retry of the same webhook is then silently
    swallowed and the message is lost for good. Losing a race is not a reason
    to drop a customer's message, so recover onto the winner's row instead.

    Only a unique violation is a race. IntegrityError also covers CHECK,
    foreign-key and NOT NULL violations, and treating those as "someone beat
    us to it" would silently drop a customer's message on what is actually a
    data bug -- so anything else is re-raised and surfaces as a failed event.

    Returns the usable Lead, or None if the row is somehow still not visible
    (logged, and the caller skips this event rather than proceeding on a
    half-built object).
    """
    try:
        # Savepoint, not a bare add/commit: a unique violation poisons the
        # transaction, and a plain rollback would also throw away everything
        # else the caller has pending. Rolling back to a savepoint undoes only
        # the failed insert and leaves the session usable.
        with db.begin_nested():
            db.add(lead)
            db.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc):
            # A CHECK/FK/NOT NULL violation is a bug in how this Lead was
            # built, not contention. Let it reach process_webhook_event's
            # handler so it is recorded as a failed event rather than
            # disappearing into a skipped message.
            raise
        existing = lookup()
        if existing is not None:
            logger.info(
                "Lead creation lost a race; reusing the concurrently-created row",
                extra={"lead_id": str(existing.id)},
            )
            return existing
        logger.exception(
            "Lead creation conflicted but no matching row is visible",
            extra={"ig_user_id": lead.ig_user_id},
        )
        return None

    db.commit()
    db.refresh(lead)
    return lead


def _dispatch_ai_turn(
    db: Session,
    *,
    account,
    lead,
    campaign,
    inbound_text: str,
) -> None:
    """Create/find the conversation, store the inbound message, and dispatch
    an AI turn unless a human has taken the thread over.

    Shared by the campaign-continuation and cold-DM paths. `campaign` is None
    for cold DMs — the conversation and message rows then carry a NULL
    campaign_id and the AI context is built from account-level fields only.
    """
    campaign_id = campaign.id if campaign is not None else None

    conversation = conversation_service.get_or_create_conversation(
        db,
        workspace_id=account.workspace_id,
        lead_id=lead.id,
        campaign_id=campaign_id,
        instagram_account_id=account.id,
    )

    # Store the inbound message regardless of conversation status, so a human
    # taking over still sees the full thread.
    inbound_message = Message(
        campaign_id=campaign_id,
        lead_id=lead.id,
        conversation_id=conversation.id,
        direction="inbound",
        content=inbound_text,
        rendered_body=inbound_text,
        message_type="ai_conversation",
        status="received",
    )
    db.add(inbound_message)
    conversation_service.touch_conversation(db, conversation)
    db.commit()
    db.refresh(inbound_message)

    if conversation.status != "bot_active":
        # A human has taken over (or the thread is closed). The inbound message
        # is already stored above so the operator sees it; the bot just doesn't
        # reply. Logged so the skip is visible.
        logger.info(
            "Inbound message stored but AI reply skipped: conversation not bot_active",
            extra={"conversation_id": str(conversation.id), "status": conversation.status},
        )
        log_action(
            db,
            "ai_continuation_skipped",
            campaign_id=campaign_id,
            instagram_account_id=account.id,
            lead_id=lead.id,
            details={
                "reason": "conversation_not_bot_active",
                "conversation_id": str(conversation.id),
                "conversation_status": conversation.status,
            },
        )
        return

    log_action(
        db,
        "ai_continuation_dispatched",
        campaign_id=campaign_id,
        instagram_account_id=account.id,
        lead_id=lead.id,
        details={
            "conversation_id": str(conversation.id),
            "inbound_message_id": str(inbound_message.id),
            "lead_source": lead.lead_source,
        },
    )
    process_ai_conversation_turn.delay(str(conversation.id), str(inbound_message.id))


def _dispatch_whatsapp_ai_turn(
    db: Session,
    *,
    account: WhatsappAccount,
    lead: Lead,
    inbound_text: str,
) -> None:
    """WhatsApp equivalent of _dispatch_ai_turn.

    A separate function rather than an extension of _dispatch_ai_turn: every
    WhatsApp conversation is cold-DM-shaped (no campaign_id), account
    attribution goes through whatsapp_account_id (not instagram_account_id,
    which is FK'd to instagram_accounts), and the turn dispatches to
    process_whatsapp_ai_conversation_turn, not the Instagram-only
    process_ai_conversation_turn. Mirrors _dispatch_ai_turn's shape/logging
    conventions so the two paths stay easy to compare.
    """
    conversation = conversation_service.get_or_create_conversation(
        db,
        workspace_id=account.workspace_id,
        lead_id=lead.id,
        campaign_id=None,
        platform="whatsapp",
        whatsapp_account_id=account.id,
    )

    inbound_message = Message(
        campaign_id=None,
        lead_id=lead.id,
        conversation_id=conversation.id,
        direction="inbound",
        content=inbound_text,
        rendered_body=inbound_text,
        message_type="ai_conversation",
        status="received",
    )
    db.add(inbound_message)
    conversation_service.touch_conversation(db, conversation)
    db.commit()
    db.refresh(inbound_message)

    if conversation.status != "bot_active":
        logger.info(
            "Inbound WhatsApp message stored but AI reply skipped: conversation not bot_active",
            extra={"conversation_id": str(conversation.id), "status": conversation.status},
        )
        log_action(
            db,
            "ai_continuation_skipped",
            whatsapp_account_id=account.id,
            lead_id=lead.id,
            details={
                "reason": "conversation_not_bot_active",
                "conversation_id": str(conversation.id),
                "conversation_status": conversation.status,
            },
        )
        return

    log_action(
        db,
        "ai_continuation_dispatched",
        whatsapp_account_id=account.id,
        lead_id=lead.id,
        details={
            "conversation_id": str(conversation.id),
            "inbound_message_id": str(inbound_message.id),
            "lead_source": lead.lead_source,
        },
    )
    process_whatsapp_ai_conversation_turn.delay(str(conversation.id), str(inbound_message.id))


def _process_whatsapp_message_events(db: Session, message_events) -> None:
    """Persist WhatsApp identity/consent before applying bot gates."""
    for event in message_events:
        result = process_inbound_whatsapp_event(db, event)
        if result is None:
            continue

        account = result.account
        lead = result.lead
        masked_wa_id = mask_wa_id(event.sender_wa_id)

        # Consent commands are state-changing control messages, not AI prompts.
        if result.consent_action is not None:
            logger.info(
                "Inbound WhatsApp consent command handled",
                extra={
                    "whatsapp_account_id": str(account.id),
                    "sender_wa_id": masked_wa_id,
                    "consent_action": result.consent_action,
                },
            )
            continue

        if not event.text:
            logger.info(
                "Inbound WhatsApp non-text message stored without AI dispatch",
                extra={
                    "whatsapp_account_id": str(account.id),
                    "sender_wa_id": masked_wa_id,
                    "message_type": event.message_type,
                },
            )
            continue

        if account.status != "connected":
            logger.info(
                "Inbound WhatsApp message skipped: account is not connected",
                extra={
                    "whatsapp_account_id": str(account.id),
                    "status": account.status,
                    "sender_wa_id": masked_wa_id,
                },
            )
            log_action(
                db,
                "ai_continuation_skipped",
                whatsapp_account_id=account.id,
                lead_id=lead.id,
                details={
                    "reason": "account_not_connected",
                    "status": account.status,
                    "sender_wa_id": masked_wa_id,
                },
            )
            continue

        if not account.ai_enabled:
            logger.info(
                "Inbound WhatsApp message skipped: account-level AI is disabled",
                extra={
                    "whatsapp_account_id": str(account.id),
                    "sender_wa_id": masked_wa_id,
                },
            )
            log_action(
                db,
                "ai_continuation_skipped",
                whatsapp_account_id=account.id,
                lead_id=lead.id,
                details={"reason": "account_ai_disabled", "sender_wa_id": masked_wa_id},
            )
            continue

        _dispatch_whatsapp_ai_turn(
            db, account=account, lead=lead, inbound_text=event.text
        )


def _record_facebook_psid(db: Session, lead_id, facebook_page_id, raw_response: dict) -> None:
    """Persist the PSID Facebook returns on a successful private reply.

    Facebook hands us two different ids for the same person: the Page-feed
    comment webhook's app-scoped `from.id` (already stored in
    lead.ig_user_id), and the page-scoped PSID used by Messenger webhooks and
    by `recipient.id` sends. The private reply's Send API response is the only
    place the second one is disclosed, via `recipient_id`.

    Best-effort and never raises: failing to record the PSID degrades a later
    reply to "looks like a cold DM", which is bad, but raising here would
    instead undo an already-delivered message's success bookkeeping.
    """
    psid = (raw_response or {}).get("recipient_id")
    if not psid or not isinstance(psid, str):
        logger.warning(
            "Facebook private reply succeeded but returned no recipient_id; "
            "this lead cannot be matched to their own reply later",
            extra={"lead_id": str(lead_id)},
        )
        return

    try:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead is None or lead.facebook_psid == psid:
            return

        # Another lead on this Page already claims this PSID -- almost always
        # a cold-DM lead created for the same human before they ever commented.
        # Leave both rows alone rather than pointing two leads at one identity;
        # log it so the duplicate is diagnosable from logs alone.
        clash = (
            db.query(Lead)
            .filter(
                Lead.facebook_page_id == facebook_page_id,
                Lead.facebook_psid == psid,
                Lead.id != lead_id,
            )
            .first()
        )
        if clash is not None:
            logger.warning(
                "Facebook PSID already held by another lead on this Page; "
                "leaving both rows as-is (same person, two lead records)",
                extra={"lead_id": str(lead_id), "existing_lead_id": str(clash.id)},
            )
            return

        lead.facebook_psid = psid
        db.commit()
        logger.info(
            "Recorded Facebook PSID for lead", extra={"lead_id": str(lead_id)}
        )
    except Exception:
        logger.exception("Failed to record Facebook PSID", extra={"lead_id": str(lead_id)})
        db.rollback()


def _dispatch_facebook_ai_turn(
    db: Session,
    *,
    page: FacebookPage,
    lead: Lead,
    campaign: FacebookCampaign | None,
    inbound_text: str,
) -> None:
    """Facebook equivalent of _dispatch_ai_turn — a separate function per the
    established Phase 2 precedent (not an extension of _dispatch_ai_turn or
    _dispatch_whatsapp_ai_turn), mirroring _dispatch_ai_turn's campaign-aware
    shape rather than WhatsApp's always-cold-DM one, since Facebook Pages
    have a real campaign concept.
    """
    facebook_campaign_id = campaign.id if campaign is not None else None

    conversation = conversation_service.get_or_create_conversation(
        db,
        workspace_id=page.workspace_id,
        lead_id=lead.id,
        campaign_id=None,
        platform="facebook",
        facebook_page_id=page.id,
        facebook_campaign_id=facebook_campaign_id,
    )

    inbound_message = Message(
        campaign_id=None,
        comment_id=None,
        facebook_campaign_id=facebook_campaign_id,
        lead_id=lead.id,
        conversation_id=conversation.id,
        direction="inbound",
        content=inbound_text,
        rendered_body=inbound_text,
        message_type="ai_conversation",
        status="received",
    )
    db.add(inbound_message)
    conversation_service.touch_conversation(db, conversation)
    db.commit()
    db.refresh(inbound_message)

    if conversation.status != "bot_active":
        logger.info(
            "Inbound Facebook message stored but AI reply skipped: conversation not bot_active",
            extra={"conversation_id": str(conversation.id), "status": conversation.status},
        )
        log_action(
            db,
            "ai_continuation_skipped",
            facebook_page_id=page.id,
            lead_id=lead.id,
            details={
                "reason": "conversation_not_bot_active",
                "conversation_id": str(conversation.id),
                "conversation_status": conversation.status,
            },
        )
        return

    log_action(
        db,
        "ai_continuation_dispatched",
        facebook_page_id=page.id,
        lead_id=lead.id,
        details={
            "conversation_id": str(conversation.id),
            "inbound_message_id": str(inbound_message.id),
            "lead_source": lead.lead_source,
        },
    )
    process_facebook_ai_conversation_turn.delay(str(conversation.id), str(inbound_message.id))


def _process_facebook_message_events(db: Session, message_events) -> None:
    """Facebook equivalent of the Instagram `for msg_evt in message_events:`
    block — Facebook has the same campaign-vs-cold_dm branch Instagram does
    (unlike WhatsApp, which is always cold-DM-shaped), so this mirrors the IG
    loop's shape rather than _process_whatsapp_message_events' simpler one.
    """
    for evt in message_events:
        dedup_suffix = evt.mid or str(evt.timestamp or "")
        event_key = (
            f"facebook_message:{evt.sender_id}:{dedup_suffix}"
            if dedup_suffix
            else f"facebook_message:{evt.sender_id}:{evt.text[:50]}"
        )
        is_new = check_and_mark_processed(
            db,
            event_key=event_key,
            event_type="facebook_message",
            metadata={"sender_id": evt.sender_id, "text": evt.text[:200]},
        )
        if not is_new:
            logger.debug(
                "Inbound Facebook message skipped: duplicate webhook delivery (already processed)",
                extra={"event_key": event_key, "sender_id": evt.sender_id},
            )
            continue

        page = db.query(FacebookPage).filter(FacebookPage.page_id == evt.facebook_page_id).first()
        if not page:
            logger.warning(
                "Inbound Facebook message skipped: page not found",
                extra={"page_id": evt.facebook_page_id},
            )
            continue

        if page.status != "connected":
            # Same reasoning as the WhatsApp gate above: disconnect is a soft
            # status flip, so it only stops the bot if dispatch honours it.
            logger.info(
                "Inbound Facebook message skipped: page is not connected",
                extra={
                    "facebook_page_id": str(page.id),
                    "status": page.status,
                    "sender_id": evt.sender_id,
                },
            )
            log_action(
                db,
                "ai_continuation_skipped",
                facebook_page_id=page.id,
                details={
                    "reason": "account_not_connected",
                    "status": page.status,
                    "sender_id": evt.sender_id,
                },
            )
            continue

        if not page.ai_enabled:
            logger.info(
                "Inbound Facebook message skipped: account-level AI is disabled",
                extra={"facebook_page_id": str(page.id), "sender_id": evt.sender_id},
            )
            log_action(
                db,
                "ai_continuation_skipped",
                facebook_page_id=page.id,
                details={"reason": "account_ai_disabled", "sender_id": evt.sender_id},
            )
            continue

        # evt.sender_id is a PSID (page-scoped). A campaign lead was created
        # from a *comment*, whose from.id is an ASID (app-scoped) stored in
        # ig_user_id -- a different namespace, so matching on ig_user_id alone
        # would never find it. Lead.facebook_psid holds the messaging identity,
        # populated from the private reply's Send API response. The ig_user_id
        # arm still matches cold-DM leads (created from a Messenger event, so
        # their ig_user_id already is the PSID), including rows created before
        # facebook_psid existed.
        def _find_fb_lead():
            return (
                db.query(Lead)
                .filter(
                    Lead.workspace_id == page.workspace_id,
                    Lead.facebook_page_id == page.id,
                    or_(Lead.facebook_psid == evt.sender_id, Lead.ig_user_id == evt.sender_id),
                )
                # A facebook_psid match is the authoritative one; order it
                # first so a campaign lead wins over a legacy row that only
                # matches on ig_user_id.
                .order_by(Lead.facebook_psid.is_(None))
                .first()
            )

        lead = _find_fb_lead()

        if lead is not None and lead.facebook_psid is None:
            # Matched on ig_user_id: a cold-DM (or legacy) lead whose
            # ig_user_id already is the PSID. Backfill so later lookups and
            # sends go through the explicit messaging-identity column.
            lead.facebook_psid = evt.sender_id
            db.commit()

        if lead is None:
            # No prior campaign interaction for this sender — cold-DM entry
            # point, same philosophy as Instagram's, gated on ai_cold_dm_enabled.
            if not page.ai_cold_dm_enabled:
                logger.info(
                    "Inbound Facebook message skipped: no lead and cold-DM AI is disabled",
                    extra={"sender_id": evt.sender_id, "facebook_page_id": str(page.id)},
                )
                log_action(
                    db,
                    "ai_continuation_skipped",
                    facebook_page_id=page.id,
                    details={"reason": "no_lead_and_cold_dm_disabled", "sender_id": evt.sender_id},
                )
                continue

            lead = Lead(
                id=uuid4(),
                workspace_id=page.workspace_id,
                platform="facebook",
                facebook_page_id=page.id,
                instagram_account_id=None,
                # Originating event is a Messenger event, so sender_id
                # is already the PSID: both columns hold it here.
                ig_user_id=evt.sender_id,
                facebook_psid=evt.sender_id,
                ig_username=None,
                last_seen_at=datetime.now(timezone.utc),
                lead_source="cold_dm",
                status="new",
            )
            created = _create_lead_or_reuse_concurrent(db, lead, _find_fb_lead)
            if created is None:
                continue
            # Only log a creation we actually performed; on a lost race the
            # winner already logged it.
            if created is lead:
                log_action(
                    db,
                    "cold_dm_lead_created",
                    facebook_page_id=page.id,
                    lead_id=lead.id,
                    details={"sender_id": evt.sender_id},
                )
            lead = created

        if lead.lead_source == "campaign":
            # A campaign-triggered lead has no recorded source_campaign_id
            # (Lead.source_campaign_id is FK'd to Instagram's campaigns) —
            # the originating facebook_campaigns row instead lives on the
            # Message rows already created for this lead. Look up the most
            # recent one to continue that campaign's conversation.
            recent_message = (
                db.query(Message)
                .filter(Message.lead_id == lead.id, Message.facebook_campaign_id.isnot(None))
                .order_by(Message.created_at.desc())
                .first()
            )
            if not recent_message or not recent_message.facebook_campaign_id:
                logger.info(
                    "Inbound Facebook message skipped: no known originating campaign for sender",
                    extra={"sender_id": evt.sender_id, "facebook_page_id": str(page.id), "lead_id": str(lead.id)},
                )
                log_action(
                    db,
                    "ai_continuation_skipped",
                    facebook_page_id=page.id,
                    lead_id=lead.id,
                    details={"reason": "lead_has_no_source_campaign", "sender_id": evt.sender_id},
                )
                continue

            campaign = (
                db.query(FacebookCampaign)
                .filter(FacebookCampaign.id == recent_message.facebook_campaign_id)
                .first()
            )
            if not campaign or not campaign.ai_enabled:
                reason = "campaign_not_found" if not campaign else "campaign_ai_disabled"
                logger.info(
                    "Inbound Facebook message skipped: campaign-level AI continuation is not enabled",
                    extra={"reason": reason, "sender_id": evt.sender_id, "facebook_page_id": str(page.id)},
                )
                log_action(
                    db,
                    "ai_continuation_skipped",
                    facebook_page_id=page.id,
                    lead_id=lead.id,
                    details={"reason": reason, "sender_id": evt.sender_id},
                )
                continue

            _dispatch_facebook_ai_turn(db, page=page, lead=lead, campaign=campaign, inbound_text=evt.text)
            continue

        if lead.lead_source == "cold_dm":
            if not page.ai_cold_dm_enabled:
                logger.info(
                    "Inbound Facebook message skipped: cold-DM AI disabled for account",
                    extra={"sender_id": evt.sender_id, "facebook_page_id": str(page.id)},
                )
                log_action(
                    db,
                    "ai_continuation_skipped",
                    facebook_page_id=page.id,
                    lead_id=lead.id,
                    details={"reason": "cold_dm_ai_disabled", "sender_id": evt.sender_id},
                )
                continue

            _dispatch_facebook_ai_turn(db, page=page, lead=lead, campaign=None, inbound_text=evt.text)
            continue

        logger.warning(
            "Inbound Facebook message skipped: unrecognized lead_source",
            extra={"lead_id": str(lead.id), "lead_source": lead.lead_source},
        )


def _process_facebook_comment_events(db: Session, comment_events) -> None:
    """Facebook equivalent of the Instagram comment-handling loop inside
    process_webhook_event (dedup -> page lookup -> upsert comment -> match
    campaigns -> cooldown -> render -> queue -> send). Written fresh rather
    than extending the IG loop, using facebook_campaign_matcher /
    facebook_comment_service / facebook_lead_service / facebook_message_service
    / facebook_cooldown_service in place of the Instagram-only equivalents.
    No follow_prompt branch — see this phase's research spike.
    """
    for parsed in comment_events:
        event_key = build_event_key(
            comment_id=parsed.comment_id,
            entry_id=parsed.facebook_page_id,
            media_id=parsed.post_id,
            commenter_ig_id=parsed.commenter_id,
            comment_text=parsed.comment_text,
            # Without this, Facebook comments were deduped under Instagram's
            # "ig_comment:" namespace.
            platform="facebook",
        )
        is_new = check_and_mark_processed(
            db,
            event_key=event_key,
            event_type="facebook_comment",
            metadata={"comment_id": parsed.comment_id, "post_id": parsed.post_id},
        )
        if not is_new:
            logger.debug(
                "Duplicate Facebook webhook change skipped (processed_webhook_events)",
                extra={"comment_id": parsed.comment_id, "event_key": event_key},
            )
            continue

        page = db.query(FacebookPage).filter(FacebookPage.page_id == parsed.facebook_page_id).first()
        if not page:
            logger.warning(
                "Facebook Page not found for webhook", extra={"page_id": parsed.facebook_page_id}
            )
            continue

        if page.status != "connected":
            # A disconnected Page must not keep triggering campaign sends
            # either, not just AI continuation.
            logger.info(
                "Facebook comment skipped: page is not connected",
                extra={"facebook_page_id": str(page.id), "status": page.status},
            )
            log_action(
                db,
                "campaign_skipped",
                facebook_page_id=page.id,
                details={
                    "reason": "account_not_connected",
                    "status": page.status,
                    "comment_id": parsed.comment_id,
                },
            )
            continue

        comment, is_dup = upsert_facebook_comment(
            db,
            page.id,
            parsed.comment_id,
            parsed.post_id,
            parsed.commenter_id,
            parsed.commenter_name,
            parsed.comment_text,
        )
        if is_dup:
            log_action(
                db, "webhook_duplicate_comment", facebook_page_id=page.id, details={"comment_id": parsed.comment_id}
            )
            continue

        matches = find_matching_facebook_campaigns(db, page.id, parsed.post_id, parsed.comment_text)
        if not matches:
            log_action(
                db,
                "campaign_no_match",
                facebook_page_id=page.id,
                details={"comment_id": parsed.comment_id, "post_id": parsed.post_id},
            )
            continue

        for match in matches:
            campaign = db.query(FacebookCampaign).filter(FacebookCampaign.id == match.campaign_id).first()
            if not campaign:
                continue

            log_action(
                db,
                "campaign_matched",
                facebook_page_id=page.id,
                details={"comment_id": parsed.comment_id, "matched_keyword": match.matched_keyword},
            )

            existing_msg = (
                db.query(Message)
                .filter(
                    Message.facebook_campaign_id == campaign.id,
                    Message.facebook_comment_id == comment.id,
                    Message.message_type == "final_delivery",
                )
                .first()
            )
            if existing_msg:
                logger.info(
                    "Duplicate Facebook message blocked",
                    extra={"campaign_id": str(campaign.id), "comment_id": str(comment.id)},
                )
                continue

            if facebook_cooldown_service.is_in_cooldown(db, campaign.id, parsed.commenter_id):
                log_action(
                    db,
                    "cooldown_skip",
                    facebook_page_id=page.id,
                    details={"comment_id": parsed.comment_id, "user_id": parsed.commenter_id},
                )
                continue

            try:
                rendered = render_template(
                    campaign.message_template,
                    {
                        "username": parsed.commenter_name or "there",
                        "campaign_name": campaign.name,
                        "keyword": match.matched_keyword,
                        "link": campaign.link_url or "",
                    },
                )
            except Exception as exc:
                logger.exception("Facebook template render failed", extra={"campaign_id": str(campaign.id)})
                log_action(db, "message_render_failed", facebook_page_id=page.id, details={"error": str(exc)})
                continue

            lead = upsert_lead_from_facebook_comment(
                db,
                campaign.workspace_id,
                page.id,
                campaign.id,
                comment.id,
                parsed.commenter_id,
                parsed.commenter_name,
                source_post_id=parsed.post_id,
            )

            message = create_queued_facebook_message(
                db,
                facebook_campaign_id=campaign.id,
                lead_id=lead.id,
                facebook_comment_id=comment.id,
                rendered_body=rendered,
                message_type="final_delivery",
                source_media_id=parsed.post_id,
            )

            campaign.total_triggers += 1
            db.commit()

            log_action(
                db,
                "message_queued",
                facebook_page_id=page.id,
                lead_id=lead.id,
                details={"message_id": str(message.id), "matched_keyword": match.matched_keyword},
            )

            if campaign.cooldown_hours > 0:
                facebook_cooldown_service.record_cooldown(
                    db, campaign.id, parsed.commenter_id, campaign.cooldown_hours
                )

            send_facebook_private_reply.delay(str(message.id))


@celery_app.task
def process_webhook_event(webhook_event_id: str):
    db = _get_db()
    try:
        event = db.query(WebhookEvent).filter(WebhookEvent.id == webhook_event_id).first()
        if not event:
            logger.warning("Webhook event not found", extra={"event_id": webhook_event_id})
            return

        log_action(db, "webhook_received", details={"event_id": webhook_event_id})

        webhook_object = (event.payload or {}).get("object")

        if webhook_object == "whatsapp_business_account":
            whatsapp_message_events = parse_whatsapp_message_events(event.payload or {})
            whatsapp_status_events = parse_whatsapp_status_events(event.payload or {})
            whatsapp_template_events = parse_whatsapp_template_status_events(event.payload or {})
            whatsapp_quality_events = parse_whatsapp_phone_quality_events(event.payload or {})
            whatsapp_raw_only_events = parse_whatsapp_raw_only_events(event.payload or {})
            if not any(
                (
                    whatsapp_message_events,
                    whatsapp_status_events,
                    whatsapp_template_events,
                    whatsapp_quality_events,
                    whatsapp_raw_only_events,
                )
            ):
                event.processing_status = "skipped"
                db.commit()
                log_action(
                    db,
                    "webhook_skipped",
                    details={"reason": "no_supported_whatsapp_events", "event_id": webhook_event_id},
                )
                return
            _process_whatsapp_message_events(db, whatsapp_message_events)
            process_whatsapp_status_events(db, whatsapp_status_events)
            process_whatsapp_template_status_events(db, whatsapp_template_events)
            process_whatsapp_phone_quality_events(db, whatsapp_quality_events)
            if whatsapp_raw_only_events:
                logger.info(
                    "Stored WhatsApp webhook event without state mutation",
                    extra={
                        "event_id": webhook_event_id,
                        "fields": sorted({item.field for item in whatsapp_raw_only_events}),
                    },
                )
            event.processing_status = "processed"
            db.commit()
            log_action(
                db,
                "webhook_processed",
                details={"event_id": webhook_event_id, "platform": "whatsapp"},
            )
            return

        if webhook_object == "page":
            facebook_comment_events = parse_facebook_comment_events(event.payload or {})
            facebook_message_events = parse_facebook_message_events(event.payload or {})
            facebook_postback_events = parse_facebook_postback_events(event.payload or {})
            if not facebook_comment_events and not facebook_message_events and not facebook_postback_events:
                event.processing_status = "skipped"
                db.commit()
                log_action(
                    db,
                    "webhook_skipped",
                    details={"reason": "no_facebook_comment_message_or_postback_events", "event_id": webhook_event_id},
                )
                return
            _process_facebook_comment_events(db, facebook_comment_events)
            _process_facebook_message_events(db, facebook_message_events)
            if facebook_postback_events:
                # No Facebook feature sends buttons/quick-replies yet (unlike
                # Instagram's FOLLOW_CHECK follow-gate), so there is nothing
                # to action on a tap today -- but record it distinctly rather
                # than letting it vanish under the generic "no events" skip
                # reason above, so a future feature (or an unexpected
                # Get Started tap) stays visible in the logs.
                logger.info(
                    "Received Facebook postback event(s) with no handler configured",
                    extra={"event_id": webhook_event_id, "count": len(facebook_postback_events)},
                )
                log_action(
                    db,
                    "facebook_postback_received_no_handler",
                    details={
                        "event_id": webhook_event_id,
                        "count": len(facebook_postback_events),
                        "payloads": [pb.payload for pb in facebook_postback_events],
                    },
                )
            event.processing_status = "processed"
            db.commit()
            log_action(
                db,
                "webhook_processed",
                details={"event_id": webhook_event_id, "platform": "facebook"},
            )
            return

        if webhook_object != "instagram":
            logger.info(
                "Unhandled or missing webhook object type",
                extra={"object": webhook_object, "event_id": webhook_event_id},
            )
            event.processing_status = "skipped"
            db.commit()
            log_action(
                db,
                "webhook_skipped",
                details={
                    "reason": "unhandled_webhook_object",
                    "object": webhook_object,
                    "event_id": webhook_event_id,
                },
            )
            return

        comment_events = parse_instagram_comment_events(event.payload or {})
        postback_events = parse_instagram_postback_events(event.payload or {})
        message_events = parse_instagram_message_events(event.payload or {})
        if not comment_events and not postback_events and not message_events:
            event.processing_status = "skipped"
            db.commit()
            log_action(db, "webhook_skipped", details={"reason": "no_comment_postback_or_message_events", "event_id": webhook_event_id})
            return

        for parsed in comment_events:
            # Per-change deduplication: skip if this comment was already processed.
            event_key = build_event_key(
                comment_id=parsed.comment_id,
                entry_id=parsed.instagram_account_ig_user_id,
                media_id=parsed.media_id,
                commenter_ig_id=parsed.commenter_ig_id,
                comment_text=parsed.comment_text,
            )
            is_new = check_and_mark_processed(
                db,
                event_key=event_key,
                event_type="ig_comment",
                metadata={"comment_id": parsed.comment_id, "media_id": parsed.media_id},
            )
            if not is_new:
                logger.debug(
                    "Duplicate webhook change skipped (processed_webhook_events)",
                    extra={"comment_id": parsed.comment_id, "event_key": event_key},
                )
                continue

            # Find instagram account by ig_user_id
            account = (
                db.query(InstagramAccount)
                .filter(InstagramAccount.ig_user_id == parsed.instagram_account_ig_user_id)
                .first()
            )
            if not account:
                logger.warning(
                    "Instagram account not found for webhook",
                    extra={"ig_user_id": parsed.instagram_account_ig_user_id},
                )
                continue

            # Upsert comment
            comment, is_dup = upsert_comment(
                db,
                account.id,
                parsed.comment_id,
                parsed.commenter_ig_id,
                parsed.username,
                parsed.comment_text,
            )
            if is_dup:
                log_action(db, "webhook_duplicate_comment", instagram_account_id=account.id, details={"comment_id": parsed.comment_id})
                continue

            # Find matching campaigns
            matches = find_matching_campaigns(
                db,
                account.id,
                parsed.media_id,
                parsed.comment_text,
            )

            if not matches:
                inactive_query = db.query(Campaign).filter(
                    Campaign.instagram_account_id == account.id,
                    Campaign.status != "active",
                )

                inactive_match = None
                for inactive_campaign in inactive_query.all():
                    if inactive_campaign.target_scope == "specific_media":
                        if not inactive_campaign.target_media_id or inactive_campaign.target_media_id != parsed.media_id:
                            continue
                    matched_keyword = find_matching_keyword(
                        parsed.comment_text,
                        [ck.normalized_keyword for ck in inactive_campaign.keywords],
                        inactive_campaign.match_type,
                    )
                    if matched_keyword:
                        inactive_match = (inactive_campaign, matched_keyword)
                        break

                if inactive_match:
                    inactive_campaign, matched_keyword = inactive_match
                    log_action(
                        db,
                        "campaign_skipped_inactive",
                        campaign_id=inactive_campaign.id,
                        instagram_account_id=account.id,
                        details={
                            "comment_id": parsed.comment_id,
                            "status": inactive_campaign.status,
                            "matched_keyword": matched_keyword,
                        },
                    )
                else:
                    waiting_specific = (
                        db.query(Campaign)
                        .filter(
                            Campaign.instagram_account_id == account.id,
                            Campaign.status == "active",
                            Campaign.target_scope == "specific_media",
                            Campaign.target_media_id.is_(None),
                        )
                        .count()
                    )
                    log_action(
                        db,
                        "campaign_no_match",
                        instagram_account_id=account.id,
                        details={
                            "comment_id": parsed.comment_id,
                            "media_id": parsed.media_id,
                            "specific_campaigns_waiting_for_media_id": waiting_specific,
                        },
                    )
                continue

            for match in matches:
                campaign = db.query(Campaign).filter(Campaign.id == match.campaign_id).first()
                if not campaign:
                    continue

                log_action(
                    db,
                    "campaign_matched",
                    campaign_id=campaign.id,
                    instagram_account_id=account.id,
                    details={"comment_id": parsed.comment_id, "matched_keyword": match.matched_keyword},
                )

                # Idempotency: check if message already exists for this campaign+comment
                existing_msg = (
                    db.query(Message)
                    .filter(
                        Message.campaign_id == campaign.id,
                        Message.comment_id == comment.id,
                        Message.message_type == "final_delivery",
                    )
                    .first()
                )
                if existing_msg:
                    logger.info(
                        "Duplicate message blocked",
                        extra={"campaign_id": str(campaign.id), "comment_id": str(comment.id)},
                    )
                    continue

                # Check cooldown
                if is_in_cooldown(db, campaign.id, parsed.commenter_ig_id):
                    log_action(
                        db,
                        "cooldown_skip",
                        campaign_id=campaign.id,
                        instagram_account_id=account.id,
                        details={"comment_id": parsed.comment_id, "user_id": parsed.commenter_ig_id},
                    )
                    continue

                # Render message
                try:
                    rendered = render_campaign_message(
                        campaign.message_template,
                        username=parsed.username or "there",
                        campaign_name=campaign.name,
                        keyword=match.matched_keyword,
                        link=campaign.link_url,
                        media_url=campaign.media_url,
                    )
                except Exception as exc:
                    logger.exception("Template render failed", extra={"campaign_id": str(campaign.id)})
                    log_action(db, "message_render_failed", campaign_id=campaign.id, details={"error": str(exc)})
                    continue

                # Upsert lead
                lead = upsert_lead_from_comment(
                    db,
                    campaign.workspace_id,
                    account.id,
                    campaign.id,
                    comment.id,
                    parsed.commenter_ig_id,
                    parsed.username,
                    source_media_id=parsed.media_id,
                    source_media_type=campaign.target_media_type,
                    source_media_label=campaign.target_media_label,
                )

                if campaign.delivery_mode == "follow_prompt":
                    message = create_queued_message(
                        db,
                        campaign_id=campaign.id,
                        lead_id=lead.id,
                        comment_id=comment.id,
                        rendered_body=campaign.follow_prompt_title or "",
                        message_type="follow_prompt",
                        source_media_id=parsed.media_id,
                        source_media_type=campaign.target_media_type,
                        source_media_label=campaign.target_media_label,
                    )
                    message.content = campaign.follow_prompt_description
                    db.commit()
                else:
                    message = create_queued_message(
                        db,
                        campaign_id=campaign.id,
                        lead_id=lead.id,
                        comment_id=comment.id,
                        rendered_body=rendered,
                        message_type="final_delivery",
                        source_media_id=parsed.media_id,
                        source_media_type=campaign.target_media_type,
                        source_media_label=campaign.target_media_label,
                    )

                # Increment campaign trigger counter
                campaign.total_triggers += 1
                db.commit()

                # Log
                log_action(
                    db,
                    "follow_prompt_queued" if campaign.delivery_mode == "follow_prompt" else "message_queued",
                    campaign_id=campaign.id,
                    lead_id=lead.id,
                    instagram_account_id=account.id,
                    details={
                        "message_id": str(message.id),
                        **_message_flow_details(
                            campaign.delivery_mode,
                            "follow_prompt" if campaign.delivery_mode == "follow_prompt" else "final_delivery",
                            parsed.comment_id,
                            match.matched_keyword,
                            str(lead.id),
                            campaign.follow_prompt_profile_url,
                        ),
                    },
                )

                # Record cooldown at queue time to prevent duplicate queueing
                if campaign.cooldown_hours > 0:
                    record_cooldown(db, campaign.id, parsed.commenter_ig_id, campaign.cooldown_hours)

                # Enqueue send task
                if campaign.delivery_mode == "follow_prompt":
                    send_follow_prompt_card.delay(str(message.id))
                else:
                    send_private_reply.delay(str(message.id))

        for pb in postback_events:
            if not pb.payload.startswith("FOLLOW_CHECK:"):
                # Not a payload shape this feature owns — ignore rather than
                # error, so other/future postback payloads aren't disrupted.
                continue

            follow_prompt_message_id = pb.payload.split("FOLLOW_CHECK:", 1)[1].strip()
            if not follow_prompt_message_id:
                continue

            # Dedup on the message id (Meta may re-deliver the same postback
            # notification). Falls back to mid if present, else timestamp,
            # so repeated taps of the *same* button by the user each still
            # trigger a fresh check (only true duplicate deliveries are
            # collapsed).
            dedup_suffix = pb.mid or str(pb.timestamp or "")
            pb_event_key = f"ig_postback:{follow_prompt_message_id}:{dedup_suffix}" if dedup_suffix else f"ig_postback:{follow_prompt_message_id}:{pb.sender_ig_id}"
            is_new_pb = check_and_mark_processed(
                db,
                event_key=pb_event_key,
                event_type="ig_postback",
                metadata={"payload": pb.payload, "sender_ig_id": pb.sender_ig_id},
            )
            if not is_new_pb:
                logger.debug("Duplicate postback event skipped", extra={"event_key": pb_event_key})
                continue

            log_action(
                db,
                "follow_check_postback_received",
                details={"message_id": follow_prompt_message_id, "sender_ig_id": pb.sender_ig_id},
            )
            check_follow_and_deliver.delay(follow_prompt_message_id, pb.sender_ig_id)

        for msg_evt in message_events:
            # Dedup on mid if present, else fall back to timestamp+sender so
            # Meta re-deliveries of the same DM don't trigger duplicate AI turns.
            dedup_suffix = msg_evt.mid or str(msg_evt.timestamp or "")
            msg_event_key = (
                f"ig_message:{msg_evt.sender_ig_id}:{dedup_suffix}"
                if dedup_suffix
                else f"ig_message:{msg_evt.sender_ig_id}:{msg_evt.text[:50]}"
            )
            is_new_msg = check_and_mark_processed(
                db,
                event_key=msg_event_key,
                event_type="ig_message",
                metadata={"sender_ig_id": msg_evt.sender_ig_id, "text": msg_evt.text[:200]},
            )
            if not is_new_msg:
                logger.info(
                    "Inbound message skipped: duplicate webhook delivery (already processed)",
                    extra={"event_key": msg_event_key, "sender_ig_id": msg_evt.sender_ig_id},
                )
                continue

            account = (
                db.query(InstagramAccount)
                .filter(InstagramAccount.ig_user_id == msg_evt.instagram_account_ig_user_id)
                .first()
            )
            if not account:
                logger.warning(
                    "Inbound message skipped: Instagram account not found",
                    extra={"ig_user_id": msg_evt.instagram_account_ig_user_id},
                )
                log_action(
                    db,
                    "ai_continuation_skipped",
                    details={
                        "reason": "account_not_found",
                        "ig_user_id": msg_evt.instagram_account_ig_user_id,
                        "sender_ig_id": msg_evt.sender_ig_id,
                    },
                )
                continue

            if not account.ai_enabled:
                # AI layer is opt-in at the account level. Without it, an
                # inbound DM reply is simply not actioned automatically —
                # this is intentional, not a bug: no campaign context exists
                # to reply from without a human or the AI layer involved.
                # Still logged so the skip is diagnosable from logs alone.
                logger.info(
                    "Inbound message skipped: account-level AI is disabled",
                    extra={
                        "instagram_account_id": str(account.id),
                        "sender_ig_id": msg_evt.sender_ig_id,
                    },
                )
                log_action(
                    db,
                    "ai_continuation_skipped",
                    instagram_account_id=account.id,
                    details={
                        "reason": "account_ai_disabled",
                        "sender_ig_id": msg_evt.sender_ig_id,
                    },
                )
                continue

            def _find_ig_lead():
                return (
                    db.query(Lead)
                    .filter(
                        Lead.workspace_id == account.workspace_id,
                        Lead.instagram_account_id == account.id,
                        Lead.ig_user_id == msg_evt.sender_ig_id,
                    )
                    .first()
                )

            lead = _find_ig_lead()

            if lead is None:
                # No prior campaign interaction for this sender. This is the
                # cold-DM entry point: only create a lead (and let the AI
                # respond) if the account has explicitly opted into answering
                # unsolicited DMs. account.ai_enabled is already known true
                # here (checked above).
                if not account.ai_cold_dm_enabled:
                    logger.info(
                        "Inbound message skipped: no lead and cold-DM AI is disabled",
                        extra={
                            "sender_ig_id": msg_evt.sender_ig_id,
                            "instagram_account_id": str(account.id),
                        },
                    )
                    log_action(
                        db,
                        "ai_continuation_skipped",
                        instagram_account_id=account.id,
                        details={
                            "reason": "no_lead_and_cold_dm_disabled",
                            "sender_ig_id": msg_evt.sender_ig_id,
                        },
                    )
                    continue

                # Best-effort: the DM webhook payload carries no username, so
                # look it up via the Instagram User Profile API. Never let a
                # failed lookup block lead creation — fall back to no username
                # (the dashboard then shows the raw IGSID, same as before).
                cold_dm_username: str | None = None
                try:
                    lookup_token = get_decrypted_token(db, account.id)
                    if lookup_token:
                        client = MetaMessagingClient()
                        try:
                            cold_dm_username = client.get_username(
                                lookup_token, msg_evt.sender_ig_id
                            )
                        finally:
                            client.close()
                except Exception:
                    logger.warning(
                        "Cold-DM username lookup failed; creating lead without username",
                        exc_info=True,
                        extra={"sender_ig_id": msg_evt.sender_ig_id},
                    )

                new_lead = Lead(
                    id=uuid4(),
                    workspace_id=account.workspace_id,
                    instagram_account_id=account.id,
                    ig_user_id=msg_evt.sender_ig_id,
                    ig_username=cold_dm_username,
                    last_seen_at=datetime.now(timezone.utc),
                    source_campaign_id=None,
                    lead_source="cold_dm",
                    status="new",
                )
                created = _create_lead_or_reuse_concurrent(db, new_lead, _find_ig_lead)
                if created is None:
                    continue
                # Only log a creation we actually performed; on a lost race the
                # winner already logged it.
                is_new_lead = created is new_lead
                lead = created

                if is_new_lead:
                    log_action(
                        db,
                        "cold_dm_lead_created",
                        instagram_account_id=account.id,
                        lead_id=lead.id,
                        details={
                            "sender_ig_id": msg_evt.sender_ig_id,
                            "username_resolved": cold_dm_username is not None,
                        },
                    )

            # --- Dispatch, branched by how this lead entered the system ---
            if lead.lead_source == "campaign":
                if not lead.source_campaign_id:
                    # No known originating campaign for this sender — nothing
                    # to continue. Do not guess which campaign applies.
                    reason = "lead_has_no_source_campaign"
                    logger.info(
                        "Inbound message skipped: no known originating campaign for sender",
                        extra={
                            "reason": reason,
                            "sender_ig_id": msg_evt.sender_ig_id,
                            "instagram_account_id": str(account.id),
                            "lead_id": str(lead.id),
                        },
                    )
                    log_action(
                        db,
                        "ai_continuation_skipped",
                        instagram_account_id=account.id,
                        lead_id=lead.id,
                        details={
                            "reason": reason,
                            "sender_ig_id": msg_evt.sender_ig_id,
                        },
                    )
                    continue

                campaign = db.query(Campaign).filter(Campaign.id == lead.source_campaign_id).first()
                if not campaign or not campaign.ai_enabled:
                    # Campaign-level AI continuation is a separate opt-in from the
                    # account-level toggle (Campaign.ai_enabled, default false).
                    # Account AI being on does NOT cascade to its campaigns.
                    reason = "campaign_not_found" if not campaign else "campaign_ai_disabled"
                    logger.info(
                        "Inbound message skipped: campaign-level AI continuation is not enabled",
                        extra={
                            "reason": reason,
                            "sender_ig_id": msg_evt.sender_ig_id,
                            "instagram_account_id": str(account.id),
                            "lead_id": str(lead.id),
                            "campaign_id": str(lead.source_campaign_id),
                        },
                    )
                    log_action(
                        db,
                        "ai_continuation_skipped",
                        campaign_id=campaign.id if campaign else None,
                        instagram_account_id=account.id,
                        lead_id=lead.id,
                        details={
                            "reason": reason,
                            "campaign_id": str(lead.source_campaign_id),
                            "sender_ig_id": msg_evt.sender_ig_id,
                        },
                    )
                    continue

                _dispatch_ai_turn(
                    db,
                    account=account,
                    lead=lead,
                    campaign=campaign,
                    inbound_text=msg_evt.text,
                )
                continue

            if lead.lead_source == "cold_dm":
                if not account.ai_cold_dm_enabled:
                    # The account toggle was switched off after this cold-DM
                    # lead was created. Fail closed, but keep it diagnosable.
                    logger.info(
                        "Inbound message skipped: cold-DM AI disabled for account",
                        extra={
                            "sender_ig_id": msg_evt.sender_ig_id,
                            "instagram_account_id": str(account.id),
                            "lead_id": str(lead.id),
                        },
                    )
                    log_action(
                        db,
                        "ai_continuation_skipped",
                        instagram_account_id=account.id,
                        lead_id=lead.id,
                        details={
                            "reason": "cold_dm_ai_disabled",
                            "sender_ig_id": msg_evt.sender_ig_id,
                        },
                    )
                    continue

                _dispatch_ai_turn(
                    db,
                    account=account,
                    lead=lead,
                    campaign=None,
                    inbound_text=msg_evt.text,
                )
                continue

            logger.warning(
                "Inbound message skipped: unrecognized lead_source",
                extra={"lead_id": str(lead.id), "lead_source": lead.lead_source},
            )

        event.processing_status = "processed"
        db.commit()
        log_action(
            db,
            "webhook_processed",
            details={"event_id": webhook_event_id, "platform": "instagram"},
        )
    except Exception:
        logger.exception("process_webhook_event failed", extra={"event_id": webhook_event_id})
        try:
            event.processing_status = "failed"
            db.commit()
        except Exception:
            # An uncaught IntegrityError earlier in this task leaves the
            # session in an aborted-transaction state, so the commit above
            # raises again -- silently swallowing that would leave this
            # event stuck in an ambiguous, non-"failed" status with nothing
            # queryable to alert on. Roll back and retry once so the
            # failure is always recorded.
            logger.exception(
                "Failed to persist webhook_event failure status; retrying after rollback",
                extra={"event_id": webhook_event_id},
            )
            try:
                db.rollback()
                event.processing_status = "failed"
                db.commit()
            except Exception:
                logger.exception(
                    "Could not persist webhook_event failure status even after rollback",
                    extra={"event_id": webhook_event_id},
                )
    finally:
        db.close()


def _send_private_reply_impl(
    task,
    message_id: str,
    final_after_prompt: bool = False,
    direct_recipient_id: str | None = None,
):
    """Send a queued message.

    When direct_recipient_id is provided, the message is delivered via
    recipient.id through the open 24-hour messaging window rather than via
    recipient.comment_id. This is required for any send that follows a
    postback tap, because Meta permits only one private reply per comment
    (further attempts fail with error subcode 2534014).
    """
    db = _get_db()
    try:
        message = get_message_for_send(db, message_id)
        if not message:
            logger.warning("Message not found for send", extra={"message_id": message_id})
            return
        if message.status == "sent":
            logger.info("Sent message skipped for idempotency", extra={"message_id": message_id})
            return

        campaign = db.query(Campaign).filter(Campaign.id == message.campaign_id).first()
        if not campaign:
            mark_message_skipped(db, message.id, "Campaign not found")
            return

        if campaign.status != "active":
            mark_message_skipped(db, message.id, f"Campaign status is {campaign.status}")
            log_action(db, "message_skipped", campaign_id=campaign.id, details={"reason": "campaign_not_active"})
            return

        account = db.query(InstagramAccount).filter(InstagramAccount.id == campaign.instagram_account_id).first()
        if not account:
            mark_message_skipped(db, message.id, "Instagram account not found")
            return

        # Get decrypted token
        access_token = get_decrypted_token(db, campaign.instagram_account_id)
        if not access_token:
            mark_message_failed(db, message.id, "no_token", "No valid access token", retryable=False)
            log_action(db, "token_expired", campaign_id=campaign.id, details={"message_id": message_id})
            return

        # Mark sending
        mark_message_sending(db, message.id)

        # Find comment_id string
        comment_id_str, trigger_keyword = _matched_keyword_for_message(db, message)

        # Send via Meta API (sync client — no asyncio needed in Celery workers)
        client = MetaMessagingClient()
        try:
            if direct_recipient_id:
                result = client.send_direct_message(
                    access_token=access_token,
                    ig_user_id=account.ig_user_id,
                    recipient_id=direct_recipient_id,
                    text=message.rendered_body or "",
                )
            else:
                result = client.send_private_reply(
                    access_token=access_token,
                    ig_user_id=account.ig_user_id,
                    comment_id=comment_id_str,
                    text=message.rendered_body or "",
                )
        finally:
            client.close()

        if result.success:
            mark_message_sent(db, message.id, result.provider_message_id)
            campaign.successful_sends += 1
            db.commit()

            if campaign.comment_reply_enabled and campaign.comment_reply_text and comment_id_str:
                # Fully isolated: the DM is already delivered and committed above.
                # No failure here may propagate to the outer handler, which would
                # otherwise mark an already-sent message as failed.
                try:
                    reply_client = MetaMessagingClient()
                    try:
                        reply_result = reply_client.reply_to_comment(
                            access_token=access_token,
                            comment_id=comment_id_str,
                            message=campaign.comment_reply_text,
                        )
                    finally:
                        reply_client.close()

                    if reply_result.success:
                        log_action(
                            db,
                            "comment_reply_sent",
                            campaign_id=campaign.id,
                            lead_id=message.lead_id,
                            details={"message_id": message_id, "comment_id": comment_id_str},
                        )
                    else:
                        logger.warning(
                            "Comment reply failed after successful DM",
                            extra={"comment_id": comment_id_str, "error": reply_result.error_message},
                        )
                        log_action(
                            db,
                            "comment_reply_failed",
                            campaign_id=campaign.id,
                            lead_id=message.lead_id,
                            details={
                                "message_id": message_id,
                                "comment_id": comment_id_str,
                                "error": reply_result.error_message,
                            },
                        )
                except Exception as reply_exc:
                    logger.exception(
                        "Comment reply raised after successful DM",
                        extra={"comment_id": comment_id_str, "message_id": message_id},
                    )
                    try:
                        log_action(
                            db,
                            "comment_reply_failed",
                            campaign_id=campaign.id,
                            lead_id=message.lead_id,
                            details={
                                "message_id": message_id,
                                "comment_id": comment_id_str,
                                "error": f"exception: {reply_exc}",
                            },
                        )
                    except Exception:
                        pass

            action = "final_delivery_sent" if final_after_prompt else "message_sent"
            log_action(
                db,
                action,
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={
                    "message_id": message_id,
                    "provider_message_id": result.provider_message_id,
                    **_message_flow_details(
                        campaign.delivery_mode,
                        message.message_type,
                        comment_id_str,
                        trigger_keyword,
                        str(message.lead_id),
                    ),
                },
            )
            return

        # Handle errors based on classification
        if result.error_code == "expired_private_reply":
            mark_message_expired(db, message.id, result.error_code, result.error_message)
            log_action(
                db,
                "message_expired",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={"message_id": message_id, "error": result.error_message},
            )
            return

        if result.retryable:
            mark_message_failed(db, message.id, result.error_code, result.error_message, retryable=True)
            increment_retry_count(db, message.id)
            campaign.failed_sends += 1
            db.commit()
            log_action(
                db,
                "final_delivery_failed" if final_after_prompt else "message_failed_retryable",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={
                    "message_id": message_id,
                    "error": result.error_message,
                    "retry": task.request.retries,
                    **_message_flow_details(campaign.delivery_mode, message.message_type, comment_id_str, trigger_keyword, str(message.lead_id)),
                },
            )
            raise task.retry(countdown=60 * (2 ** task.request.retries), exc=Exception(result.error_message))

        # Token/permission/policy errors - permanent failure
        if result.error_code in ("token_error", "permission_error", "policy_error"):
            mark_message_failed(db, message.id, result.error_code, result.error_message, retryable=False)
            campaign.failed_sends += 1
            db.commit()
            log_action(
                db,
                "final_delivery_failed" if final_after_prompt else f"message_{result.error_code}",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={
                    "message_id": message_id,
                    "error": result.error_message,
                    **_message_flow_details(campaign.delivery_mode, message.message_type, comment_id_str, trigger_keyword, str(message.lead_id)),
                },
            )
            return

        # Any other unknown error - non-retryable
        mark_message_failed(db, message.id, result.error_code or "unknown", result.error_message, retryable=False)
        campaign.failed_sends += 1
        db.commit()
        log_action(
            db,
            "final_delivery_failed" if final_after_prompt else "message_failed",
            campaign_id=campaign.id,
            lead_id=message.lead_id,
            details={
                "message_id": message_id,
                "error": result.error_message,
                **_message_flow_details(campaign.delivery_mode, message.message_type, comment_id_str, trigger_keyword, str(message.lead_id)),
            },
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if exc_name in ("Retry", "MaxRetriesExceededError"):
            raise
        logger.exception("send_private_reply failed", extra={"message_id": message_id})
        try:
            mark_message_failed(db, message_id, "task_exception", str(exc), retryable=False)
        except Exception:
            pass
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=4)
def send_follow_prompt_card(self, message_id: str):
    db = _get_db()
    try:
        message = get_message_for_send(db, message_id)
        if not message:
            logger.warning("Follow prompt message not found", extra={"message_id": message_id})
            return
        if message.status == "sent":
            logger.info("Sent follow prompt skipped for idempotency", extra={"message_id": message_id})
            return

        if message.message_type != "follow_prompt":
            mark_message_skipped(db, message.id, "Message is not a follow prompt")
            return

        campaign = db.query(Campaign).filter(Campaign.id == message.campaign_id).first()
        if not campaign:
            mark_message_skipped(db, message.id, "Campaign not found")
            return

        if campaign.status != "active":
            mark_message_skipped(db, message.id, f"Campaign status is {campaign.status}")
            log_action(db, "message_skipped", campaign_id=campaign.id, details={"reason": "campaign_not_active"})
            return

        account = db.query(InstagramAccount).filter(InstagramAccount.id == campaign.instagram_account_id).first()
        if not account:
            mark_message_skipped(db, message.id, "Instagram account not found")
            return

        access_token = get_decrypted_token(db, campaign.instagram_account_id)
        if not access_token:
            mark_message_failed(db, message.id, "no_token", "No valid access token", retryable=False)
            log_action(db, "token_expired", campaign_id=campaign.id, details={"message_id": message_id})
            return

        comment_id_str, trigger_keyword = _matched_keyword_for_message(db, message)
        mark_message_sending(db, message.id)

        # Send via Meta API (sync client — no asyncio needed in Celery workers)
        client = MetaMessagingClient()
        try:
            result = client.send_follow_prompt_card(
                access_token=access_token,
                ig_user_id=account.ig_user_id,
                comment_id=comment_id_str or "",
                title=campaign.follow_prompt_title or "",
                description=campaign.follow_prompt_description or "",
                profile_url=campaign.follow_prompt_profile_url or "",
                message_id=str(message.id),
            )
        finally:
            client.close()

        details = _message_flow_details(
            campaign.delivery_mode,
            "follow_prompt",
            comment_id_str,
            trigger_keyword,
            str(message.lead_id),
            campaign.follow_prompt_profile_url,
        )

        if not result.success:
            mark_message_failed(db, message.id, result.error_code or "unknown", result.error_message, retryable=result.retryable)
            if result.retryable:
                increment_retry_count(db, message.id)
            campaign.failed_sends += 1
            db.commit()
            log_action(
                db,
                "message_failed_retryable" if result.retryable else "message_failed",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={"message_id": message_id, "error": result.error_message, **details},
            )
            if result.retryable:
                raise self.retry(countdown=60 * (2 ** self.request.retries), exc=Exception(result.error_message))
            return

        mark_message_sent(db, message.id, result.provider_message_id)
        db.commit()
        log_action(
            db,
            "follow_prompt_sent",
            campaign_id=campaign.id,
            lead_id=message.lead_id,
            details={"message_id": message_id, "provider_message_id": result.provider_message_id, **details},
        )

        final_message = get_message_by_context(db, campaign.id, message.comment_id, "final_delivery")
        if not final_message:
            try:
                from app.models.lead import Lead

                lead = db.query(Lead).filter(Lead.id == message.lead_id).first()
                rendered = render_campaign_message(
                    campaign.message_template,
                    username=(lead.ig_username if lead else None) or "there",
                    campaign_name=campaign.name,
                    keyword=trigger_keyword,
                    link=campaign.link_url,
                    media_url=campaign.media_url,
                )
            except Exception as exc:
                logger.exception("Final delivery render failed", extra={"campaign_id": str(campaign.id)})
                log_action(db, "message_render_failed", campaign_id=campaign.id, lead_id=message.lead_id, details={"error": str(exc), **details})
                return

            final_message = create_queued_message(
                db,
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                comment_id=message.comment_id,
                rendered_body=rendered,
                message_type="final_delivery",
                source_media_id=message.source_media_id,
                source_media_type=message.source_media_type,
                source_media_label=message.source_media_label,
            )

        log_action(
            db,
            "follow_prompt_awaiting_tap",
            campaign_id=campaign.id,
            lead_id=message.lead_id,
            details={"message_id": str(final_message.id), **details},
        )
        log_action(
            db,
            "final_delivery_queued",
            campaign_id=campaign.id,
            lead_id=message.lead_id,
            details={"message_id": str(final_message.id), **_message_flow_details(campaign.delivery_mode, "final_delivery", comment_id_str, trigger_keyword, str(message.lead_id))},
        )
        # No timer here. Delivery of final_message is now triggered only when
        # the user taps the postback button on this follow-prompt card,
        # handled by check_follow_and_deliver() below via the messaging_postbacks
        # webhook. See process_webhook_event() for the dispatch point.
    except Exception as exc:
        exc_name = type(exc).__name__
        if exc_name in ("Retry", "MaxRetriesExceededError"):
            raise
        logger.exception("send_follow_prompt_card failed", extra={"message_id": message_id})
        try:
            mark_message_failed(db, message_id, "task_exception", str(exc), retryable=False)
        except Exception:
            pass
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=4)
def send_private_reply(self, message_id: str):
    return _send_private_reply_impl(self, message_id)


@celery_app.task(bind=True, max_retries=4)
def send_final_delivery_after_follow_prompt(self, message_id: str, direct_recipient_id: str | None = None):
    return _send_private_reply_impl(
        self,
        message_id,
        final_after_prompt=True,
        direct_recipient_id=direct_recipient_id,
    )


@celery_app.task(bind=True, max_retries=4)
def send_facebook_private_reply(self, message_id: str):
    """Facebook equivalent of _send_private_reply_impl/send_private_reply.

    Simpler than the Instagram version: no follow_prompt/direct_recipient_id
    branch, since this phase's research spike found no Facebook equivalent
    of Instagram's follow-gate — every Facebook campaign message is sent via
    recipient.comment_id. Reuses the generic Message lifecycle functions
    (mark_message_sending/sent/failed/expired, increment_retry_count) from
    message_service.py directly — those only ever touched Message.id, never
    campaign_id/comment_id, so they needed no Facebook-specific copy.
    """
    db = _get_db()
    try:
        message = get_message_for_send(db, message_id)
        if not message:
            logger.warning("Facebook message not found for send", extra={"message_id": message_id})
            return
        if message.status == "sent":
            logger.info("Sent Facebook message skipped for idempotency", extra={"message_id": message_id})
            return

        campaign = (
            db.query(FacebookCampaign).filter(FacebookCampaign.id == message.facebook_campaign_id).first()
        )
        if not campaign:
            mark_message_skipped(db, message.id, "Facebook campaign not found")
            return

        if campaign.status != "active":
            mark_message_skipped(db, message.id, f"Campaign status is {campaign.status}")
            log_action(db, "message_skipped", facebook_page_id=campaign.facebook_page_id, details={"reason": "campaign_not_active"})
            return

        page = db.query(FacebookPage).filter(FacebookPage.id == campaign.facebook_page_id).first()
        if not page:
            mark_message_skipped(db, message.id, "Facebook page not found")
            return

        if page.status != "connected":
            # The Page was disconnected between queueing and sending.
            mark_message_skipped(db, message.id, f"Facebook page status is {page.status}")
            log_action(
                db,
                "message_skipped",
                facebook_page_id=page.id,
                details={"reason": "account_not_connected", "status": page.status},
            )
            return

        access_token = facebook_token_service.get_decrypted_token(db, page.id)
        if not access_token:
            mark_message_failed(db, message.id, "no_token", "No valid access token", retryable=False)
            log_action(db, "token_expired", facebook_page_id=page.id, details={"message_id": message_id})
            return

        mark_message_sending(db, message.id)

        comment = (
            db.query(FacebookComment).filter(FacebookComment.id == message.facebook_comment_id).first()
        )
        comment_id_str = comment.comment_id if comment else None
        if not comment_id_str:
            mark_message_failed(db, message.id, "no_comment", "No comment_id to reply to", retryable=False)
            return

        client = FacebookClient()
        try:
            result = client.send_private_reply(
                access_token=access_token,
                page_id=page.page_id,
                comment_id=comment_id_str,
                text=message.rendered_body or "",
            )
        finally:
            client.close()

        if result.success:
            mark_message_sent(db, message.id, result.provider_message_id)
            campaign.successful_sends += 1
            db.commit()

            # This is the only point at which Facebook tells us the
            # commenter's messaging identity. The comment webhook gave us an
            # app-scoped id (stored in lead.ig_user_id); the Send API response
            # carries `recipient_id`, which is the page-scoped id (PSID) that
            # inbound Messenger webhooks use and that recipient.id sends
            # require. Without capturing it here, the lead can never be
            # matched to their own reply.
            _record_facebook_psid(db, message.lead_id, page.id, result.raw_response)

            if campaign.comment_reply_enabled and campaign.comment_reply_text:
                try:
                    reply_client = FacebookClient()
                    try:
                        reply_result = reply_client.send_private_reply(
                            access_token=access_token,
                            page_id=page.page_id,
                            comment_id=comment_id_str,
                            text=campaign.comment_reply_text,
                        )
                    finally:
                        reply_client.close()
                    log_action(
                        db,
                        "comment_reply_sent" if reply_result.success else "comment_reply_failed",
                        facebook_page_id=page.id,
                        lead_id=message.lead_id,
                        details={"message_id": message_id, "comment_id": comment_id_str, "error": reply_result.error_message},
                    )
                except Exception:
                    logger.exception(
                        "Facebook comment reply raised after successful DM",
                        extra={"comment_id": comment_id_str, "message_id": message_id},
                    )

            log_action(
                db,
                "message_sent",
                facebook_page_id=page.id,
                lead_id=message.lead_id,
                details={"message_id": message_id, "provider_message_id": result.provider_message_id},
            )
            return

        if result.error_code == "expired_private_reply":
            mark_message_expired(db, message.id, result.error_code, result.error_message)
            log_action(
                db,
                "message_expired",
                facebook_page_id=page.id,
                lead_id=message.lead_id,
                details={"message_id": message_id, "error": result.error_message},
            )
            return

        if result.retryable:
            mark_message_failed(db, message.id, result.error_code, result.error_message, retryable=True)
            increment_retry_count(db, message.id)
            campaign.failed_sends += 1
            db.commit()
            log_action(
                db,
                "message_failed_retryable",
                facebook_page_id=page.id,
                lead_id=message.lead_id,
                details={"message_id": message_id, "error": result.error_message, "retry": self.request.retries},
            )
            raise self.retry(countdown=60 * (2 ** self.request.retries), exc=Exception(result.error_message))

        mark_message_failed(db, message.id, result.error_code or "unknown", result.error_message, retryable=False)
        campaign.failed_sends += 1
        db.commit()
        log_action(
            db,
            "message_failed",
            facebook_page_id=page.id,
            lead_id=message.lead_id,
            details={"message_id": message_id, "error": result.error_message},
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if exc_name in ("Retry", "MaxRetriesExceededError"):
            raise
        logger.exception("send_facebook_private_reply failed", extra={"message_id": message_id})
        try:
            mark_message_failed(db, message_id, "task_exception", str(exc), retryable=False)
        except Exception:
            pass
    finally:
        db.close()


@celery_app.task
def check_follow_and_deliver(message_id: str, sender_ig_id: str | None = None):
    """Real, event-driven replacement for the old 10s-delay fallback.

    Triggered by process_webhook_event() when a messaging_postbacks webhook
    event is received for a follow-prompt card's button. Checks live follow
    status via the Instagram User Profile API and either:
      - delivers the final message immediately (follow confirmed), or
      - re-sends the same follow-prompt card so the user can tap again
        after actually following (follow not confirmed / check inconclusive)

    message_id here is the id of the *follow_prompt* Message row (encoded
    in the button's postback payload), not the final_delivery row.
    """
    db = _get_db()
    try:
        message = get_message_for_send(db, message_id)
        if not message:
            logger.warning("Follow-check: follow_prompt message not found", extra={"message_id": message_id})
            return
        if message.message_type != "follow_prompt":
            logger.warning(
                "Follow-check: message is not a follow_prompt",
                extra={"message_id": message_id, "message_type": message.message_type},
            )
            return

        campaign = db.query(Campaign).filter(Campaign.id == message.campaign_id).first()
        if not campaign:
            logger.warning("Follow-check: campaign not found", extra={"message_id": message_id})
            return
        if campaign.status != "active":
            log_action(
                db,
                "follow_check_skipped",
                campaign_id=campaign.id,
                details={"reason": "campaign_not_active", "message_id": message_id},
            )
            return

        account = db.query(InstagramAccount).filter(InstagramAccount.id == campaign.instagram_account_id).first()
        if not account:
            logger.warning("Follow-check: instagram account not found", extra={"message_id": message_id})
            return

        access_token = get_decrypted_token(db, campaign.instagram_account_id)
        if not access_token:
            log_action(
                db,
                "token_expired",
                campaign_id=campaign.id,
                details={"message_id": message_id, "context": "follow_check"},
            )
            return

        from app.models.lead import Lead

        lead = db.query(Lead).filter(Lead.id == message.lead_id).first()
        ig_scoped_id = (lead.ig_user_id if lead else None) or sender_ig_id
        if not ig_scoped_id:
            logger.warning("Follow-check: no IGSID available", extra={"message_id": message_id})
            return

        comment_id_str, trigger_keyword = _matched_keyword_for_message(db, message)

        client = MetaMessagingClient()
        try:
            is_following = client.get_is_user_follow_business(access_token, ig_scoped_id)
        finally:
            client.close()

        details = _message_flow_details(
            campaign.delivery_mode,
            "follow_prompt",
            comment_id_str,
            trigger_keyword,
            str(message.lead_id),
            campaign.follow_prompt_profile_url,
        )

        if is_following:
            final_message = get_message_by_context(db, campaign.id, message.comment_id, "final_delivery")
            if not final_message:
                # Defensive fallback — send_follow_prompt_card already creates
                # this row when the prompt is first sent, so this branch
                # should not normally be hit.
                try:
                    rendered = render_campaign_message(
                        campaign.message_template,
                        username=(lead.ig_username if lead else None) or "there",
                        campaign_name=campaign.name,
                        keyword=trigger_keyword,
                        link=campaign.link_url,
                        media_url=campaign.media_url,
                    )
                except Exception as exc:
                    logger.exception("Follow-check: final delivery render failed", extra={"campaign_id": str(campaign.id)})
                    log_action(
                        db,
                        "message_render_failed",
                        campaign_id=campaign.id,
                        lead_id=message.lead_id,
                        details={"error": str(exc), **details},
                    )
                    return

                final_message = create_queued_message(
                    db,
                    campaign_id=campaign.id,
                    lead_id=message.lead_id,
                    comment_id=message.comment_id,
                    rendered_body=rendered,
                    message_type="final_delivery",
                    source_media_id=message.source_media_id,
                    source_media_type=message.source_media_type,
                    source_media_label=message.source_media_label,
                )

            log_action(
                db,
                "follow_confirmed_delivering",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={"message_id": str(final_message.id), **details},
            )
            # Deliver via recipient.id (24h window opened by the tap), NOT via
            # comment_id — the single permitted private reply per comment was
            # already consumed by the follow-prompt card itself.
            send_final_delivery_after_follow_prompt.delay(str(final_message.id), ig_scoped_id)
        else:
            # Not following, or the check was inconclusive (None) — treat
            # both the same way: re-send the identical follow-prompt card so
            # the button is live again.
            #
            # Sent via recipient.id, not comment_id: Meta permits only one
            # private reply per comment (subcode 2534014 on repeats), and
            # that allowance was consumed by the original prompt. The tap
            # that brought us here opened the 24-hour messaging window, so
            # recipient.id is both valid and the correct channel.
            #
            # No new Message row is created — the unique constraint on
            # (campaign_id, comment_id, message_type) forbids a second
            # follow_prompt row for the same comment, and the existing row
            # keeps its "sent" status.
            resend_client = MetaMessagingClient()
            try:
                resend_result = resend_client.send_follow_prompt_card(
                    access_token=access_token,
                    ig_user_id=account.ig_user_id,
                    comment_id=comment_id_str or "",
                    title=campaign.follow_prompt_title or "",
                    description=campaign.follow_prompt_description or "",
                    profile_url=campaign.follow_prompt_profile_url or "",
                    message_id=str(message.id),
                    recipient_id=ig_scoped_id,
                )
            finally:
                resend_client.close()

            log_action(
                db,
                "follow_not_confirmed_reprompted" if resend_result.success else "follow_reprompt_failed",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={
                    "message_id": message_id,
                    "is_following": is_following,
                    "resend_success": resend_result.success,
                    "resend_error": resend_result.error_message,
                    **details,
                },
            )
    except Exception:
        logger.exception("check_follow_and_deliver failed", extra={"message_id": message_id})
    finally:
        db.close()


@celery_app.task
def process_ai_conversation_turn(conversation_id: str, inbound_message_id: str):
    """Take one AI conversation turn: check handoff/budget conditions,
    generate a reply, send it, and log the result.

    Fails closed: any error here (API failure, timeout, missing token)
    stops this turn without retrying and without sending anything. It does
    NOT hand the conversation off automatically — a transient failure
    should not permanently kill the bot for that lead — but it also never
    silently retries in a way that could spam the user or the AI API.
    """
    # Celery serializes task args to JSON, so these normally arrive as str.
    # Normalize anyway: `details` is written to a JSONB column and a raw UUID
    # object is not JSON-serializable, which would raise *after* the reply was
    # already sent to the user.
    conversation_id = str(conversation_id)
    inbound_message_id = str(inbound_message_id)

    db = _get_db()
    try:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            logger.warning("Conversation not found for AI turn", extra={"conversation_id": conversation_id})
            return

        if conversation.status != "bot_active":
            logger.debug(
                "Conversation no longer bot_active, aborting AI turn",
                extra={"conversation_id": conversation_id, "status": conversation.status},
            )
            return

        # A cold-DM conversation has no originating campaign — its gates are
        # purely account-level. A campaign conversation keeps the exact
        # campaign checks it had before.
        is_cold_dm = conversation.campaign_id is None
        campaign = None
        if not is_cold_dm:
            campaign = db.query(Campaign).filter(Campaign.id == conversation.campaign_id).first()
            if not campaign or not campaign.ai_enabled or campaign.status != "active":
                conversation_service.hand_off(db, conversation, "campaign_inactive")
                logger.info(
                    "AI turn aborted: campaign missing / AI disabled / not active",
                    extra={
                        "conversation_id": conversation_id,
                        "campaign_id": str(conversation.campaign_id),
                        "campaign_ai_enabled": bool(campaign and campaign.ai_enabled),
                        "campaign_status": campaign.status if campaign else None,
                    },
                )
                log_action(
                    db,
                    "ai_conversation_handed_off",
                    campaign_id=campaign.id if campaign else None,
                    lead_id=conversation.lead_id,
                    instagram_account_id=conversation.instagram_account_id,
                    details={"conversation_id": conversation_id, "reason": "campaign_inactive"},
                )
                return

        account = (
            db.query(InstagramAccount).filter(InstagramAccount.id == conversation.instagram_account_id).first()
        )
        if not account or not account.ai_enabled:
            conversation_service.hand_off(db, conversation, "ai_disabled")
            logger.info(
                "AI turn aborted: account missing or account-level AI disabled",
                extra={
                    "conversation_id": conversation_id,
                    "instagram_account_id": str(conversation.instagram_account_id),
                },
            )
            log_action(
                db,
                "ai_conversation_handed_off",
                campaign_id=campaign.id if campaign else None,
                lead_id=conversation.lead_id,
                instagram_account_id=conversation.instagram_account_id,
                details={"conversation_id": conversation_id, "reason": "ai_disabled"},
            )
            return

        if is_cold_dm and not account.ai_cold_dm_enabled:
            conversation_service.hand_off(db, conversation, "cold_dm_ai_disabled")
            logger.info(
                "AI turn aborted: cold-DM AI disabled for account",
                extra={
                    "conversation_id": conversation_id,
                    "instagram_account_id": str(account.id),
                },
            )
            log_action(
                db,
                "ai_conversation_handed_off",
                campaign_id=None,
                lead_id=conversation.lead_id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "reason": "cold_dm_ai_disabled"},
            )
            return

        # --- Handoff conditions, checked before any model call ---
        handoff_after_turns = (
            campaign.ai_handoff_after_turns if campaign is not None else account.ai_handoff_after_turns
        )
        if conversation.turn_count >= handoff_after_turns:
            conversation_service.hand_off(db, conversation, "turn_limit")
            log_action(
                db,
                "ai_conversation_handed_off",
                campaign_id=campaign.id if campaign else None,
                lead_id=conversation.lead_id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "reason": "turn_limit"},
            )
            return

        if conversation_service.is_budget_exhausted(db, account):
            conversation_service.hand_off(db, conversation, "daily_cap_reached")
            log_action(
                db,
                "ai_conversation_handed_off",
                campaign_id=campaign.id if campaign else None,
                lead_id=conversation.lead_id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "reason": "daily_cap_reached"},
            )
            return

        access_token = get_decrypted_token(db, account.id)
        if not access_token:
            # Don't hand off — this is an infra problem, not a conversation
            # problem. Leave bot_active so the next inbound message retries.
            logger.warning("No access token for AI reply", extra={"instagram_account_id": str(account.id)})
            return

        lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
        if not lead:
            logger.warning("Lead not found for AI turn", extra={"conversation_id": conversation_id})
            return

        result = ai_service.generate_reply(db, account, campaign, conversation.id)
        if not result.success:
            logger.warning(
                "AI reply generation failed, no message sent",
                extra={"conversation_id": conversation_id, "error": result.error},
            )
            log_action(
                db,
                "ai_reply_failed",
                campaign_id=campaign.id if campaign else None,
                lead_id=lead.id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "error": result.error},
            )
            return

        client = MetaMessagingClient()
        try:
            send_result = client.send_direct_message(
                access_token=access_token,
                ig_user_id=account.ig_user_id,
                recipient_id=lead.ig_user_id,
                text=result.text,
            )
        finally:
            client.close()

        outbound_message = Message(
            campaign_id=campaign.id if campaign else None,
            lead_id=lead.id,
            conversation_id=conversation.id,
            direction="outbound",
            content=result.text,
            rendered_body=result.text,
            message_type="ai_conversation",
            status="sent" if send_result.success else "failed",
            provider_message_id=send_result.provider_message_id,
            error_code=send_result.error_code,
            error_message=send_result.error_message,
        )
        db.add(outbound_message)
        db.commit()

        if send_result.success:
            conversation_service.increment_turn(db, conversation)
            conversation_service.touch_conversation(db, conversation)
            conversation_service.record_ai_send(db, account)
            log_action(
                db,
                "ai_reply_sent",
                campaign_id=campaign.id if campaign else None,
                lead_id=lead.id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "turn_count": conversation.turn_count},
            )
        else:
            # Fail closed: do not retry automatically. Leave conversation
            # bot_active so the next inbound message from the user gives
            # the bot another chance, rather than looping on the same send.
            logger.warning(
                "AI reply send failed",
                extra={"conversation_id": conversation_id, "error": send_result.error_message},
            )
            log_action(
                db,
                "ai_reply_send_failed",
                campaign_id=campaign.id if campaign else None,
                lead_id=lead.id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "error": send_result.error_message},
            )
    except Exception:
        logger.exception("process_ai_conversation_turn failed", extra={"conversation_id": conversation_id})
    finally:
        db.close()


@celery_app.task
def process_whatsapp_ai_conversation_turn(conversation_id: str, inbound_message_id: str):
    """WhatsApp equivalent of process_ai_conversation_turn.

    A new, separate task rather than a branch inside the Instagram task:
    process_ai_conversation_turn is the single most business-critical piece
    of the running system (it sends real AI replies to live Instagram users
    today), and branching inside it risks that path for a DRY-ness gain that
    isn't worth it. Reuses the genuinely platform-agnostic pieces of
    conversation_service (budget/turn/handoff helpers) and ai_service
    (prompt generation, with platform="whatsapp" so the prompt text doesn't
    describe the bot as an Instagram assistant) rather than reimplementing
    them.

    Every WhatsApp conversation is cold-DM-shaped (no campaign_id), so there
    is no campaign-vs-cold_dm branch to mirror from the Instagram version.
    """
    conversation_id = str(conversation_id)
    inbound_message_id = str(inbound_message_id)

    db = _get_db()
    try:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            logger.warning(
                "Conversation not found for WhatsApp AI turn", extra={"conversation_id": conversation_id}
            )
            return

        if conversation.status != "bot_active":
            logger.debug(
                "Conversation no longer bot_active, aborting WhatsApp AI turn",
                extra={"conversation_id": conversation_id, "status": conversation.status},
            )
            return

        account = (
            db.query(WhatsappAccount)
            .filter(WhatsappAccount.id == conversation.whatsapp_account_id)
            .first()
        )
        # `status != connected` is folded into the same gate as ai_enabled:
        # a turn can be queued and then run after the number is disconnected.
        if not account or not account.ai_enabled or account.status != "connected":
            conversation_service.hand_off(db, conversation, "ai_disabled")
            logger.info(
                "WhatsApp AI turn aborted: account missing, disconnected, or account-level AI disabled",
                extra={
                    "conversation_id": conversation_id,
                    "whatsapp_account_id": str(conversation.whatsapp_account_id),
                },
            )
            log_action(
                db,
                "ai_conversation_handed_off",
                lead_id=conversation.lead_id,
                whatsapp_account_id=conversation.whatsapp_account_id,
                details={"conversation_id": conversation_id, "reason": "ai_disabled"},
            )
            return

        # --- Handoff conditions, checked before any model call ---
        if conversation.turn_count >= account.ai_handoff_after_turns:
            conversation_service.hand_off(db, conversation, "turn_limit")
            log_action(
                db,
                "ai_conversation_handed_off",
                lead_id=conversation.lead_id,
                whatsapp_account_id=account.id,
                details={"conversation_id": conversation_id, "reason": "turn_limit"},
            )
            return

        if conversation_service.is_budget_exhausted(db, account):
            conversation_service.hand_off(db, conversation, "daily_cap_reached")
            log_action(
                db,
                "ai_conversation_handed_off",
                lead_id=conversation.lead_id,
                whatsapp_account_id=account.id,
                details={"conversation_id": conversation_id, "reason": "daily_cap_reached"},
            )
            return

        access_token = whatsapp_token_service.get_decrypted_token(db, account.id)
        if not access_token:
            # Don't hand off — this is an infra problem, not a conversation
            # problem. Leave bot_active so the next inbound message retries.
            logger.warning("No access token for WhatsApp AI reply", extra={"whatsapp_account_id": str(account.id)})
            return

        lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
        if not lead:
            logger.warning("Lead not found for WhatsApp AI turn", extra={"conversation_id": conversation_id})
            return

        contact = (
            db.query(WhatsappContact)
            .filter(
                WhatsappContact.whatsapp_account_id == account.id,
                WhatsappContact.wa_id == lead.ig_user_id,
            )
            .first()
        )
        if (
            contact is None
            or contact.marketing_consent == "opted_out"
            or not in_service_window(contact)
        ):
            conversation_service.hand_off(db, conversation, "whatsapp_window_closed")
            log_action(
                db,
                "ai_conversation_handed_off",
                lead_id=lead.id,
                whatsapp_account_id=account.id,
                details={"conversation_id": conversation_id, "reason": "whatsapp_window_closed"},
            )
            return

        result = ai_service.generate_reply(db, account, None, conversation.id, platform="whatsapp")
        if not result.success:
            logger.warning(
                "WhatsApp AI reply generation failed, no message sent",
                extra={"conversation_id": conversation_id, "error": result.error},
            )
            log_action(
                db,
                "ai_reply_failed",
                lead_id=lead.id,
                whatsapp_account_id=account.id,
                details={"conversation_id": conversation_id, "error": result.error},
            )
            return

        client = WhatsappClient()
        try:
            send_result = client.send_text_message(
                access_token=access_token,
                phone_number_id=account.phone_number_id,
                recipient_wa_id=lead.ig_user_id,
                text=result.text,
            )
        finally:
            client.close()

        outbound_message = Message(
            campaign_id=None,
            lead_id=lead.id,
            conversation_id=conversation.id,
            direction="outbound",
            content=result.text,
            rendered_body=result.text,
            message_type="ai_conversation",
            status="sent" if send_result.success else "failed",
            provider_message_id=send_result.provider_message_id,
            error_code=send_result.error_code,
            error_message=send_result.error_message,
        )
        db.add(outbound_message)
        db.commit()

        if send_result.success:
            conversation_service.increment_turn(db, conversation)
            conversation_service.touch_conversation(db, conversation)
            conversation_service.record_ai_send(db, account)
            log_action(
                db,
                "ai_reply_sent",
                lead_id=lead.id,
                whatsapp_account_id=account.id,
                details={"conversation_id": conversation_id, "turn_count": conversation.turn_count},
            )
        else:
            # Fail closed: do not retry automatically. Leave conversation
            # bot_active so the next inbound message from the user gives
            # the bot another chance, rather than looping on the same send.
            logger.warning(
                "WhatsApp AI reply send failed",
                extra={"conversation_id": conversation_id, "error": send_result.error_message},
            )
            log_action(
                db,
                "ai_reply_send_failed",
                lead_id=lead.id,
                whatsapp_account_id=account.id,
                details={"conversation_id": conversation_id, "error": send_result.error_message},
            )
    except Exception:
        logger.exception(
            "process_whatsapp_ai_conversation_turn failed", extra={"conversation_id": conversation_id}
        )
    finally:
        db.close()


@celery_app.task
def process_facebook_ai_conversation_turn(conversation_id: str, inbound_message_id: str):
    """Facebook equivalent of process_ai_conversation_turn.

    A new, separate task per the established Phase 2 precedent — mirrors
    process_ai_conversation_turn's campaign-aware structure (not the
    simpler WhatsApp one), since Facebook Pages have the same
    campaign-vs-cold_dm branch Instagram does. Uses
    conversation.facebook_campaign_id (not campaign_id, which is FK'd
    strictly to Instagram's campaigns) to detect the cold-DM case, and
    reuses the platform-agnostic conversation_service budget/turn/handoff
    helpers plus ai_service.generate_reply(..., platform="facebook")
    unchanged.
    """
    conversation_id = str(conversation_id)
    inbound_message_id = str(inbound_message_id)

    db = _get_db()
    try:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            logger.warning("Conversation not found for Facebook AI turn", extra={"conversation_id": conversation_id})
            return

        if conversation.status != "bot_active":
            logger.debug(
                "Conversation no longer bot_active, aborting Facebook AI turn",
                extra={"conversation_id": conversation_id, "status": conversation.status},
            )
            return

        is_cold_dm = conversation.facebook_campaign_id is None
        campaign = None
        if not is_cold_dm:
            campaign = (
                db.query(FacebookCampaign).filter(FacebookCampaign.id == conversation.facebook_campaign_id).first()
            )
            if not campaign or not campaign.ai_enabled or campaign.status != "active":
                conversation_service.hand_off(db, conversation, "campaign_inactive")
                logger.info(
                    "Facebook AI turn aborted: campaign missing / AI disabled / not active",
                    extra={
                        "conversation_id": conversation_id,
                        "facebook_campaign_id": str(conversation.facebook_campaign_id),
                    },
                )
                log_action(
                    db,
                    "ai_conversation_handed_off",
                    facebook_page_id=conversation.facebook_page_id,
                    lead_id=conversation.lead_id,
                    details={"conversation_id": conversation_id, "reason": "campaign_inactive"},
                )
                return

        page = db.query(FacebookPage).filter(FacebookPage.id == conversation.facebook_page_id).first()
        # Same reasoning as WhatsApp's gate: a turn can be queued and then run
        # after the Page is disconnected.
        if not page or not page.ai_enabled or page.status != "connected":
            conversation_service.hand_off(db, conversation, "ai_disabled")
            logger.info(
                "Facebook AI turn aborted: page missing, disconnected, or account-level AI disabled",
                extra={"conversation_id": conversation_id, "facebook_page_id": str(conversation.facebook_page_id)},
            )
            log_action(
                db,
                "ai_conversation_handed_off",
                facebook_page_id=conversation.facebook_page_id,
                lead_id=conversation.lead_id,
                details={"conversation_id": conversation_id, "reason": "ai_disabled"},
            )
            return

        if is_cold_dm and not page.ai_cold_dm_enabled:
            conversation_service.hand_off(db, conversation, "cold_dm_ai_disabled")
            logger.info(
                "Facebook AI turn aborted: cold-DM AI disabled for account",
                extra={"conversation_id": conversation_id, "facebook_page_id": str(page.id)},
            )
            log_action(
                db,
                "ai_conversation_handed_off",
                facebook_page_id=page.id,
                lead_id=conversation.lead_id,
                details={"conversation_id": conversation_id, "reason": "cold_dm_ai_disabled"},
            )
            return

        handoff_after_turns = campaign.ai_handoff_after_turns if campaign is not None else page.ai_handoff_after_turns
        if conversation.turn_count >= handoff_after_turns:
            conversation_service.hand_off(db, conversation, "turn_limit")
            log_action(
                db,
                "ai_conversation_handed_off",
                facebook_page_id=page.id,
                lead_id=conversation.lead_id,
                details={"conversation_id": conversation_id, "reason": "turn_limit"},
            )
            return

        if conversation_service.is_budget_exhausted(db, page):
            conversation_service.hand_off(db, conversation, "daily_cap_reached")
            log_action(
                db,
                "ai_conversation_handed_off",
                facebook_page_id=page.id,
                lead_id=conversation.lead_id,
                details={"conversation_id": conversation_id, "reason": "daily_cap_reached"},
            )
            return

        access_token = facebook_token_service.get_decrypted_token(db, page.id)
        if not access_token:
            logger.warning("No access token for Facebook AI reply", extra={"facebook_page_id": str(page.id)})
            return

        lead = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
        if not lead:
            logger.warning("Lead not found for Facebook AI turn", extra={"conversation_id": conversation_id})
            return

        if not lead.facebook_psid:
            # No verified messaging identity. lead.ig_user_id is only a usable
            # recipient.id for cold-DM leads; for a campaign lead it holds the
            # comment's app-scoped id, which Meta rejects as a recipient. Sending
            # it anyway would be a guaranteed API failure recorded as a "failed"
            # message, which reads like a Meta outage rather than the real cause.
            #
            # Not a handoff: like the missing-token case above this is an
            # identity problem, not a conversation problem. The conversation
            # stays bot_active so the next successful private reply (which is
            # what discloses the PSID) lets the bot pick straight back up.
            logger.warning(
                "Facebook AI turn aborted: no verified messaging identity for this lead "
                "(facebook_psid is unset, so no private reply has succeeded yet)",
                extra={"conversation_id": conversation_id, "lead_id": str(lead.id)},
            )
            log_action(
                db,
                "ai_reply_skipped",
                facebook_page_id=page.id,
                lead_id=lead.id,
                details={
                    "conversation_id": conversation_id,
                    "reason": "no_messaging_identity",
                },
            )
            return

        result = ai_service.generate_reply(db, page, campaign, conversation.id, platform="facebook")
        if not result.success:
            logger.warning(
                "Facebook AI reply generation failed, no message sent",
                extra={"conversation_id": conversation_id, "error": result.error},
            )
            log_action(
                db,
                "ai_reply_failed",
                facebook_page_id=page.id,
                lead_id=lead.id,
                details={"conversation_id": conversation_id, "error": result.error},
            )
            return

        client = FacebookClient()
        try:
            send_result = client.send_direct_message(
                access_token=access_token,
                page_id=page.page_id,
                # recipient.id must be a PSID, never ig_user_id: that holds
                # the comment's app-scoped id for a campaign lead. Guaranteed
                # non-null by the guard above.
                recipient_id=lead.facebook_psid,
                text=result.text,
            )
        finally:
            client.close()

        outbound_message = Message(
            campaign_id=None,
            comment_id=None,
            facebook_campaign_id=campaign.id if campaign else None,
            lead_id=lead.id,
            conversation_id=conversation.id,
            direction="outbound",
            content=result.text,
            rendered_body=result.text,
            message_type="ai_conversation",
            status="sent" if send_result.success else "failed",
            provider_message_id=send_result.provider_message_id,
            error_code=send_result.error_code,
            error_message=send_result.error_message,
        )
        db.add(outbound_message)
        db.commit()

        if send_result.success:
            conversation_service.increment_turn(db, conversation)
            conversation_service.touch_conversation(db, conversation)
            conversation_service.record_ai_send(db, page)
            log_action(
                db,
                "ai_reply_sent",
                facebook_page_id=page.id,
                lead_id=lead.id,
                details={"conversation_id": conversation_id, "turn_count": conversation.turn_count},
            )
        else:
            logger.warning(
                "Facebook AI reply send failed",
                extra={"conversation_id": conversation_id, "error": send_result.error_message},
            )
            log_action(
                db,
                "ai_reply_send_failed",
                facebook_page_id=page.id,
                lead_id=lead.id,
                details={"conversation_id": conversation_id, "error": send_result.error_message},
            )
    except Exception:
        logger.exception("process_facebook_ai_conversation_turn failed", extra={"conversation_id": conversation_id})
    finally:
        db.close()

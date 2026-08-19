import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.integrations.meta.messaging import MetaMessagingClient
from app.integrations.meta.webhooks import (
    parse_instagram_comment_events,
    parse_instagram_message_events,
    parse_instagram_postback_events,
)
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.conversation import Conversation
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.webhook_event import WebhookEvent
from app.services import ai_service, conversation_service
from app.services.campaign_matcher import find_matching_campaigns, find_matching_keyword
from app.services.comment_service import upsert_comment
from app.services.cooldown_service import is_in_cooldown, record_cooldown
from app.services.lead_service import upsert_lead_from_comment
from app.services.log_service import log_action
from app.services.processed_event_service import build_event_key, check_and_mark_processed
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


@celery_app.task
def process_webhook_event(webhook_event_id: str):
    db = _get_db()
    try:
        event = db.query(WebhookEvent).filter(WebhookEvent.id == webhook_event_id).first()
        if not event:
            logger.warning("Webhook event not found", extra={"event_id": webhook_event_id})
            return

        log_action(db, "webhook_received", details={"event_id": webhook_event_id})

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
                logger.debug("Duplicate inbound message event skipped", extra={"event_key": msg_event_key})
                continue

            account = (
                db.query(InstagramAccount)
                .filter(InstagramAccount.ig_user_id == msg_evt.instagram_account_ig_user_id)
                .first()
            )
            if not account:
                logger.warning(
                    "Instagram account not found for inbound message",
                    extra={"ig_user_id": msg_evt.instagram_account_ig_user_id},
                )
                continue

            if not account.ai_enabled:
                # AI layer is opt-in at the account level. Without it, an
                # inbound DM reply is simply not actioned automatically —
                # this is intentional, not a bug: no campaign context exists
                # to reply from without a human or the AI layer involved.
                continue

            lead = (
                db.query(Lead)
                .filter(
                    Lead.workspace_id == account.workspace_id,
                    Lead.instagram_account_id == account.id,
                    Lead.ig_user_id == msg_evt.sender_ig_id,
                )
                .first()
            )
            if not lead or not lead.source_campaign_id:
                # No known lead / originating campaign for this sender —
                # nothing to continue. Do not guess which campaign applies.
                logger.info(
                    "Inbound message from unknown lead, skipping AI reply",
                    extra={"sender_ig_id": msg_evt.sender_ig_id, "instagram_account_id": str(account.id)},
                )
                continue

            campaign = db.query(Campaign).filter(Campaign.id == lead.source_campaign_id).first()
            if not campaign or not campaign.ai_enabled:
                continue

            conversation = conversation_service.get_or_create_conversation(
                db,
                workspace_id=account.workspace_id,
                lead_id=lead.id,
                campaign_id=campaign.id,
                instagram_account_id=account.id,
            )

            # Store the inbound message regardless of conversation status,
            # so a human taking over still sees the full thread.
            inbound_message = Message(
                campaign_id=campaign.id,
                lead_id=lead.id,
                conversation_id=conversation.id,
                direction="inbound",
                content=msg_evt.text,
                rendered_body=msg_evt.text,
                message_type="ai_conversation",
                status="received",
            )
            db.add(inbound_message)
            conversation_service.touch_conversation(db, conversation)
            db.commit()
            db.refresh(inbound_message)

            if conversation.status != "bot_active":
                logger.debug(
                    "Conversation not bot_active, skipping AI reply",
                    extra={"conversation_id": str(conversation.id), "status": conversation.status},
                )
                continue

            process_ai_conversation_turn.delay(str(conversation.id), str(inbound_message.id))

        event.processing_status = "processed"
        db.commit()
        log_action(db, "webhook_processed", details={"event_id": webhook_event_id})
    except Exception:
        logger.exception("process_webhook_event failed", extra={"event_id": webhook_event_id})
        try:
            event.processing_status = "failed"
            db.commit()
        except Exception:
            pass
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

        if result.error_code == "retryable":
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
            mark_message_failed(db, message.id, result.error_code or "unknown", result.error_message, retryable=result.error_code == "retryable")
            if result.error_code == "retryable":
                increment_retry_count(db, message.id)
            campaign.failed_sends += 1
            db.commit()
            log_action(
                db,
                "message_failed_retryable" if result.error_code == "retryable" else "message_failed",
                campaign_id=campaign.id,
                lead_id=message.lead_id,
                details={"message_id": message_id, "error": result.error_message, **details},
            )
            if result.error_code == "retryable":
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

        campaign = db.query(Campaign).filter(Campaign.id == conversation.campaign_id).first()
        if not campaign or not campaign.ai_enabled or campaign.status != "active":
            conversation_service.hand_off(db, conversation, "campaign_inactive")
            return

        account = (
            db.query(InstagramAccount).filter(InstagramAccount.id == conversation.instagram_account_id).first()
        )
        if not account or not account.ai_enabled:
            conversation_service.hand_off(db, conversation, "ai_disabled")
            return

        # --- Handoff conditions, checked before any model call ---
        if conversation.turn_count >= campaign.ai_handoff_after_turns:
            conversation_service.hand_off(db, conversation, "turn_limit")
            log_action(
                db,
                "ai_conversation_handed_off",
                campaign_id=campaign.id,
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
                campaign_id=campaign.id,
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
                campaign_id=campaign.id,
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
            campaign_id=campaign.id,
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
                campaign_id=campaign.id,
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
                campaign_id=campaign.id,
                lead_id=lead.id,
                instagram_account_id=account.id,
                details={"conversation_id": conversation_id, "error": send_result.error_message},
            )
    except Exception:
        logger.exception("process_ai_conversation_turn failed", extra={"conversation_id": conversation_id})
    finally:
        db.close()
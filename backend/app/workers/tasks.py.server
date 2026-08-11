import logging
import inspect
import asyncio

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.integrations.meta.messaging import MetaMessagingClient
from app.integrations.meta.webhooks import parse_instagram_comment_events
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.instagram_account import InstagramAccount
from app.models.message import Message
from app.models.webhook_event import WebhookEvent
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


def _resolve_maybe_awaitable(value):
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


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
        if not comment_events:
            event.processing_status = "skipped"
            db.commit()
            log_action(db, "webhook_skipped", details={"reason": "no_comment_events", "event_id": webhook_event_id})
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


def _send_private_reply_impl(task, message_id: str, final_after_prompt: bool = False):
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

        # Send via Meta API
        client = MetaMessagingClient()
        try:
            result = _resolve_maybe_awaitable(client.send_private_reply(
                access_token=access_token,
                comment_id=comment_id_str,
                text=message.rendered_body or "",
            ))
        finally:
            _resolve_maybe_awaitable(client.close())

        if result.success:
            mark_message_sent(db, message.id, result.provider_message_id)
            campaign.successful_sends += 1
            db.commit()
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
            # Retry with exponential backoff
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
        # Let Celery retry exceptions propagate naturally
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

        access_token = get_decrypted_token(db, campaign.instagram_account_id)
        if not access_token:
            mark_message_failed(db, message.id, "no_token", "No valid access token", retryable=False)
            log_action(db, "token_expired", campaign_id=campaign.id, details={"message_id": message_id})
            return

        comment_id_str, trigger_keyword = _matched_keyword_for_message(db, message)
        mark_message_sending(db, message.id)

        client = MetaMessagingClient()
        try:
            result = _resolve_maybe_awaitable(client.send_follow_prompt_card(
                access_token=access_token,
                recipient_id=comment_id_str or "",
                title=campaign.follow_prompt_title or "",
                description=campaign.follow_prompt_description or "",
                profile_url=campaign.follow_prompt_profile_url or "",
            ))
        finally:
            _resolve_maybe_awaitable(client.close())

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
            "follow_prompt_delay_started",
            campaign_id=campaign.id,
            lead_id=message.lead_id,
            details={"message_id": str(final_message.id), "delay_seconds": 10, **details},
        )
        log_action(
            db,
            "final_delivery_queued",
            campaign_id=campaign.id,
            lead_id=message.lead_id,
            details={"message_id": str(final_message.id), **_message_flow_details(campaign.delivery_mode, "final_delivery", comment_id_str, trigger_keyword, str(message.lead_id))},
        )
        send_final_delivery_after_follow_prompt.apply_async(args=[str(final_message.id)], countdown=10)
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
def send_final_delivery_after_follow_prompt(self, message_id: str):
    return _send_private_reply_impl(self, message_id, final_after_prompt=True)

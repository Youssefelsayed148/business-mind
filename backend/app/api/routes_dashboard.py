import csv
import io
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.routes_auth import get_current_user
from app.db.session import get_db
from app.models.automation_log import AutomationLog
from app.models.audit_log import AuditLog
from app.models.campaign import Campaign
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.user import User
from app.models.workspace import Workspace
from app.models.comment import Comment
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_page import FacebookPage
from app.models.whatsapp_account import WhatsappAccount

router = APIRouter()


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _campaign_names(db: Session, campaign_ids: set[UUID]) -> dict[str, str]:
    if not campaign_ids:
        return {}
    campaigns = db.query(Campaign.id, Campaign.name).filter(Campaign.id.in_(campaign_ids)).all()
    return {str(campaign_id): name for campaign_id, name in campaigns}


def _audit_response(log: AuditLog) -> dict:
    return {
        "id": str(log.id),
        "level": "error" if log.severity == "danger" else log.severity,
        "campaign_id": None,
        "campaign": log.entity_name if log.entity_type == "campaign" else None,
        "event_type": log.action,
        "message": log.message,
        "metadata": {
            **(log.metadata_ or {}),
            "actor_user_id": str(log.actor_user_id) if log.actor_user_id else None,
            "actor_email": log.actor_email,
            "entity_type": log.entity_type,
            "entity_id": str(log.entity_id) if log.entity_id else None,
            "entity_name": log.entity_name,
            "severity": log.severity,
        },
        "actor_email": log.actor_email,
        "entity_type": log.entity_type,
        "entity_name": log.entity_name,
        "severity": log.severity,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _trigger_keyword_for_campaign_comment(
    db: Session, campaign_id: UUID | None, comment_id: UUID | None
) -> str | None:
    if not campaign_id or not comment_id:
        return None

    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        return None

    log = (
        db.query(AutomationLog)
        .filter(
            AutomationLog.campaign_id == campaign_id,
            AutomationLog.action == "campaign_matched",
            AutomationLog.details["comment_id"].astext == comment.comment_id,
        )
        .order_by(AutomationLog.created_at.desc())
        .first()
    )
    if log and log.details:
        keyword = log.details.get("matched_keyword") or log.details.get("trigger_keyword")
        if isinstance(keyword, str) and keyword:
            return keyword

    message = (
        db.query(Message)
        .filter(
            Message.campaign_id == campaign_id,
            Message.comment_id == comment_id,
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if not message:
        return None

    log = (
        db.query(AutomationLog)
        .filter(
            AutomationLog.campaign_id == campaign_id,
            AutomationLog.lead_id == message.lead_id,
        )
        .order_by(AutomationLog.created_at.desc())
        .first()
    )
    if log and log.details:
        keyword = log.details.get("trigger_keyword") or log.details.get("matched_keyword")
        if isinstance(keyword, str) and keyword:
            return keyword

    return None


@router.get("/stats/overview")
async def overview_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = _today_start()
    active_instagram_campaigns = (
        db.query(Campaign)
        .join(
            InstagramAccount,
            InstagramAccount.id == Campaign.instagram_account_id,
        )
        .filter(
            Campaign.status == "active",
            InstagramAccount.status == "connected",
        )
        .count()
    )
    active_facebook_campaigns = (
        db.query(FacebookCampaign)
        .join(
            FacebookPage,
            FacebookPage.id == FacebookCampaign.facebook_page_id,
        )
        .filter(
            FacebookCampaign.status == "active",
            FacebookPage.status == "connected",
        )
        .count()
    )
    return {
        "active_campaigns": active_instagram_campaigns + active_facebook_campaigns,
        "triggers_today": db.query(AutomationLog).filter(
            AutomationLog.created_at >= today,
            AutomationLog.action.in_(["matched", "triggered", "message_created"]),
        ).count(),
        "messages_sent_today": db.query(Message).filter(
            Message.created_at >= today,
            Message.status == "sent",
        ).count(),
        "failed_messages_today": db.query(Message).filter(
            Message.created_at >= today,
            Message.status == "failed",
        ).count(),
        "new_leads_today": db.query(Lead).filter(Lead.created_at >= today).count(),
    }


@router.get("/campaigns/{campaign_id}/stats")
async def campaign_stats(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return Response(status_code=404)
    account = (
        db.query(InstagramAccount)
        .filter(InstagramAccount.id == campaign.instagram_account_id)
        .first()
    )
    created_audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "campaign",
            AuditLog.entity_id == campaign.id,
            AuditLog.action == "campaign_created",
        )
        .order_by(AuditLog.created_at.asc())
        .first()
    )

    status_counts = dict(
        db.query(Message.status, func.count(Message.id))
        .filter(Message.campaign_id == campaign_id)
        .group_by(Message.status)
        .all()
    )
    recent_messages = (
        db.query(Message)
        .filter(Message.campaign_id == campaign_id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )
    lead_ids = {message.lead_id for message in recent_messages if message.lead_id}
    leads_by_id = {
        lead.id: lead
        for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
    } if lead_ids else {}
    recent_logs = (
        db.query(AutomationLog)
        .filter(AutomationLog.campaign_id == campaign_id)
        .order_by(AutomationLog.created_at.desc())
        .limit(10)
        .all()
    )
    last_triggered_at = (
        db.query(func.max(AutomationLog.created_at))
        .filter(
            AutomationLog.campaign_id == campaign_id,
            AutomationLog.action.in_(["campaign_matched", "message_queued", "follow_prompt_queued"]),
        )
        .scalar()
    )
    cooldown_logs = (
        db.query(AutomationLog)
        .filter(
            AutomationLog.campaign_id == campaign_id,
            AutomationLog.action == "cooldown_skip",
        )
        .count()
    )
    new_leads = (
        db.query(Lead)
        .filter(
            Lead.source_campaign_id == campaign_id,
            Lead.status == "new",
        )
        .count()
    )

    return {
        "campaign_id": str(campaign.id),
        "name": campaign.name,
        "status": campaign.status,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "created_by": (
            created_audit.actor_email
            or ((created_audit.metadata_ or {}).get("created_by") if created_audit else None)
        ) if created_audit else None,
        "account_username": account.ig_username if account else None,
        "account_ig_user_id": account.ig_user_id if account else None,
        "target_scope": campaign.target_scope,
        "target_media_label": campaign.target_media_label,
        "target_media_type": campaign.target_media_type,
        "target_media_url": campaign.target_media_url,
        "keywords": [keyword.normalized_keyword for keyword in campaign.keywords],
        "match_type": campaign.match_type,
        "cooldown_hours": campaign.cooldown_hours,
        "delivery_mode": campaign.delivery_mode,
        "message_template": campaign.message_template,
        "link_url": campaign.link_url,
        "follow_prompt_title": campaign.follow_prompt_title,
        "follow_prompt_description": campaign.follow_prompt_description,
        "follow_prompt_profile_url": campaign.follow_prompt_profile_url,
        "comment_reply_enabled": campaign.comment_reply_enabled,
        "comment_reply_text": campaign.comment_reply_text,
        "last_triggered_at": last_triggered_at.isoformat() if last_triggered_at else None,
        "new_leads": new_leads,
        "total_triggers": campaign.total_triggers,
        "successful_sends": campaign.successful_sends,
        "failed_sends": campaign.failed_sends,
        "expired": int(status_counts.get("expired", 0)),
        "cooldowns": int(status_counts.get("skipped", 0)) + cooldown_logs,
        "recent_messages": [
            {
                "id": str(message.id),
                "status": message.status,
                "message_type": message.message_type,
                "lead_id": str(message.lead_id),
                "username": leads_by_id.get(message.lead_id).ig_username if message.lead_id in leads_by_id else None,
                "comment_id": str(message.comment_id) if message.comment_id else None,
                "source_media_id": message.source_media_id,
                "source_media_type": message.source_media_type,
                "source_media_label": message.source_media_label,
                "retry_count": message.retry_count,
                "error_message": message.error_message,
                "sent_at": message.created_at.isoformat() if message.status == "sent" and message.created_at else None,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message in recent_messages
        ],
        "recent_logs": [
            {
                "id": str(log.id),
                "campaign_id": str(log.campaign_id) if log.campaign_id else None,
                "event_type": log.action,
                "message": (log.details or {}).get("message") or log.action.replace("_", " ").title(),
                "metadata": log.details or {},
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in recent_logs
        ],
    }


def _account_usernames(db: Session, account_ids: set[UUID]) -> dict[str, str]:
    # Callers pass a set comprehension over every lead, which now includes
    # None for WhatsApp/Facebook rows. Harmless (it renders IN (NULL, ...))
    # but filtered for consistency with the two helpers below.
    account_ids = {a for a in account_ids if a is not None}
    if not account_ids:
        return {}
    rows = (
        db.query(InstagramAccount.id, InstagramAccount.ig_username)
        .filter(InstagramAccount.id.in_(account_ids))
        .all()
    )
    return {str(acc_id): (username or "") for acc_id, username in rows}


def _whatsapp_account_names(db: Session, account_ids: set[UUID]) -> dict[str, str]:
    account_ids = {a for a in account_ids if a is not None}
    if not account_ids:
        return {}
    rows = (
        db.query(WhatsappAccount.id, WhatsappAccount.display_phone_number)
        .filter(WhatsappAccount.id.in_(account_ids))
        .all()
    )
    return {str(acc_id): (name or "") for acc_id, name in rows}


def _facebook_page_names(db: Session, page_ids: set[UUID]) -> dict[str, str]:
    page_ids = {p for p in page_ids if p is not None}
    if not page_ids:
        return {}
    rows = (
        db.query(FacebookPage.id, FacebookPage.page_name)
        .filter(FacebookPage.id.in_(page_ids))
        .all()
    )
    return {str(page_id): (name or "") for page_id, name in rows}


def _facebook_campaign_names(db: Session, campaign_ids: set[UUID]) -> dict[str, str]:
    campaign_ids = {c for c in campaign_ids if c is not None}
    if not campaign_ids:
        return {}
    campaigns = (
        db.query(FacebookCampaign.id, FacebookCampaign.name)
        .filter(FacebookCampaign.id.in_(campaign_ids))
        .all()
    )
    return {str(campaign_id): name for campaign_id, name in campaigns}


def _facebook_campaign_and_keyword_for_lead(
    db: Session, lead_id: UUID
) -> tuple[UUID | None, str | None]:
    """Facebook leads carry no source_campaign_id -- that FK is strictly
    Instagram's (see facebook_lead_service.upsert_lead_from_facebook_comment).
    The originating facebook_campaigns row instead lives on the Message row,
    and AutomationLog has no facebook_campaign_id column either, so the
    matched keyword logged alongside it is keyed by lead_id rather than by
    campaign_id the way _trigger_keyword_for_campaign_comment looks it up.
    """
    message = (
        db.query(Message)
        .filter(Message.lead_id == lead_id, Message.facebook_campaign_id.isnot(None))
        .order_by(Message.created_at.desc())
        .first()
    )
    if not message:
        return None, None

    keyword = None
    log = (
        db.query(AutomationLog)
        .filter(AutomationLog.lead_id == lead_id, AutomationLog.action == "message_queued")
        .order_by(AutomationLog.created_at.desc())
        .first()
    )
    if log and log.details:
        value = log.details.get("matched_keyword")
        if isinstance(value, str) and value:
            keyword = value

    return message.facebook_campaign_id, keyword


@router.get("/leads")
async def list_leads(
    campaign_id: UUID | None = None,
    instagram_account_id: UUID | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Lead)
    if campaign_id:
        query = query.filter(Lead.source_campaign_id == campaign_id)
    if instagram_account_id:
        query = query.filter(Lead.instagram_account_id == instagram_account_id)
    if search:
        query = query.filter(Lead.ig_username.ilike(f"%{search}%"))

    leads = query.order_by(Lead.created_at.desc()).all()
    names = _campaign_names(db, {lead.source_campaign_id for lead in leads if lead.source_campaign_id})
    account_names = _account_usernames(db, {lead.instagram_account_id for lead in leads})
    whatsapp_names = _whatsapp_account_names(db, {lead.whatsapp_account_id for lead in leads})
    facebook_names = _facebook_page_names(db, {lead.facebook_page_id for lead in leads})
    fb_campaign_lookup = {
        lead.id: _facebook_campaign_and_keyword_for_lead(db, lead.id)
        for lead in leads
        if lead.platform == "facebook" and lead.lead_source == "campaign"
    }
    fb_campaign_names = _facebook_campaign_names(
        db, {fb_cid for fb_cid, _ in fb_campaign_lookup.values()}
    )

    results = []
    for lead in leads:
        fb_campaign_id, fb_keyword = fb_campaign_lookup.get(lead.id, (None, None))
        source_campaign_id = lead.source_campaign_id or fb_campaign_id
        source_campaign = (
            names.get(str(lead.source_campaign_id))
            if lead.source_campaign_id
            else (fb_campaign_names.get(str(fb_campaign_id)) if fb_campaign_id else None)
        )
        keyword = (
            _trigger_keyword_for_campaign_comment(db, lead.source_campaign_id, lead.source_comment_id)
            or fb_keyword
        )
        results.append(
            {
                "id": str(lead.id),
                "username": lead.ig_username,
                "ig_user_id": lead.ig_user_id,
                "lead_source": lead.lead_source,
                "platform": lead.platform,
                "source_campaign_id": str(source_campaign_id) if source_campaign_id else None,
                "source_campaign": source_campaign,
                "source_media_id": lead.source_media_id,
                "source_media_type": lead.source_media_type,
                "source_media_label": lead.source_media_label,
                "keyword": keyword,
                "instagram_account_id": str(lead.instagram_account_id) if lead.instagram_account_id else None,
                "instagram_account_username": account_names.get(str(lead.instagram_account_id)) or None,
                "whatsapp_account_id": str(lead.whatsapp_account_id) if lead.whatsapp_account_id else None,
                "whatsapp_account_username": whatsapp_names.get(str(lead.whatsapp_account_id)) or None,
                "facebook_page_id": str(lead.facebook_page_id) if lead.facebook_page_id else None,
                "facebook_page_username": facebook_names.get(str(lead.facebook_page_id)) or None,
                "tags": [],
                "first_seen": lead.created_at.isoformat() if lead.created_at else None,
                "last_seen": lead.last_seen_at.isoformat() if lead.last_seen_at else None,
                "captured_at": lead.created_at.isoformat() if lead.created_at else None,
            }
        )
    return results


def _csv_safe(value: str) -> str:
    """Keep customer-controlled cells from becoming spreadsheet formulas."""
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


@router.get("/leads/export.csv")
async def export_leads_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    names = _campaign_names(db, {lead.source_campaign_id for lead in leads if lead.source_campaign_id})
    acc_names = _account_usernames(db, {lead.instagram_account_id for lead in leads})
    whatsapp_names = _whatsapp_account_names(db, {lead.whatsapp_account_id for lead in leads})
    facebook_names = _facebook_page_names(db, {lead.facebook_page_id for lead in leads})
    fb_campaign_lookup = {
        lead.id: _facebook_campaign_and_keyword_for_lead(db, lead.id)
        for lead in leads
        if lead.platform == "facebook" and lead.lead_source == "campaign"
    }
    fb_campaign_names = _facebook_campaign_names(
        db, {fb_cid for fb_cid, _ in fb_campaign_lookup.values()}
    )

    def _source_campaign_label(lead: Lead) -> str:
        if lead.source_campaign_id:
            return names.get(str(lead.source_campaign_id), "")
        fb_campaign_id, _ = fb_campaign_lookup.get(lead.id, (None, None))
        return fb_campaign_names.get(str(fb_campaign_id), "") if fb_campaign_id else ""

    def _account_label(lead: Lead) -> str:
        # Exactly one of the three FKs is set per lead
        # (ck_leads_platform_account_fk), so this resolves unambiguously.
        if lead.instagram_account_id:
            return acc_names.get(str(lead.instagram_account_id), "")
        if lead.whatsapp_account_id:
            return whatsapp_names.get(str(lead.whatsapp_account_id), "")
        if lead.facebook_page_id:
            return facebook_names.get(str(lead.facebook_page_id), "")
        return ""

    output = io.StringIO()
    writer = csv.writer(output)
    # `user_id` rather than `ig_user_id`: for WhatsApp rows this column holds
    # the WA ID and for Facebook rows the commenter/PSID, not an Instagram id.
    writer.writerow(
        [
            "platform",
            "username",
            "user_id",
            "lead_source",
            "source_campaign",
            "account",
            "first_seen",
            "last_seen",
        ]
    )
    for lead in leads:
        row = [
            lead.platform or "",
            lead.ig_username or "",
            lead.ig_user_id,
            lead.lead_source or "",
            _source_campaign_label(lead),
            _account_label(lead),
            lead.created_at.isoformat() if lead.created_at else "",
            lead.last_seen_at.isoformat() if lead.last_seen_at else "",
        ]
        writer.writerow([_csv_safe(value) for value in row])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@router.get("/logs")
async def list_logs(
    level: str | None = None,
    campaign_id: UUID | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(AutomationLog)
    if campaign_id:
        query = query.filter(AutomationLog.campaign_id == campaign_id)
    if event_type:
        event_types = [item.strip() for item in event_type.split(",") if item.strip()]
        query = query.filter(AutomationLog.action.in_(event_types))

    logs = query.order_by(AutomationLog.created_at.desc()).limit(limit).all()
    if level:
        logs = [log for log in logs if (log.details or {}).get("level", "info") == level]
    names = _campaign_names(db, {log.campaign_id for log in logs if log.campaign_id})
    automation_rows = [
        {
            "id": str(log.id),
            "level": (log.details or {}).get("level", "info"),
            "campaign_id": str(log.campaign_id) if log.campaign_id else None,
            "campaign": names.get(str(log.campaign_id)) if log.campaign_id else None,
            "event_type": log.action,
            "message": (log.details or {}).get("message") or log.action.replace("_", " ").title(),
            "metadata": log.details or {},
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]

    audit_query = db.query(AuditLog)
    if event_type:
        audit_query = audit_query.filter(AuditLog.action.in_(event_types))
    if level:
        audit_level = "danger" if level == "error" else level
        audit_query = audit_query.filter(AuditLog.severity == audit_level)
    audit_rows = [_audit_response(log) for log in audit_query.order_by(AuditLog.created_at.desc()).limit(limit).all()]
    merged = sorted(
        [*automation_rows, *audit_rows],
        key=lambda row: row.get("created_at") or "",
        reverse=True,
    )
    return merged[:limit]

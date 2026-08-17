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
    return {
        "active_campaigns": (
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
        ),
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
    if not account_ids:
        return {}
    rows = (
        db.query(InstagramAccount.id, InstagramAccount.ig_username)
        .filter(InstagramAccount.id.in_(account_ids))
        .all()
    )
    return {str(acc_id): (username or "") for acc_id, username in rows}


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
    return [
        {
            "id": str(lead.id),
            "username": lead.ig_username,
            "ig_user_id": lead.ig_user_id,
            "source_campaign_id": str(lead.source_campaign_id) if lead.source_campaign_id else None,
            "source_campaign": names.get(str(lead.source_campaign_id)) if lead.source_campaign_id else None,
            "source_media_id": lead.source_media_id,
            "source_media_type": lead.source_media_type,
            "source_media_label": lead.source_media_label,
            "keyword": _trigger_keyword_for_campaign_comment(db, lead.source_campaign_id, lead.source_comment_id),
            "instagram_account_id": str(lead.instagram_account_id),
            "instagram_account_username": account_names.get(str(lead.instagram_account_id)) or None,
            "tags": [],
            "first_seen": lead.created_at.isoformat() if lead.created_at else None,
            "last_seen": lead.last_seen_at.isoformat() if lead.last_seen_at else None,
            "captured_at": lead.created_at.isoformat() if lead.created_at else None,
        }
        for lead in leads
    ]


@router.get("/leads/export.csv")
async def export_leads_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
    names = _campaign_names(db, {lead.source_campaign_id for lead in leads if lead.source_campaign_id})
    acc_names = _account_usernames(db, {lead.instagram_account_id for lead in leads})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["username", "ig_user_id", "source_campaign", "instagram_account", "first_seen", "last_seen"])
    for lead in leads:
        writer.writerow(
            [
                lead.ig_username or "",
                lead.ig_user_id,
                names.get(str(lead.source_campaign_id), "") if lead.source_campaign_id else "",
                acc_names.get(str(lead.instagram_account_id), ""),
                lead.created_at.isoformat() if lead.created_at else "",
                lead.last_seen_at.isoformat() if lead.last_seen_at else "",
            ]
        )
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

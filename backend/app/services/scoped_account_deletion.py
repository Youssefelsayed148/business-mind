"""Account FK deletion shared by the erasure lifecycle; no commit or HTTP."""
from copy import deepcopy

from sqlalchemy import null, or_

from app.models.audit_log import AuditLog
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.comment import Comment
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_campaign_keyword import FacebookCampaignKeyword
from app.models.facebook_comment import FacebookComment
from app.models.facebook_user_cooldown import FacebookUserCooldown
from app.models.lead import Lead
from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.user_cooldown import UserCooldown
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_campaign_recipient import WhatsappCampaignRecipient
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.services.contact_erasure import ACCOUNT_FK


def scrub_account_payload(payload, platform, channel):
    expected = {"instagram": "instagram", "facebook": "page", "whatsapp": "whatsapp_business_account"}[platform]
    if not isinstance(payload, dict) or payload.get("object") != expected or not isinstance(payload.get("entry"), list):
        return payload, False
    result = deepcopy(payload)
    retained = []
    for entry in result["entry"]:
        if not isinstance(entry, dict):
            retained.append(entry)
            continue
        if platform != "whatsapp":
            external_id = channel.ig_user_id if platform == "instagram" else channel.page_id
            if str(entry.get("id")) != external_id:
                retained.append(entry)
        else:
            # A WABA delivery can mix phone numbers. The WABA alone is not scope.
            changes = entry.get("changes")
            if not isinstance(changes, list):
                retained.append(entry)
                continue
            remaining = [change for change in changes if not (
                isinstance(change, dict) and isinstance(change.get("value"), dict)
                and isinstance(change["value"].get("metadata"), dict)
                and str(change["value"]["metadata"].get("phone_number_id")) == channel.phone_number_id)]
            if remaining:
                entry["changes"] = remaining
                retained.append(entry)
    result["entry"] = retained
    changed = result != payload
    return (result if retained else None), changed


def erase_owned_rows(db, *, platform, channel):
    """Remove children in FK order, preserving every A16 row and the account."""
    fk = ACCOUNT_FK[platform]
    scope = channel.id
    campaign_model = {"instagram": Campaign, "facebook": FacebookCampaign, "whatsapp": WhatsappCampaign}[platform]
    campaign_ids = [r[0] for r in db.query(campaign_model.id).filter(getattr(campaign_model, fk) == scope).all()]
    lead_ids = [r[0] for r in db.query(Lead.id).filter(getattr(Lead, fk) == scope, Lead.workspace_id == channel.workspace_id).all()]
    conversation_scope = [getattr(Conversation, fk) == scope, Conversation.lead_id.in_(lead_ids)]
    if platform != "whatsapp":
        conversation_campaign = Conversation.campaign_id if platform == "instagram" else Conversation.facebook_campaign_id
        conversation_scope.append(conversation_campaign.in_(campaign_ids))
    conv_ids = [r[0] for r in db.query(Conversation.id).filter(or_(*conversation_scope)).all()]
    msg_campaign_fk = {"instagram": "campaign_id", "facebook": "facebook_campaign_id", "whatsapp": "whatsapp_campaign_id"}[platform]
    message_scope = [Message.lead_id.in_(lead_ids), Message.conversation_id.in_(conv_ids), getattr(Message, msg_campaign_fk).in_(campaign_ids)]
    contact_ids, template_ids, comment_ids = [], [], []
    if platform == "whatsapp":
        contact_ids = [r[0] for r in db.query(WhatsappContact.id).filter(WhatsappContact.whatsapp_account_id == scope).all()]
        template_ids = [r[0] for r in db.query(WhatsappTemplate.id).filter(WhatsappTemplate.whatsapp_account_id == scope).all()]
        recipient_msgs = [r[0] for r in db.query(WhatsappCampaignRecipient.message_id).filter(or_(
            WhatsappCampaignRecipient.campaign_id.in_(campaign_ids), WhatsappCampaignRecipient.contact_id.in_(contact_ids))).all() if r[0]]
        message_scope.extend([Message.id.in_(recipient_msgs), Message.whatsapp_template_id.in_(template_ids)])
        db.query(WhatsappCampaignRecipient).filter(or_(WhatsappCampaignRecipient.campaign_id.in_(campaign_ids),
            WhatsappCampaignRecipient.contact_id.in_(contact_ids))).delete(synchronize_session=False)
        db.query(WhatsappConsentEvent).filter(WhatsappConsentEvent.contact_id.in_(contact_ids)).delete(synchronize_session=False)
        db.query(WhatsappContact).filter(WhatsappContact.id.in_(contact_ids)).delete(synchronize_session=False)
    else:
        comment_model = Comment if platform == "instagram" else FacebookComment
        comment_ids = [r[0] for r in db.query(comment_model.id).filter(getattr(comment_model, fk) == scope).all()]
        comment_fk = Message.comment_id if platform == "instagram" else Message.facebook_comment_id
        message_scope.append(comment_fk.in_(comment_ids))
        if platform == "instagram":
            db.query(Lead).filter(Lead.source_comment_id.in_(comment_ids)).update(
                {"source_comment_id": None}, synchronize_session=False)
    message_ids = [r[0] for r in db.query(Message.id).filter(or_(*message_scope)).all()]
    db.query(SaasOutboundMessage).filter(or_(
        (SaasOutboundMessage.platform == platform) & (SaasOutboundMessage.channel_id == scope),
        SaasOutboundMessage.message_pk.in_(message_ids))).delete(synchronize_session=False)
    db.query(SaasForwardEvent).filter(SaasForwardEvent.platform == platform, SaasForwardEvent.channel_id == scope,
                                    SaasForwardEvent.event_type != "contact.erasure").delete(synchronize_session=False)
    log_scope = [getattr(AutomationLog, fk) == scope, AutomationLog.lead_id.in_(lead_ids)]
    if platform == "instagram":
        log_scope.append(AutomationLog.campaign_id.in_(campaign_ids))
    db.query(AutomationLog).filter(or_(*log_scope)).delete(synchronize_session=False)
    db.query(Message).filter(Message.id.in_(message_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(synchronize_session=False)
    db.query(Lead).filter(Lead.id.in_(lead_ids)).delete(synchronize_session=False)
    if platform == "instagram":
        db.query(Lead).filter(Lead.source_campaign_id.in_(campaign_ids)).update(
            {"source_campaign_id": None}, synchronize_session=False)
    if platform != "whatsapp":
        keyword = CampaignKeyword if platform == "instagram" else FacebookCampaignKeyword
        cooldown = UserCooldown if platform == "instagram" else FacebookUserCooldown
        db.query(cooldown).filter(cooldown.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        db.query(keyword).filter(keyword.campaign_id.in_(campaign_ids)).delete(synchronize_session=False)
        db.query(comment_model).filter(getattr(comment_model, fk) == scope).delete(synchronize_session=False)
    db.query(campaign_model).filter(campaign_model.id.in_(campaign_ids)).delete(synchronize_session=False)
    if platform == "whatsapp":
        db.query(WhatsappTemplate).filter(WhatsappTemplate.id.in_(template_ids)).delete(synchronize_session=False)
    owned = [scope, *campaign_ids, *comment_ids, *lead_ids, *conv_ids, *message_ids, *contact_ids, *template_ids]
    # UUID equality is proof of entity scope. Never match people by email/name.
    db.query(AuditLog).filter(AuditLog.entity_id.in_(owned)).update({
        "entity_name": None, "message": "Account data erased", "metadata_": None,
    }, synchronize_session=False)
    for event in db.query(WebhookEvent).filter(WebhookEvent.provider == "meta", WebhookEvent.payload.isnot(None)).with_for_update().all():
        payload, changed = scrub_account_payload(event.payload, platform, channel)
        if changed:
            event.payload = payload if payload is not None else null()
            if payload is None:
                event.processing_status = "skipped"
    db.flush()

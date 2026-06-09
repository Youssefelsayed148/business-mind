"""
Rehearsal seed script.

Usage:
    docker compose exec backend python -m app.scripts.seed_rehearsal
    docker compose exec backend python -m app.scripts.seed_rehearsal --force   # allow in production
"""

import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.audit_log import AuditLog
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.comment import Comment
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.user import User
from app.models.workspace import Workspace
from app.roles import ROLE_ADMIN, ROLE_OPERATOR, ROLE_OWNER, ROLE_VIEWER

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REHEARSAL_TAG = "[Rehearsal]"

USERS = [
    {"email": "owner@osiris.com",    "name": "Osiris Owner",    "role": ROLE_OWNER},
    {"email": "admin2@osiris.com",   "name": "Osiris Admin",    "role": ROLE_ADMIN},
    {"email": "operator@osiris.com", "name": "Osiris Operator", "role": ROLE_OPERATOR},
    {"email": "viewer@osiris.com",   "name": "Osiris Viewer",   "role": ROLE_VIEWER},
]

IG_ACCOUNTS = [
    {"ig_user_id": "178400000000001", "ig_username": "osiris_demo_01", "display": "Osiris Demo – Fashion"},
    {"ig_user_id": "178400000000002", "ig_username": "osiris_demo_02", "display": "Osiris Demo – Travel"},
    {"ig_user_id": "178400000000003", "ig_username": "osiris_demo_03", "display": "Osiris Demo – Fitness"},
    {"ig_user_id": "178400000000004", "ig_username": "osiris_demo_04", "display": "Osiris Demo – Tech"},
    {"ig_user_id": "178400000000005", "ig_username": "osiris_demo_05", "display": "Osiris Demo – Food"},
    {"ig_user_id": "178400000000006", "ig_username": "osiris_demo_06", "display": "Osiris Demo – Beauty"},
    {"ig_user_id": "178400000000007", "ig_username": "osiris_demo_07", "display": "Osiris Demo – Education"},
    {"ig_user_id": "178400000000008", "ig_username": "osiris_demo_08", "display": "Osiris Demo – Finance"},
    {"ig_user_id": "178400000000009", "ig_username": "osiris_demo_09", "display": "Osiris Demo – Health"},
    {"ig_user_id": "178400000000010", "ig_username": "osiris_demo_10", "display": "Osiris Demo – Lifestyle"},
]

# 50 campaign definitions: (name_suffix, keywords, status, delivery_mode, message_template)
CAMPAIGN_DEFS = [
    # --- instant campaigns ---
    ("Price Check",      ["price"],              "active",   "instant",
     "Hey {{ username }}! Our current price list is ready — check it out here: {{ link }}"),
    ("Demo Request",     ["demo"],               "active",   "instant",
     "Hi {{ username }}, thanks for asking about a demo! Reply here and we'll set one up."),
    ("Special Offer",    ["offer"],              "active",   "instant",
     "{{ username }}, you caught our special offer alert! Click {{ link }} to claim yours."),
    ("Quick Guide",      ["guide"],              "active",   "instant",
     "Here's your free guide, {{ username }}: {{ link }} — let us know if you have questions!"),
    ("Prompt Reply",     ["prompt"],             "active",   "instant",
     "Thanks for the message, {{ username }}! We'll get back to you shortly."),
    ("Discount Code",    ["discount"],           "active",   "instant",
     "{{ username }}, use code DEMO20 for 20% off your first order: {{ link }}"),
    ("Get Started",      ["start"],              "active",   "instant",
     "Ready to start, {{ username }}? Head over to {{ link }} and we'll walk you through it."),
    ("More Info",        ["info"],               "active",   "instant",
     "Hi {{ username }}! Full details are at {{ link }} — feel free to DM us any questions."),
    ("Course Access",    ["course"],             "active",   "instant",
     "{{ username }}, your course link is waiting: {{ link }} — enjoy the learning!"),
    ("Book a Spot",      ["book"],               "active",   "instant",
     "{{ username }}, grab your spot here: {{ link }} before it fills up!"),

    # --- follow_prompt campaigns ---
    ("Follow to Get Price",     ["price", "pricing"],  "active",  "follow_prompt",
     "{{ username }}, follow us first and we'll send you the full price breakdown!"),
    ("Follow for Demo Access",  ["demo", "preview"],   "active",  "follow_prompt",
     "{{ username }}, follow our page to unlock the exclusive demo access link."),
    ("Follow + Offer Bundle",   ["offer", "deal"],     "active",  "follow_prompt",
     "{{ username }}, follow us to receive your personalised offer bundle today!"),
    ("Follow for Free Guide",   ["guide", "resource"], "active",  "follow_prompt",
     "{{ username }}, follow us and we'll send the full resource guide right away!"),
    ("Follow + Prompt Pack",    ["prompt"],            "active",  "follow_prompt",
     "{{ username }}, follow our account and we'll DM you the prompt pack instantly."),

    # --- paused campaigns ---
    ("Discount Drop – Paused",  ["discount"],          "paused",  "instant",
     "{{ username }}, our seasonal discount drop is coming back soon — stay tuned!"),
    ("Start Pack – Paused",     ["start", "begin"],    "paused",  "instant",
     "{{ username }}, our starter pack campaign is temporarily paused for updates."),
    ("Info Blast – Paused",     ["info"],              "paused",  "instant",
     "Hi {{ username }}, we are refreshing our info campaign. Check back soon!"),
    ("Course Bundle – Paused",  ["course"],            "paused",  "instant",
     "{{ username }}, the course bundle campaign will relaunch next week — subscribe!"),
    ("Book Drive – Paused",     ["book"],              "paused",  "follow_prompt",
     "{{ username }}, follow us — our booking drive is paused but launching again soon."),

    # --- more instant active ---
    ("Price Alert",      ["price"],              "active",   "instant",
     "{{ username }}, price alert activated! See the latest at {{ link }}."),
    ("Demo Tour",        ["demo"],               "active",   "instant",
     "{{ username }}, take a quick product tour here: {{ link }} — no signup needed."),
    ("Offer Wall",       ["offer"],              "active",   "instant",
     "{{ username }}, browse all active offers at {{ link }} — updated daily."),
    ("Guide Library",    ["guide"],              "active",   "instant",
     "{{ username }}, your guide library is at {{ link }} — enjoy every resource!"),
    ("Prompt Bank",      ["prompt"],             "active",   "instant",
     "{{ username }}, access your prompt bank at {{ link }} — 100+ prompts inside."),

    # --- archived ---
    ("Black Friday Offer",  ["offer", "discount"],  "archived", "instant",
     "{{ username }}, this campaign has ended. Thanks for participating!"),
    ("January Guide Drop",  ["guide"],              "archived", "instant",
     "{{ username }}, our January guide drop is complete. Watch for the next one!"),
    ("Q1 Course Launch",    ["course"],             "archived", "instant",
     "{{ username }}, Q1 enrollment is closed. Join the waitlist at {{ link }}."),
    ("Early Book Access",   ["book"],               "archived", "follow_prompt",
     "{{ username }}, early access booking has closed. Follow for next round info."),
    ("Beta Start Pack",     ["start"],              "archived", "instant",
     "{{ username }}, the beta program is full. Thanks for your interest!"),

    # --- more variety for 50 total ---
    ("Pricing Table",       ["price"],              "active",   "instant",
     "{{ username }}, full pricing table: {{ link }} — no hidden fees."),
    ("Demo Sandbox",        ["demo"],               "active",   "instant",
     "{{ username }}, try our sandbox demo at {{ link }} — no credit card needed."),
    ("Flash Offer",         ["offer"],              "paused",   "instant",
     "{{ username }}, our flash offer is temporarily paused — check back Friday!"),
    ("Beginner Guide",      ["guide", "start"],     "active",   "instant",
     "{{ username }}, perfect beginner guide at {{ link }} — step by step!"),
    ("Prompt Templates",    ["prompt"],             "active",   "follow_prompt",
     "{{ username }}, follow us and we'll send you 50 ready-to-use prompt templates!"),
    ("VIP Discount",        ["discount"],           "active",   "instant",
     "{{ username }}, VIP discount unlocked! Use code VIP30 at {{ link }}."),
    ("Kickstart Pack",      ["start"],              "active",   "instant",
     "{{ username }}, your kickstart pack is ready at {{ link }} — let's go!"),
    ("Info Hub",            ["info"],               "active",   "instant",
     "{{ username }}, find everything at our info hub: {{ link }}."),
    ("Masterclass Access",  ["course"],             "active",   "follow_prompt",
     "{{ username }}, follow us and we'll send you your masterclass access link today!"),
    ("Reserve Your Spot",   ["book"],               "active",   "instant",
     "{{ username }}, reserve your spot now at {{ link }} — limited availability!"),

    # --- more archived / paused ---
    ("Summer Price Drop",   ["price"],              "archived", "instant",
     "{{ username }}, summer campaign ended. More deals coming this fall!"),
    ("Exclusive Demo",      ["demo"],               "paused",   "follow_prompt",
     "{{ username }}, follow us to get notified when exclusive demo spots reopen."),
    ("Loyalty Offer",       ["offer"],              "active",   "instant",
     "{{ username }}, loyalty offer applied! Details at {{ link }}."),
    ("Advanced Guide",      ["guide"],              "active",   "instant",
     "{{ username }}, advanced guide series at {{ link }} — go deep!"),
    ("AI Prompt Kit",       ["prompt"],             "active",   "instant",
     "{{ username }}, your AI prompt kit: {{ link }} — 200+ prompts included."),
    ("Refer & Discount",    ["discount"],           "active",   "instant",
     "{{ username }}, share your referral and get 15% off. Details: {{ link }}."),
    ("Onboarding Start",    ["start"],              "active",   "follow_prompt",
     "{{ username }}, follow us to kick off your onboarding journey with us!"),
    ("Product Info Pack",   ["info"],               "paused",   "instant",
     "{{ username }}, our product info pack campaign is being refreshed. Coming soon!"),
    ("Course Waitlist",     ["course"],             "archived", "instant",
     "{{ username }}, the course is fully enrolled. Join the waitlist: {{ link }}."),
    ("Group Booking",       ["book"],               "active",   "instant",
     "{{ username }}, group booking available at {{ link }} — save 25%!"),
]

FOLLOW_PROMPT_DATA = [
    {
        "title": "Follow Osiris Demo to Continue",
        "description": "Follow our page and we'll send you the exclusive content you asked about.",
        "profile_url": "https://www.instagram.com/osiris_demo_01/",
    },
    {
        "title": "Get Your Exclusive Access",
        "description": "Follow us first — we'll DM you the link the moment you do.",
        "profile_url": "https://www.instagram.com/osiris_demo_02/",
    },
    {
        "title": "Unlock Your Free Resource",
        "description": "One follow and your free resource is on its way — no spam, ever.",
        "profile_url": "https://www.instagram.com/osiris_demo_03/",
    },
]

SAMPLE_COMMENTERS = [
    ("demo_user_001", "lina_fashion"),
    ("demo_user_002", "mark_travels"),
    ("demo_user_003", "sara_fit"),
    ("demo_user_004", "joe_tech"),
    ("demo_user_005", "nina_eats"),
    ("demo_user_006", "alex_beauty"),
    ("demo_user_007", "tom_learns"),
    ("demo_user_008", "rania_finance"),
    ("demo_user_009", "hassan_health"),
    ("demo_user_010", "layla_lifestyle"),
    ("demo_user_011", "chris_demo"),
    ("demo_user_012", "diana_info"),
    ("demo_user_013", "sam_guide"),
    ("demo_user_014", "pat_course"),
    ("demo_user_015", "robin_book"),
]

MEDIA_IDS = [
    "media_rehearsal_001",
    "media_rehearsal_002",
    "media_rehearsal_003",
    "media_rehearsal_004",
    "media_rehearsal_005",
]

SPECIFIC_TARGETS = [
    {
        "name": "May Discount Reel",
        "media_id": "media_rehearsal_001",
        "url": "https://www.instagram.com/reel/C7MayDiscount001/",
        "type": "reel",
        "keyword": "discount",
    },
    {
        "name": "Quick Guide Post",
        "media_id": "media_rehearsal_002",
        "url": "https://www.instagram.com/p/C7QuickGuide002/",
        "type": "post",
        "keyword": "guide",
    },
    {
        "name": "Course Launch Reel",
        "media_id": "media_rehearsal_003",
        "url": "https://www.instagram.com/reel/C7CourseLaunch003/",
        "type": "reel",
        "keyword": "course",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def ago(hours: int = 0, days: int = 0, minutes: int = 0) -> datetime:
    return now_utc() - timedelta(hours=hours, days=days, minutes=minutes)


def _upsert_user(db, email: str, name: str, role: str, password: str = "password") -> tuple[User, bool]:
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return existing, False
    user = User(
        id=uuid.uuid4(),
        email=email,
        name=name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user, True


def _upsert_workspace(db) -> tuple[Workspace, bool]:
    ws = db.query(Workspace).filter(Workspace.slug == "default").first()
    if ws:
        return ws, False
    ws = Workspace(id=uuid.uuid4(), name="Default Workspace", slug="default")
    db.add(ws)
    db.flush()
    return ws, True


def _upsert_ig_account(db, workspace_id: uuid.UUID, ig_user_id: str, ig_username: str) -> tuple[InstagramAccount, bool]:
    existing = db.query(InstagramAccount).filter(InstagramAccount.ig_user_id == ig_user_id).first()
    if existing:
        existing.ig_username = ig_username
        existing.status = "connected"
        return existing, False
    acc = InstagramAccount(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        ig_user_id=ig_user_id,
        ig_username=ig_username,
        status="connected",
    )
    db.add(acc)
    db.flush()
    return acc, True


def _find_campaign(db, workspace_id: uuid.UUID, name: str) -> Campaign | None:
    return (
        db.query(Campaign)
        .filter(Campaign.workspace_id == workspace_id, Campaign.name == name)
        .first()
    )


def _upsert_campaign(db, workspace_id: uuid.UUID, account_id: uuid.UUID, defn: tuple, media_id: str, target: dict | None) -> tuple[Campaign, bool]:
    name_suffix, keywords, status, delivery_mode, message_template = defn
    full_name = f"{REHEARSAL_TAG} {name_suffix}"

    fp_data = {}
    if delivery_mode == "follow_prompt":
        fp = random.choice(FOLLOW_PROMPT_DATA)
        fp_data = {
            "follow_prompt_title": fp["title"],
            "follow_prompt_description": fp["description"],
            "follow_prompt_profile_url": fp["profile_url"],
        }

    existing = _find_campaign(db, workspace_id, full_name)
    target_scope = "specific_media" if target else "any_media"
    target_media_url = target["url"] if target else None
    target_media_id = target["media_id"] if target else None
    target_media_type = target["type"] if target else "unknown"
    target_media_label = target["name"] if target else None
    target_media_shortcode = target_media_url.rstrip("/").split("/")[-1] if target_media_url else None
    if existing:
        existing.status = status
        existing.delivery_mode = delivery_mode
        existing.message_template = message_template
        existing.instagram_account_id = account_id
        existing.media_id = target_media_id
        existing.media_url = target_media_url
        existing.target_scope = target_scope
        existing.target_media_url = target_media_url
        existing.target_media_shortcode = target_media_shortcode
        existing.target_media_id = target_media_id
        existing.target_media_type = target_media_type
        existing.target_media_label = target_media_label
        if not existing.created_at:
            existing.created_at = ago(days=random.randint(1, 45), hours=random.randint(0, 23))
        for k, v in fp_data.items():
            setattr(existing, k, v)
        db.flush()
        return existing, False

    campaign = Campaign(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        instagram_account_id=account_id,
        name=full_name,
        description=f"Rehearsal campaign: {name_suffix}. Auto-generated for demo purposes.",
        media_id=target_media_id,
        media_url=target_media_url,
        target_scope=target_scope,
        target_media_url=target_media_url,
        target_media_shortcode=target_media_shortcode,
        target_media_id=target_media_id,
        target_media_type=target_media_type,
        target_media_label=target_media_label,
        match_type="contains",
        message_template=message_template,
        link_url="https://example.com/demo",
        cooldown_hours=24,
        status=status,
        delivery_mode=delivery_mode,
        total_triggers=random.randint(5, 200),
        successful_sends=random.randint(3, 150),
        failed_sends=random.randint(0, 10),
        created_at=ago(days=random.randint(1, 45), hours=random.randint(0, 23)),
        **fp_data,
    )
    db.add(campaign)
    db.flush()

    for kw in keywords:
        existing_kw = (
            db.query(CampaignKeyword)
            .filter(
                CampaignKeyword.campaign_id == campaign.id,
                CampaignKeyword.normalized_keyword == kw.lower().strip(),
            )
            .first()
        )
        if not existing_kw:
            db.add(CampaignKeyword(
                id=uuid.uuid4(),
                campaign_id=campaign.id,
                normalized_keyword=kw.lower().strip(),
            ))
    db.flush()
    return campaign, True


def _upsert_comment(db, account_id: uuid.UUID, comment_id: str, ig_user_id: str, ig_username: str, message: str) -> tuple[Comment, bool]:
    existing = db.query(Comment).filter(Comment.comment_id == comment_id).first()
    if existing:
        return existing, False
    c = Comment(
        id=uuid.uuid4(),
        instagram_account_id=account_id,
        comment_id=comment_id,
        ig_user_id=ig_user_id,
        ig_username=ig_username,
        message=message,
        normalized_text=message.lower().strip(),
        received_at=ago(hours=random.randint(1, 72)),
    )
    db.add(c)
    db.flush()
    return c, True


def _upsert_lead(db, workspace_id: uuid.UUID, account_id: uuid.UUID, ig_user_id: str, ig_username: str, campaign: Campaign, comment: Comment) -> tuple[Lead, bool]:
    existing = (
        db.query(Lead)
        .filter(
            Lead.workspace_id == workspace_id,
            Lead.instagram_account_id == account_id,
            Lead.ig_user_id == ig_user_id,
        )
        .first()
    )
    if existing:
        return existing, False
    lead = Lead(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        instagram_account_id=account_id,
        ig_user_id=ig_user_id,
        ig_username=ig_username,
        last_seen_at=ago(hours=random.randint(1, 48)),
        source_campaign_id=campaign.id,
        source_comment_id=comment.id,
        source_media_id=campaign.target_media_id,
        source_media_type=campaign.target_media_type,
        source_media_label=campaign.target_media_label,
        status="new",
    )
    db.add(lead)
    db.flush()
    return lead, True


def _upsert_message(
    db,
    campaign: Campaign,
    lead: Lead,
    comment: Comment,
    message_type: str,
    status: str,
    rendered_body: str,
    provider_message_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    retryable: bool = False,
    retry_count: int = 0,
) -> tuple[Message, bool]:
    existing = (
        db.query(Message)
        .filter(
            Message.campaign_id == campaign.id,
            Message.comment_id == comment.id,
            Message.message_type == message_type,
        )
        .first()
    )
    if existing:
        return existing, False
    msg = Message(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        lead_id=lead.id,
        comment_id=comment.id,
        source_media_id=campaign.target_media_id,
        source_media_type=campaign.target_media_type,
        source_media_label=campaign.target_media_label,
        rendered_body=rendered_body,
        content=rendered_body,
        message_type=message_type,
        status=status,
        provider_message_id=provider_message_id,
        error_code=error_code,
        error_message=error_message,
        retryable=retryable,
        retry_count=retry_count,
    )
    db.add(msg)
    db.flush()
    return msg, True


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

def seed_users(db) -> dict[str, User]:
    created = updated = 0
    users: dict[str, User] = {}
    for spec in USERS:
        user, was_new = _upsert_user(db, spec["email"], spec["name"], spec["role"])
        users[spec["email"]] = user
        if was_new:
            created += 1
        else:
            updated += 1
    print(f"  Users:              created={created}  skipped={updated}")
    return users


def seed_ig_accounts(db, workspace_id: uuid.UUID) -> list[InstagramAccount]:
    created = updated = 0
    accounts: list[InstagramAccount] = []
    for spec in IG_ACCOUNTS:
        acc, was_new = _upsert_ig_account(db, workspace_id, spec["ig_user_id"], spec["ig_username"])
        accounts.append(acc)
        if was_new:
            created += 1
        else:
            updated += 1
    print(f"  Instagram accounts: created={created}  updated={updated}")
    return accounts


def seed_campaigns(db, workspace_id: uuid.UUID, accounts: list[InstagramAccount]) -> list[Campaign]:
    created = updated = 0
    campaigns: list[Campaign] = []
    random.seed(42)
    for i, defn in enumerate(CAMPAIGN_DEFS):
        account = accounts[i % len(accounts)]
        media_id = MEDIA_IDS[i % len(MEDIA_IDS)]
        target = SPECIFIC_TARGETS[i % len(SPECIFIC_TARGETS)] if i % 4 == 0 else None
        campaign, was_new = _upsert_campaign(db, workspace_id, account.id, defn, media_id, target)
        campaigns.append(campaign)
        if was_new:
            created += 1
        else:
            updated += 1
    print(f"  Campaigns:          created={created}  updated={updated}")
    return campaigns


def seed_sample_data(
    db,
    workspace_id: uuid.UUID,
    accounts: list[InstagramAccount],
    campaigns: list[Campaign],
    owner: User,
) -> None:
    comments_created = leads_created = messages_created = auto_logs = audit_logs = 0

    active_campaigns = [c for c in campaigns if c.status == "active"]
    random.seed(99)

    for i, (ig_user_id, ig_username) in enumerate(SAMPLE_COMMENTERS):
        campaign = active_campaigns[i % len(active_campaigns)]
        account = db.query(InstagramAccount).filter(
            InstagramAccount.id == campaign.instagram_account_id
        ).first()
        if not account:
            continue

        # Pick a keyword from the campaign's keywords
        kw_records = (
            db.query(CampaignKeyword)
            .filter(CampaignKeyword.campaign_id == campaign.id)
            .all()
        )
        keyword = kw_records[0].normalized_keyword if kw_records else "demo"
        comment_text = f"Hey! I want to know more about {keyword} please"

        comment_id = f"demo_comment_{i+1:04d}"
        comment, c_new = _upsert_comment(
            db, account.id, comment_id, ig_user_id, ig_username, comment_text
        )
        if c_new:
            comments_created += 1

        lead, l_new = _upsert_lead(db, workspace_id, account.id, ig_user_id, ig_username, campaign, comment)
        if l_new:
            leads_created += 1

        rendered = campaign.message_template.replace("{{ username }}", ig_username).replace("{{ link }}", "https://example.com/demo")

        # Vary message statuses to make the table interesting
        if i % 7 == 0:
            status = "failed"
            error_code = "190"
            error_msg = "Invalid OAuth access token."
            retryable = False
            retry_count = 3
            provider_id = None
        elif i % 5 == 0:
            status = "failed"
            error_code = "100"
            error_msg = "Unsupported post request."
            retryable = True
            retry_count = 1
            provider_id = None
        else:
            status = "sent"
            error_code = None
            error_msg = None
            retryable = False
            retry_count = 0
            provider_id = f"mock_mid_{uuid.uuid4().hex[:12]}"

        if campaign.delivery_mode == "follow_prompt":
            # First create the follow_prompt message
            fp_rendered = f"Follow us, {ig_username}! Tap the button below to continue."
            _, m_new = _upsert_message(
                db, campaign, lead, comment, "follow_prompt", status,
                fp_rendered, provider_id, error_code, error_msg, retryable, retry_count
            )
            if m_new:
                messages_created += 1

        _, m_new = _upsert_message(
            db, campaign, lead, comment, "final_delivery", status,
            rendered, provider_id, error_code, error_msg, retryable, retry_count
        )
        if m_new:
            messages_created += 1

        # AutomationLog entry
        db.add(AutomationLog(
            id=uuid.uuid4(),
            campaign_id=campaign.id,
            lead_id=lead.id,
            instagram_account_id=account.id,
            action="message_queued" if status == "sent" else "message_failed",
            details={
                "keyword": keyword,
                "comment_id": comment_id,
                "ig_username": ig_username,
                "status": status,
                "trigger": keyword,
            },
        ))
        auto_logs += 1

    # AuditLog entries for rehearsal actor activity
    audit_actions = [
        ("campaign_activated",   "campaign", "info",    "Activated rehearsal campaign for testing."),
        ("campaign_paused",      "campaign", "info",    "Paused campaign for rehearsal maintenance window."),
        ("campaign_archived",    "campaign", "warning", "Archived old rehearsal campaign after test cycle."),
        ("campaign_unarchived",  "campaign", "info",    "Restored archived campaign for re-test."),
        ("user_login_success",   None,       "info",    "Owner logged in successfully during rehearsal."),
        ("campaign_created",     "campaign", "info",    "Created new rehearsal campaign via seed script."),
    ]
    for action, entity_type, severity, message in audit_actions:
        db.add(AuditLog(
            id=uuid.uuid4(),
            actor_user_id=owner.id,
            actor_email=owner.email,
            action=action,
            entity_type=entity_type,
            severity=severity,
            message=message,
            metadata_={"source": "seed_rehearsal", "rehearsal": True},
        ))
        audit_logs += 1

    for campaign in campaigns[:10]:
        existing_created_log = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "campaign_created",
                AuditLog.entity_type == "campaign",
                AuditLog.entity_id == campaign.id,
            )
            .first()
        )
        if not existing_created_log:
            db.add(AuditLog(
                id=uuid.uuid4(),
                actor_user_id=owner.id,
                actor_email=owner.email,
                action="campaign_created",
                entity_type="campaign",
                entity_id=campaign.id,
                entity_name=campaign.name,
                severity="info",
                message=f"{owner.email} created campaign {campaign.name}",
                metadata_={"source": "seed_rehearsal", "rehearsal": True, "created_by": owner.email},
            ))
            audit_logs += 1

    db.flush()
    print(f"  Comments:           created={comments_created}")
    print(f"  Leads:              created={leads_created}")
    print(f"  Messages:           created={messages_created}")
    print(f"  Automation logs:    created={auto_logs}")
    print(f"  Audit logs:         created={audit_logs}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed rehearsal data for ManyOsirisChat")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow seeding even when APP_ENV=production",
    )
    args = parser.parse_args()

    env = settings.APP_ENV.lower()
    if env == "production" and not args.force:
        print(
            "ERROR: Refusing to seed in production mode.\n"
            "       Pass --force to override (use with caution).",
            file=sys.stderr,
        )
        sys.exit(1)

    if env == "production":
        print("WARNING: Running seed in production mode (--force was passed).")

    print(f"Seeding rehearsal data (APP_ENV={env}) …")
    db = SessionLocal()
    try:
        workspace, ws_new = _upsert_workspace(db)
        print(f"  Workspace:          {'created' if ws_new else 'exists'}  ({workspace.slug})")

        users = seed_users(db)
        owner = users["owner@osiris.com"]

        accounts = seed_ig_accounts(db, workspace.id)
        campaigns = seed_campaigns(db, workspace.id, accounts)
        seed_sample_data(db, workspace.id, accounts, campaigns, owner)

        db.commit()
        print("\nRehearsal seed complete.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

import logging
import uuid

from openai import OpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.campaign import Campaign
from app.models.instagram_account import InstagramAccount
from app.models.message import Message

logger = logging.getLogger(__name__)

# Non-overridable safety instructions per vertical. These are appended
# regardless of what a client fills into their business profile, so a
# misconfigured or sparse profile can't accidentally leave out a hard
# safety boundary for a sensitive vertical.
_VERTICAL_SAFETY_INSTRUCTIONS = {
    "clinical": (
        "You must never provide medical advice, diagnoses, treatment "
        "recommendations, or medication guidance, even if asked directly. "
        "For any medical question, tell the user you can't advise on that "
        "and offer to help them book an appointment or connect with staff."
    ),
    "real_estate": (
        "You must never quote a final price, commit to availability, or "
        "confirm a legal/contractual term as final — always frame pricing "
        "and availability as needing confirmation from the team."
    ),
    "restaurant": (
        "Be careful with allergen and ingredient questions: if you are not "
        "certain the business profile covers the specific allergen or "
        "ingredient asked about, say you're not sure and offer to connect "
        "the user with staff rather than guessing."
    ),
    "general": "",
}

_HANDOFF_INSTRUCTION = (
    "If the user asks to speak to a human, seems frustrated, or asks "
    "something clearly outside what you've been told about this business, "
    "say you'll get a team member to help and do not attempt to answer."
)


class AIReplyResult:
    def __init__(self, success: bool, text: str | None = None, error: str | None = None):
        self.success = success
        self.text = text
        self.error = error


def build_system_prompt(account: InstagramAccount, campaign: Campaign) -> str:
    vertical = account.business_vertical or "general"
    safety = _VERTICAL_SAFETY_INSTRUCTIONS.get(vertical, "")

    parts = [
        f"You are a helpful assistant messaging on behalf of an Instagram business account (vertical: {vertical}).",
        f"Business profile:\n{account.ai_business_profile.strip()}" if account.ai_business_profile else "No business profile has been configured yet — keep responses brief and generic.",
    ]
    if account.ai_tone_instructions:
        parts.append(f"Tone/style: {account.ai_tone_instructions.strip()}")
    parts.append(f"This conversation started from the campaign: {campaign.name}.")
    if safety:
        parts.append(safety)
    parts.append(_HANDOFF_INSTRUCTION)
    parts.append("Keep replies short and conversational, suitable for an Instagram DM.")

    return "\n\n".join(p for p in parts if p)


def build_conversation_history(db: Session, conversation_id: uuid.UUID, max_turns: int) -> list[dict]:
    """Return the last `max_turns` messages for this conversation as
    OpenAI-style chat messages, oldest first."""
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(max_turns)
        .all()
    )
    rows.reverse()

    history = []
    for row in rows:
        role = "user" if row.direction == "inbound" else "assistant"
        content = row.rendered_body or row.content or ""
        if content:
            history.append({"role": role, "content": content})
    return history


def generate_reply(
    db: Session,
    account: InstagramAccount,
    campaign: Campaign,
    conversation_id: uuid.UUID,
) -> AIReplyResult:
    if not settings.AI_ENABLED_GLOBAL:
        return AIReplyResult(success=False, error="ai_disabled_globally")
    if not settings.OPENAI_API_KEY:
        return AIReplyResult(success=False, error="no_api_key_configured")

    system_prompt = build_system_prompt(account, campaign)
    history = build_conversation_history(db, conversation_id, settings.AI_MAX_CONTEXT_TURNS)

    messages = [{"role": "system", "content": system_prompt}] + history

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.AI_REQUEST_TIMEOUT_SECONDS)
        response = client.chat.completions.create(
            model=settings.AI_MODEL_NAME,
            messages=messages,
            max_tokens=300,
        )
    except Exception as exc:
        # Fail closed: any error here means no reply gets sent, not a retry
        # storm. Caller is responsible for logging/handoff on failure.
        logger.warning("AI model call failed", extra={"conversation_id": str(conversation_id), "error": str(exc)})
        return AIReplyResult(success=False, error=str(exc))

    text = None
    if response.choices:
        text = (response.choices[0].message.content or "").strip()

    if not text:
        return AIReplyResult(success=False, error="empty_response")

    return AIReplyResult(success=True, text=text)

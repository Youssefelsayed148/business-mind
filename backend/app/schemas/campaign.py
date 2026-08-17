from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from urllib.parse import urlparse


DeliveryMode = Literal["instant", "follow_prompt"]
TargetScope = Literal["any_media", "specific_media"]
TargetMediaType = Literal["post", "reel", "story", "unknown"]


def extract_instagram_shortcode(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
        return parts[1]
    return None


def _validate_instagram_media_url(value: str | None) -> str | None:
    if not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a valid Instagram post or reel URL.")
    host = parsed.netloc.lower()
    if not (host == "instagram.com" or host.endswith(".instagram.com")):
        raise ValueError("Enter a valid Instagram post or reel URL.")
    if not extract_instagram_shortcode(value):
        raise ValueError("Enter a valid Instagram post or reel URL.")
    return value


def _validate_follow_prompt_url(value: str | None) -> str | None:
    if value is None:
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("follow_prompt_profile_url must be a valid URL")
    return value


class CampaignKeywordCreate(BaseModel):
    keyword: str = Field(..., min_length=1)


class CampaignKeywordResponse(BaseModel):
    id: UUID
    campaign_id: UUID
    normalized_keyword: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignCreate(BaseModel):
    instagram_account_id: UUID
    name: str = Field(..., min_length=1)
    description: str | None = None
    media_id: str | None = Field(default=None, min_length=1)
    media_url: str | None = None
    target_scope: TargetScope = "any_media"
    target_media_url: str | None = None
    target_media_shortcode: str | None = None
    target_media_id: str | None = None
    target_media_type: TargetMediaType = "unknown"
    target_media_label: str | None = None
    match_type: Literal["contains", "exact", "starts_with"] = "contains"
    message_template: str = Field(..., min_length=1)
    link_url: str | None = None
    cooldown_hours: int = Field(default=168, ge=0)
    status: Literal["draft", "active", "paused"] = "draft"
    keywords: list[str] = Field(default_factory=list)
    delivery_mode: DeliveryMode = "instant"
    follow_prompt_title: str | None = None
    follow_prompt_description: str | None = None
    follow_prompt_profile_url: str | None = None
    comment_reply_enabled: bool = False
    comment_reply_text: str | None = None

    @field_validator("message_template")
    @classmethod
    def validate_message_template_length(cls, v: str) -> str:
        if len(v) > 1000:
            raise ValueError("message_template must not exceed 1000 characters")
        return v

    @field_validator("follow_prompt_profile_url")
    @classmethod
    def validate_follow_prompt_profile_url(cls, v: str | None) -> str | None:
        return _validate_follow_prompt_url(v)

    @field_validator("target_media_url")
    @classmethod
    def validate_target_media_url(cls, v: str | None) -> str | None:
        return _validate_instagram_media_url(v)

    @model_validator(mode="after")
    def validate_follow_prompt_fields(self):
        if self.target_scope == "specific_media":
            if not self.target_media_id and self.media_id:
                self.target_media_id = self.media_id
            # target_media_id must be Instagram's numeric media id (from the post
            # picker / GET /me/media). A shortcode parsed from a permalink is a
            # different identifier space and can never match the webhook's
            # media_id, which would leave the campaign silently non-firing.
            if not self.target_media_id or not str(self.target_media_id).strip():
                raise ValueError(
                    "Select a post or reel for this campaign. "
                    "A specific-post campaign needs a post chosen from your connected account."
                )
            if self.target_media_url:
                self.target_media_shortcode = extract_instagram_shortcode(self.target_media_url)
        else:
            self.target_media_url = None
            self.target_media_shortcode = None
            self.target_media_id = None
            self.target_media_label = None
            self.target_media_type = "unknown"
        self.media_url = self.target_media_url or self.media_url
        self.media_id = self.target_media_id or self.media_id
        if self.delivery_mode == "follow_prompt":
            if not self.follow_prompt_title or not self.follow_prompt_title.strip():
                raise ValueError("follow_prompt_title is required for follow_prompt delivery")
            if not self.follow_prompt_description or not self.follow_prompt_description.strip():
                raise ValueError("follow_prompt_description is required for follow_prompt delivery")
            if not self.follow_prompt_profile_url or not self.follow_prompt_profile_url.strip():
                raise ValueError("follow_prompt_profile_url is required for follow_prompt delivery")
        return self


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    media_id: str | None = Field(default=None, min_length=1)
    media_url: str | None = None
    target_scope: TargetScope | None = None
    target_media_url: str | None = None
    target_media_shortcode: str | None = None
    target_media_id: str | None = None
    target_media_type: TargetMediaType | None = None
    target_media_label: str | None = None
    match_type: Literal["contains", "exact", "starts_with"] | None = None
    message_template: str | None = Field(default=None, min_length=1)
    link_url: str | None = None
    cooldown_hours: int | None = Field(default=None, ge=0)
    status: Literal["draft", "active", "paused"] | None = None
    delivery_mode: DeliveryMode | None = None
    follow_prompt_title: str | None = None
    follow_prompt_description: str | None = None
    follow_prompt_profile_url: str | None = None
    comment_reply_enabled: bool | None = None
    comment_reply_text: str | None = None

    @field_validator("message_template")
    @classmethod
    def validate_message_template_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("message_template must not exceed 1000 characters")
        return v

    @field_validator("follow_prompt_profile_url")
    @classmethod
    def validate_follow_prompt_profile_url(cls, v: str | None) -> str | None:
        return _validate_follow_prompt_url(v)

    @field_validator("target_media_url")
    @classmethod
    def validate_target_media_url(cls, v: str | None) -> str | None:
        return _validate_instagram_media_url(v)

    @model_validator(mode="after")
    def derive_target_shortcode(self):
        if self.target_media_url:
            self.target_media_shortcode = extract_instagram_shortcode(self.target_media_url)
        if self.target_media_id and self.media_id is None:
            self.media_id = self.target_media_id
        if self.target_media_url and self.media_url is None:
            self.media_url = self.target_media_url
        # Switching an existing campaign to specific_media requires a real
        # numeric media id, otherwise the campaign would never match a webhook.
        if self.target_scope == "specific_media":
            if not self.target_media_id or not str(self.target_media_id).strip():
                raise ValueError(
                    "Select a post or reel for this campaign. "
                    "A specific-post campaign needs a post chosen from your connected account."
                )
        elif self.target_scope == "any_media":
            self.target_media_url = None
            self.target_media_shortcode = None
            self.target_media_id = None
            self.target_media_label = None
        return self


class CampaignResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    instagram_account_id: UUID
    name: str
    description: str | None
    media_id: str | None
    media_url: str | None
    target_scope: str = "any_media"
    target_media_url: str | None = None
    target_media_shortcode: str | None = None
    target_media_id: str | None = None
    target_media_type: str = "unknown"
    target_media_label: str | None = None
    match_type: str
    message_template: str
    link_url: str | None
    cooldown_hours: int
    status: str
    delivery_mode: str = "instant"
    follow_prompt_title: str | None = None
    follow_prompt_description: str | None = None
    follow_prompt_profile_url: str | None = None
    comment_reply_enabled: bool = False
    comment_reply_text: str | None = None
    total_triggers: int = 0
    successful_sends: int = 0
    failed_sends: int = 0
    created_at: datetime
    updated_at: datetime
    keywords: list[CampaignKeywordResponse] = []

    model_config = {"from_attributes": True}


class CampaignSimulateRequest(BaseModel):
    comment_text: str = Field(..., min_length=1)
    username: str = Field(default="there")


class CampaignSimulateResponse(BaseModel):
    matched: bool
    matched_keyword: str | None
    rendered_message: str | None

from pydantic import BaseModel, Field


class SaasDelegationUpdate(BaseModel):
    """Partial update; only fields the caller sends are applied. `secret` is
    write-only and is never echoed back."""

    saas_delegation_enabled: bool | None = None
    saas_connection_id: str | None = Field(default=None, max_length=64)
    saas_base_url: str | None = Field(default=None, max_length=512)
    secret: str | None = Field(default=None, max_length=256, repr=False)

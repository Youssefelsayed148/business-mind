"""Add leads.facebook_psid so Facebook comment-identity and messaging-identity
can be stored separately

Facebook uses two distinct ID namespaces for the same human against the same
Page:

- A Page-feed comment webhook's `value.from.id` is an app-scoped ID (ASID).
- A Messenger webhook's `messaging[].sender.id`, and the Send API's
  `recipient.id`, are page-scoped IDs (PSID).

They are not interchangeable. Instagram does not have this problem (its
comment `from.id` and the IGSID are the same value), which is why the
Instagram-derived code path stored one id in `leads.ig_user_id` and used it
for both purposes -- correct for Instagram, wrong for Facebook.

Before this migration, a Facebook campaign lead was created from a comment
(so `ig_user_id` held the ASID) and then looked up on an inbound Messenger
message by that same column (so the lookup compared an ASID against a PSID
and never matched). The user who commented, received the private reply and
replied to it was therefore never matched to their own lead.

`facebook_psid` stores the messaging identity separately. It is populated
from the private reply Send API response's `recipient_id` field for campaign
leads, and at creation time for cold-DM leads (whose originating event is a
Messenger event, so `sender.id` is already the PSID).

Nullable with no backfill: existing Facebook campaign leads have no known
PSID and cannot have one derived retroactively -- they acquire it the next
time a private reply is sent to them. Instagram and WhatsApp leads never use
this column.

Revision ID: 0014_facebook_psid
Revises: 0013_facebook_pages
Create Date: 2026-09-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_facebook_psid"
down_revision = "0013_facebook_pages"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_leads_facebook_psid"


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _index_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    # 0001_initial.py builds tables via Base.metadata.create_all() against the
    # current models, so on a freshly-created DB the column and its index
    # already exist by the time this runs; on an incrementally-migrated DB
    # (every real deployment) they do not. Same guard style as 0011-0013.
    if "facebook_psid" not in _columns("leads"):
        op.add_column("leads", sa.Column("facebook_psid", sa.String(255), nullable=True))

    if _INDEX_NAME not in _index_names("leads"):
        op.create_index(_INDEX_NAME, "leads", ["facebook_psid"])


def downgrade() -> None:
    if _INDEX_NAME in _index_names("leads"):
        op.drop_index(_INDEX_NAME, table_name="leads")

    if "facebook_psid" in _columns("leads"):
        op.drop_column("leads", "facebook_psid")

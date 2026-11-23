"""Close the NULL-campaign gap in conversation uniqueness

`uq_conversation_lead_campaign (lead_id, campaign_id)` and
`uq_conversation_lead_facebook_campaign (lead_id, facebook_campaign_id)` are
plain unique constraints, and Postgres treats NULL as distinct from every
other NULL in one. So neither constrains anything when its campaign column is
NULL -- which is the case for:

- every WhatsApp conversation (no campaign concept at all),
- every Facebook cold-DM conversation,
- every Instagram cold-DM conversation.

`get_or_create_conversation` was read-then-insert with no lock, so two workers
handling two near-simultaneous inbound messages from the same person could
both miss the row and both insert, producing two conversations for one lead:
split history, halved AI context, and a doubled effective turn limit. Before
Phase 2 this was a rare edge case; for WhatsApp it is the only shape there is.

This adds a partial unique index covering exactly the gap -- one cold-DM-style
conversation per lead:

    UNIQUE (lead_id) WHERE campaign_id IS NULL AND facebook_campaign_id IS NULL

`lead_id` alone is sufficient without `platform` because a Lead belongs to
exactly one platform (enforced by ck_leads_platform_account_fk), so
(lead_id, platform) would be redundant -- and including platform would
actually weaken the index by allowing one row per platform for a lead that
can only ever have one.

Campaign-backed conversations are untouched: the index's WHERE clause excludes
every row with a campaign set, so Instagram's existing campaign conversation
creation keeps behaving exactly as it does today, still governed by
uq_conversation_lead_campaign.

Deduplication before creating the index: any pre-existing duplicate
NULL-campaign conversations for one lead would make CREATE UNIQUE INDEX fail.
Duplicates are merged onto the oldest row rather than deleted, so no message
history is lost. The survivor takes:

- every duplicate's messages (repointed),
- the summed turn_count -- those turns were really consumed, so the operator's
  ai_handoff_after_turns cap must still account for them. A merged total above
  the cap therefore hands off on the next message, which is the intended
  conservative outcome: capping instead would hand out unsupervised AI turns
  the operator never authorised, and the handoff is visible
  (handoff_reason='turn_limit') rather than silent,
- the latest last_message_at,
- the most restrictive status in the group (closed > handed_off > bot_active),
  with the handoff_reason of the most recently active fork that had one.
  Taking the most restrictive status is the safe direction: a permissive merge
  would resume the bot on a thread a human had deliberately taken over.

Revision ID: 0015_conv_cold_dm_uniq
Revises: 0014_facebook_psid
Create Date: 2026-09-06 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_conv_cold_dm_uniq"
down_revision = "0014_facebook_psid"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_conversation_lead_cold_dm"


def _index_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    # Merge any duplicates that already exist, keeping the oldest conversation
    # per lead. Ordering by (created_at, id) makes the choice deterministic
    # even when created_at ties.
    op.execute(
        """
        CREATE TEMP TABLE _conv_dupes AS
        SELECT id AS dupe_id,
               FIRST_VALUE(id) OVER (
                   PARTITION BY lead_id ORDER BY created_at, id
               ) AS keep_id
        FROM conversations
        WHERE campaign_id IS NULL AND facebook_campaign_id IS NULL
        """
    )
    op.execute("DELETE FROM _conv_dupes WHERE dupe_id = keep_id")

    # Repoint messages onto the surviving conversation.
    op.execute(
        """
        UPDATE messages m
        SET conversation_id = d.keep_id
        FROM _conv_dupes d
        WHERE m.conversation_id = d.dupe_id
        """
    )

    # Carry the whole group's state onto the survivor. Aggregating over the
    # survivor *and* its duplicates (not just the duplicates) is what lets
    # status be resolved correctly in both directions.
    #
    # status takes the most restrictive value in the group, because the
    # dangerous direction is the permissive one: if any fork was handed to a
    # human, the merged thread must stay handed off, or the bot silently
    # resumes auto-replying on a conversation somebody deliberately took over.
    # closed > handed_off > bot_active.
    #
    # handoff_reason comes from the most recently active fork that has one,
    # ordered by (last_message_at, created_at, id) so the choice is
    # deterministic rather than whichever row the planner happened to emit.
    # It is cleared when the resolved status is bot_active, so the pair can
    # never end up inconsistent.
    op.execute(
        """
        UPDATE conversations c
        SET turn_count      = agg.total_turns,
            last_message_at = agg.latest,
            status          = agg.status,
            handoff_reason  = CASE WHEN agg.status = 'bot_active'
                                   THEN NULL ELSE agg.handoff_reason END
        FROM (
            SELECT g.keep_id,
                   SUM(cv.turn_count)      AS total_turns,
                   MAX(cv.last_message_at) AS latest,
                   CASE
                       WHEN bool_or(cv.status = 'closed')     THEN 'closed'
                       WHEN bool_or(cv.status = 'handed_off') THEN 'handed_off'
                       ELSE 'bot_active'
                   END AS status,
                   (array_agg(cv.handoff_reason ORDER BY
                        cv.last_message_at DESC NULLS LAST, cv.created_at DESC, cv.id DESC)
                    FILTER (WHERE cv.handoff_reason IS NOT NULL))[1] AS handoff_reason
            FROM (
                SELECT keep_id, dupe_id AS member_id FROM _conv_dupes
                UNION
                SELECT DISTINCT keep_id, keep_id FROM _conv_dupes
            ) g
            JOIN conversations cv ON cv.id = g.member_id
            GROUP BY g.keep_id
        ) agg
        WHERE c.id = agg.keep_id
        """
    )

    op.execute("DELETE FROM conversations WHERE id IN (SELECT dupe_id FROM _conv_dupes)")
    op.execute("DROP TABLE _conv_dupes")

    if _INDEX_NAME not in _index_names("conversations"):
        op.execute(
            f"""
            CREATE UNIQUE INDEX {_INDEX_NAME}
            ON conversations (lead_id)
            WHERE campaign_id IS NULL AND facebook_campaign_id IS NULL
            """
        )


def downgrade() -> None:
    # Only the index is reversible; the duplicate merge above is not (and
    # should not be) undone.
    if _INDEX_NAME in _index_names("conversations"):
        op.execute(f"DROP INDEX {_INDEX_NAME}")

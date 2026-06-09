"""Add follow prompt delivery flow

Revision ID: 0003_follow_prompt_flow
Revises: 0002_instagram_account_status
Create Date: 2026-05-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0003_follow_prompt_flow"
down_revision = "0002_instagram_account_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    campaign_columns = {column["name"] for column in inspector.get_columns("campaigns")}
    if "delivery_mode" not in campaign_columns:
        op.add_column(
            "campaigns",
            sa.Column("delivery_mode", sa.String(length=50), nullable=False, server_default="instant"),
        )
        op.alter_column("campaigns", "delivery_mode", server_default=None)
    if "follow_prompt_title" not in campaign_columns:
        op.add_column("campaigns", sa.Column("follow_prompt_title", sa.Text(), nullable=True))
    if "follow_prompt_description" not in campaign_columns:
        op.add_column("campaigns", sa.Column("follow_prompt_description", sa.Text(), nullable=True))
    if "follow_prompt_profile_url" not in campaign_columns:
        op.add_column("campaigns", sa.Column("follow_prompt_profile_url", sa.Text(), nullable=True))

    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    if "message_type" not in message_columns:
        op.add_column(
            "messages",
            sa.Column("message_type", sa.String(length=50), nullable=False, server_default="final_delivery"),
        )
        op.alter_column("messages", "message_type", server_default=None)

    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("messages")}
    if "uq_message_campaign_comment" in constraints:
        op.drop_constraint("uq_message_campaign_comment", "messages", type_="unique")
    constraints = {constraint["name"] for constraint in sa.inspect(bind).get_unique_constraints("messages")}
    if "uq_message_campaign_comment_type" not in constraints:
        op.create_unique_constraint(
            "uq_message_campaign_comment_type",
            "messages",
            ["campaign_id", "comment_id", "message_type"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("messages")}
    if "uq_message_campaign_comment_type" in constraints:
        op.drop_constraint("uq_message_campaign_comment_type", "messages", type_="unique")
    if "uq_message_campaign_comment" not in constraints:
        op.create_unique_constraint(
            "uq_message_campaign_comment",
            "messages",
            ["campaign_id", "comment_id"],
        )

    message_columns = {column["name"] for column in sa.inspect(bind).get_columns("messages")}
    if "message_type" in message_columns:
        op.drop_column("messages", "message_type")

    campaign_columns = {column["name"] for column in sa.inspect(bind).get_columns("campaigns")}
    for column_name in (
        "follow_prompt_profile_url",
        "follow_prompt_description",
        "follow_prompt_title",
        "delivery_mode",
    ):
        if column_name in campaign_columns:
            op.drop_column("campaigns", column_name)

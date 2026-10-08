"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MySQL 5.7 禁止 TEXT 默认值；应用 ORM 已提供这些字段的默认值。
    text_options = {} if op.get_bind().dialect.name == 'mysql' else {'server_default': ''}
    op.create_table(
        "categories",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, **text_options),
        sa.Column("category_id", sa.String(length=80), nullable=False),
        sa.Column("tags", sa.Text(), nullable=False, **text_options),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("updated_at", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
    )

    op.create_table(
        "ai_providers",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False, **text_options),
        sa.Column("api_key_hint", sa.String(length=40), nullable=False, server_default="未填写"),
        sa.Column("default_model", sa.String(length=120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "ai_models",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False, server_default="32000"),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_providers.id"]),
    )


def downgrade() -> None:
    op.drop_table("ai_models")
    op.drop_table("ai_providers")
    op.drop_table("documents")
    op.drop_table("categories")

"""Atlas's own accounts: the Better Auth tables, and plans.user_id

The web app's own Better Auth (web/lib/auth.ts, AUTH_MODE=atlas) keeps its core models here, in
snake_case: `users`, `auth_sessions`, `auth_accounts` (the Google account or the magic-link
credential linked to a user) and `auth_verifications` (pending magic-link tokens and OAuth
states). The web app writes them; the backend reads `users` and stores the owner's id on new
plans (`plans.user_id`, NULL for TripTracker's and the local mode's plans, ownership still by
`user_email` until the switch). Deleting a user deletes their plans, sessions and accounts.

Revision ID: 600fbb922f91
Revises: a3f5b8c1d7e2
Create Date: 2026-10-17 15:45:14.369853+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "600fbb922f91"
down_revision: str | Sequence[str] | None = "a3f5b8c1d7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_verifications",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_verifications")),
    )
    op.create_index(
        op.f("ix_auth_verifications_identifier"), "auth_verifications", ["identifier"], unique=False
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("image", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "auth_accounts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("id_token", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_accounts")),
    )
    op.create_index(op.f("ix_auth_accounts_user_id"), "auth_accounts", ["user_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token", name=op.f("uq_auth_sessions_token")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.add_column("plans", sa.Column("user_id", sa.Text(), nullable=True))
    op.create_index(op.f("ix_plans_user_id"), "plans", ["user_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_plans_user_id_users"), "plans", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_plans_user_id_users"), "plans", type_="foreignkey")
    op.drop_index(op.f("ix_plans_user_id"), table_name="plans")
    op.drop_column("plans", "user_id")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_auth_accounts_user_id"), table_name="auth_accounts")
    op.drop_table("auth_accounts")
    op.drop_table("users")
    op.drop_index(op.f("ix_auth_verifications_identifier"), table_name="auth_verifications")
    op.drop_table("auth_verifications")

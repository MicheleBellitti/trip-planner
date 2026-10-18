"""The waitlist: addresses that asked for an invitation, and the invitations

One row per address (`email`, trimmed and lower-cased by the web app). `invited_at` NULL is a
pending request from the landing's or the login's form (`source`); once an admin invites it
(`invited_at`, `invited_by`) the web app's sign-up policy lets that address create an account,
and the invitation email's departure is `invitation_sent_at`. The web app
(web/lib/server/waitlist.ts) writes and reads the table; the backend only migrates it.

Revision ID: 609ccf5bdc99
Revises: 600fbb922f91
Create Date: 2026-10-17 18:03:54.142193+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "609ccf5bdc99"
down_revision: str | Sequence[str] | None = "600fbb922f91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waitlist",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by", sa.Text(), nullable=True),
        sa.Column("invitation_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("email", name=op.f("pk_waitlist")),
    )


def downgrade() -> None:
    op.drop_table("waitlist")

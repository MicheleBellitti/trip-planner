"""destination_covers: cached Wikimedia cover photo per destination

destination_covers: one row per normalized destination name (app/covers.py `cache_key`); `cover`
is the Cover JSON of the free-licensed image, or NULL for a cached miss; `fetched_at` drives the
refresh (30 days for a cover, a few hours for a miss).

Revision ID: c0e7a1b4f2d9
Revises: de5a02c96d07
Create Date: 2026-10-12 19:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c0e7a1b4f2d9"
down_revision: str | Sequence[str] | None = "de5a02c96d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "destination_covers",
        sa.Column("destination_key", sa.Text(), nullable=False),
        sa.Column("cover", postgresql.JSONB(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("destination_key", name=op.f("pk_destination_covers")),
    )


def downgrade() -> None:
    op.drop_table("destination_covers")

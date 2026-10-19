"""add link_health to plans

Revision ID: 924fdf7a0667
Revises: 22bb438487ee
Create Date: 2026-10-18 17:33:03.085565+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "924fdf7a0667"
down_revision: str | Sequence[str] | None = "22bb438487ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column(
            "link_health", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("plans", "link_health")

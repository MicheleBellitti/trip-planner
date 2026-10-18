"""plans.continues: how many times "Continua" raised a plan's budget.

The cap on "Continua" per plan (MAX_CONTINUES_PER_PLAN, app/quota.py) counts this column, which
`set_plan_status(..., continues_increment=1)` raises with every approved $2. Existing rows start
at 0: their earlier "Continua" are not counted, so the cap applies to them from now on.

Revision ID: 22bb438487ee
Revises: 609ccf5bdc99
Create Date: 2026-10-18 00:18:50.000321+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22bb438487ee"
down_revision: str | Sequence[str] | None = "609ccf5bdc99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plans", sa.Column("continues", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("plans", "continues")

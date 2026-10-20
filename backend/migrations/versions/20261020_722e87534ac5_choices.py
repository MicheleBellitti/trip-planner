"""the choices table: questions put to the traveller (ask_traveller) and their answers

Revision ID: 722e87534ac5
Revises: 924fdf7a0667
Create Date: 2026-10-20 05:53:39.336381+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "722e87534ac5"
down_revision: str | Sequence[str] | None = "924fdf7a0667"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "choices",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False
        ),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "answer", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("answered_by", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "answered_by IS NULL OR answered_by IN ('traveller', 'skip', 'timeout', 'closed')",
            name=op.f("ck_choices_answered_by"),
        ),
        sa.CheckConstraint(
            "kind IN ('destination', 'journey', 'activities', 'food', 'other')",
            name=op.f("ck_choices_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_choices_plan_id_plans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_choices")),
    )
    op.create_index(op.f("ix_choices_plan_id"), "choices", ["plan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_choices_plan_id"), table_name="choices")
    op.drop_table("choices")

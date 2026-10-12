"""initial schema: plans, events, fx_rates

plans: one planning run (request, Managed Agents session, plan, trip, cost and budget,
versions, when it last entered running, whether an interrupt was asked).
events: normalized UI events per plan; ma_event_id is unique so a resumed consumer never
duplicates an event. The primary key (plan_id, seq) is the read index for the SSE replay.
fx_rates: cached exchange rates, units of currency per 1 EUR, one per currency, day and source.

Revision ID: de5a02c96d07
Revises:
Create Date: 2026-10-12 00:01:34.537330+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "de5a02c96d07"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.PrimaryKeyConstraint("date", "currency", "source", name=op.f("pk_fx_rates")),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_email", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("agent_profile", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("trip", postgresql.JSONB(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("budget_cents", sa.Integer(), nullable=True),
        sa.Column("submit_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "agent_versions",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "running_since",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("interrupt_requested_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('running', 'ready', 'failed', 'budget_paused', 'blocked', 'interrupted')",
            name=op.f("ck_plans_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
    )
    op.create_table(
        "events",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=True),
        sa.Column("ma_event_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_events_plan_id_plans"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("plan_id", "seq", name=op.f("pk_events")),
        sa.UniqueConstraint("ma_event_id", name=op.f("uq_events_ma_event_id")),
    )


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("plans")
    op.drop_table("fx_rates")

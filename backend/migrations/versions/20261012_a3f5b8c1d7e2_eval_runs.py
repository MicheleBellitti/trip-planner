"""eval_runs: uploaded eval results, for the eval history page

eval_runs: one row per eval run uploaded by the CI job (POST /evals/runs) or imported with
`python -m app.cli import-evals`. `run_key` (profile, git sha, start time) is unique, so an
upload is idempotent; `summary` holds the list fields, `results` the whole document of
evals/run.py and `comparison` evals/compare.py's JSON (NULL when not compared).

Revision ID: a3f5b8c1d7e2
Revises: c0e7a1b4f2d9
Create Date: 2026-10-12 21:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3f5b8c1d7e2"
down_revision: str | Sequence[str] | None = "c0e7a1b4f2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_key", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aborted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        sa.Column("comparison", postgresql.JSONB(), nullable=True),
        sa.Column("workflow_run_url", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
        sa.UniqueConstraint("run_key", name=op.f("uq_eval_runs_run_key")),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")

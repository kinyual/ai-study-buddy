"""create quiz results and question snapshots

Revision ID: 0002_create_quiz_results
Revises: 0001_create_users
Create Date: 2026-11-27

"""

from collections.abc import Sequence
from typing import Optional

import sqlalchemy as sa
from alembic import op

revision: str = "0002_create_quiz_results"
down_revision: Optional[str] = "0001_create_users"
branch_labels: Optional[Sequence[str]] = None
depends_on: Optional[Sequence[str]] = None


def upgrade() -> None:
    op.create_table(
        "quiz_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quiz_id", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("difficulty", sa.String(length=10), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("percentage", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_quiz_results_user_id"),
        "quiz_results",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quiz_results_quiz_id"),
        "quiz_results",
        ["quiz_id"],
        unique=True,
    )

    op.create_table(
        "quiz_result_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("option_a", sa.Text(), nullable=False),
        sa.Column("option_b", sa.Text(), nullable=False),
        sa.Column("option_c", sa.Text(), nullable=False),
        sa.Column("option_d", sa.Text(), nullable=False),
        sa.Column("correct_option", sa.String(length=1), nullable=False),
        sa.Column("selected_option", sa.String(length=1), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("source_snippet", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["result_id"],
            ["quiz_results.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "result_id",
            "position",
            name="uq_quiz_result_items_result_position",
        ),
    )
    op.create_index(
        op.f("ix_quiz_result_items_result_id"),
        "quiz_result_items",
        ["result_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_quiz_result_items_result_id"), table_name="quiz_result_items")
    op.drop_table("quiz_result_items")
    op.drop_index(op.f("ix_quiz_results_quiz_id"), table_name="quiz_results")
    op.drop_index(op.f("ix_quiz_results_user_id"), table_name="quiz_results")
    op.drop_table("quiz_results")

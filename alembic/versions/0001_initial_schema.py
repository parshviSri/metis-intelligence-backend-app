"""
alembic/versions/0001_initial_schema.py
──────────────────────────────────────────────────────────────────────────────
Initial database schema for Metis Intelligence Backend.

Creates:
  diagnostics   – one row per wizard submission
  reports       – one row per LLM-generated report (FK → diagnostics)

Run:
  alembic upgrade head
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ── diagnostics ────────────────────────────────────────────────────────
    op.create_table(
        "diagnostics",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "raw_input_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full JSON payload as received from the frontend",
        ),
        sa.Column(
            "business_name",
            sa.String(length=255),
            nullable=False,
            comment="Extracted from raw_input_json.business_name",
        ),
        sa.Column(
            "business_type",
            sa.String(length=100),
            nullable=False,
            comment="Extracted from raw_input_json.business_type",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_diagnostics_id", "diagnostics", ["id"])
    op.create_index("ix_diagnostics_business_name", "diagnostics", ["business_name"])

    # ── reports ────────────────────────────────────────────────────────────
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "diagnostic_id",
            sa.Integer(),
            sa.ForeignKey("diagnostics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "llm_response",
            sa.Text(),
            nullable=False,
            comment="Raw JSON string returned by the LLM service",
        ),
        sa.Column(
            "health_score",
            sa.SmallInteger(),
            nullable=True,
            comment="0-100 business health score parsed from llm_response",
        ),
        sa.Column(
            "insights_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Parsed insights array from llm_response",
        ),
        sa.Column(
            "recommendations_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Parsed recommendations array from llm_response",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reports_id", "reports", ["id"])
    op.create_index("ix_reports_diagnostic_id", "reports", ["diagnostic_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_diagnostic_id", table_name="reports")
    op.drop_index("ix_reports_id", table_name="reports")
    op.drop_table("reports")

    op.drop_index("ix_diagnostics_business_name", table_name="diagnostics")
    op.drop_index("ix_diagnostics_id", table_name="diagnostics")
    op.drop_table("diagnostics")

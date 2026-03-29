"""add analysis type to diagnostic report

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_report",
        sa.Column("analysis_type", sa.String(length=50), nullable=False, server_default="full_diagnostic"),
    )
    op.execute("UPDATE diagnostic_report SET analysis_type = 'full_diagnostic' WHERE analysis_type IS NULL;")


def downgrade() -> None:
    op.drop_column("diagnostic_report", "analysis_type")

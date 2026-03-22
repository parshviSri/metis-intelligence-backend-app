"""
models/diagnostic.py
──────────────────────────────────────────────────────────────────────────────
ORM models for the diagnostic platform.

Tables
──────
diagnostics  – one row per wizard submission; stores the raw JSON payload plus
               normalised scalar columns for fast querying.
reports      – one row per LLM call; stores the raw LLM JSON and the parsed
               health_score, insights, and recommendations for direct reads.

Design notes
────────────
• JSONB columns (raw_input_json, insights_json, recommendations_json) hold the
  full unstructured data so nothing is ever lost.
• Scalar columns (health_score, business_name, business_type) are extracted at
  write time for cheap indexed reads.
• All timestamps are timezone-aware and default to the DB's now().
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Diagnostic(Base):
    """One submission from the frontend wizard."""

    __tablename__ = "diagnostics"

    # ── Primary key ───────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Raw payload (never lost) ──────────────────────────────────────────
    raw_input_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="Full JSON payload as received from the frontend"
    )

    # ── Extracted scalar columns for fast filtering / display ─────────────
    business_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
        comment="Extracted from raw_input_json.business_name"
    )
    business_type: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Extracted from raw_input_json.business_type"
    )

    # ── Audit timestamp ───────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationship ──────────────────────────────────────────────────────
    reports: Mapped[list["Report"]] = relationship(
        "Report", back_populates="diagnostic", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Diagnostic id={self.id} business='{self.business_name}'>"


class Report(Base):
    """
    One LLM-generated report associated with a Diagnostic.

    Stores both the raw LLM JSON string and the parsed structured fields so
    the GET endpoint never needs to re-parse the JSON.
    """

    __tablename__ = "reports"

    # ── Primary key ───────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Foreign key ───────────────────────────────────────────────────────
    diagnostic_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostics.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # ── Raw LLM output (kept for audit / re-parsing) ──────────────────────
    llm_response: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Raw JSON string returned by the LLM service"
    )

    # ── Parsed structured columns ─────────────────────────────────────────
    health_score: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True,
        comment="0-100 business health score parsed from llm_response"
    )
    insights_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="Parsed insights array from llm_response"
    )
    recommendations_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True,
        comment="Parsed recommendations array from llm_response"
    )

    # ── Audit timestamp ───────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationship ──────────────────────────────────────────────────────
    diagnostic: Mapped["Diagnostic"] = relationship(
        "Diagnostic", back_populates="reports"
    )

    def __repr__(self) -> str:
        return f"<Report id={self.id} diagnostic_id={self.diagnostic_id} score={self.health_score}>"

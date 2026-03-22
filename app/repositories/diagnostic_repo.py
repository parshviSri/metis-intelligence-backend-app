"""
repositories/diagnostic_repo.py
──────────────────────────────────────────────────────────────────────────────
Data-access layer for the diagnostic platform.

All database interactions are isolated here — the route layer and service
layer never import SQLAlchemy directly.

Functions
─────────
create_diagnostic(db, raw_input)              → Diagnostic
create_report(db, diagnostic_id, llm_response, health_score, insights, recommendations) → Report
get_diagnostic_by_id(db, diagnostic_id)       → Diagnostic | None
get_report_by_diagnostic_id(db, diagnostic_id)→ Report | None
list_diagnostics(db, skip, limit)             → list[Diagnostic]
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.diagnostic import Diagnostic, Report

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Write operations
# ─────────────────────────────────────────────────────────────────────────────

def create_diagnostic(db: Session, raw_input: dict[str, Any]) -> Diagnostic:
    """
    Persist a new Diagnostic row.

    Extracts business_name and business_type from the payload into dedicated
    columns for fast indexed lookups.

    Parameters
    ----------
    db        : Active SQLAlchemy Session
    raw_input : Validated + normalised request payload dict

    Returns
    -------
    Diagnostic
        The newly created ORM object with id and created_at populated.
    """
    diagnostic = Diagnostic(
        raw_input_json=raw_input,
        business_name=str(raw_input.get("business_name", "")).strip() or "Unknown",
        business_type=str(raw_input.get("business_type", "")).strip() or "other",
    )
    db.add(diagnostic)
    db.commit()
    db.refresh(diagnostic)
    logger.info(
        "Created Diagnostic id=%d for business='%s'",
        diagnostic.id,
        diagnostic.business_name,
    )
    return diagnostic


def create_report(
    db: Session,
    diagnostic_id: int,
    llm_response: str,
    health_score: Optional[int] = None,
    insights: Optional[list[dict]] = None,
    recommendations: Optional[list[dict]] = None,
) -> Report:
    """
    Persist a new Report row linked to a Diagnostic.

    Stores both the raw LLM JSON string and the pre-parsed structured fields
    so the GET endpoint never needs to re-parse.

    Parameters
    ----------
    db               : Active SQLAlchemy Session
    diagnostic_id    : FK to the parent Diagnostic row
    llm_response     : Raw JSON string from the LLM service
    health_score     : Parsed 0-100 integer (None if parsing failed)
    insights         : Parsed list[dict] of insight objects
    recommendations  : Parsed list[dict] of recommendation objects

    Returns
    -------
    Report
        The newly created ORM object with id and created_at populated.
    """
    report = Report(
        diagnostic_id=diagnostic_id,
        llm_response=llm_response,
        health_score=health_score,
        insights_json=insights or [],
        recommendations_json=recommendations or [],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info(
        "Created Report id=%d for Diagnostic id=%d (score=%s)",
        report.id,
        diagnostic_id,
        health_score,
    )
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Read operations
# ─────────────────────────────────────────────────────────────────────────────

def get_diagnostic_by_id(
    db: Session, diagnostic_id: int
) -> Optional[Diagnostic]:
    """
    Fetch a single Diagnostic by primary key.

    Returns None if not found (caller should raise 404).
    """
    return db.get(Diagnostic, diagnostic_id)


def get_report_by_diagnostic_id(
    db: Session, diagnostic_id: int
) -> Optional[Report]:
    """
    Fetch the most recent Report associated with a given Diagnostic.

    Returns None if no report exists yet.
    """
    return (
        db.query(Report)
        .filter(Report.diagnostic_id == diagnostic_id)
        .order_by(Report.created_at.desc())
        .first()
    )


def list_diagnostics(
    db: Session,
    skip: int = 0,
    limit: int = 50,
) -> list[Diagnostic]:
    """
    Return a paginated list of Diagnostic rows, newest first.

    Parameters
    ----------
    skip  : Number of rows to skip (offset)
    limit : Maximum number of rows to return (capped at 200)
    """
    limit = min(limit, 200)
    return (
        db.query(Diagnostic)
        .order_by(Diagnostic.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

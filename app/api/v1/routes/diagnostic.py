"""
api/v1/routes/diagnostic.py
──────────────────────────────────────────────────────────────────────────────
HTTP route handlers for the diagnostic platform.

Endpoints
─────────
POST /api/v1/diagnostic/submit
    Accept the full wizard payload, run the LLM, persist results, return report.

GET  /api/v1/diagnostic/{diagnostic_id}
    Retrieve a previously submitted diagnostic and its associated report.

GET  /api/v1/diagnostics
    Paginated list of all submitted diagnostics (newest first).

Architecture
────────────
• Routes are thin: they validate input (Pydantic), call the repo + service,
  and build the response.  Zero business logic lives here.
• All DB access goes through repositories/diagnostic_repo.py.
• All LLM logic goes through services/llm_service.py.
• Errors are surfaced as FastAPI HTTPException with clear detail messages.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.diagnostic_repo import (
    create_diagnostic,
    create_report,
    get_diagnostic_by_id,
    get_report_by_diagnostic_id,
    list_diagnostics,
)
from app.schemas.diagnostic_schema import (
    DiagnosticRequest,
    DiagnosticResponse,
    DiagnosticSummary,
    Insight,
    Recommendation,
)
from app.services.llm_service import generate_report
from app.utils import calculate_health_score, normalise_payload

router = APIRouter(prefix="/diagnostic", tags=["Diagnostic"])
logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# POST /diagnostic/submit
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/submit",
    response_model=DiagnosticResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a business diagnostic and receive a structured AI report",
    response_description="Structured diagnostic report with health score, insights, and recommendations",
)
def submit_diagnostic(
    payload: DiagnosticRequest,
    db: Session = Depends(get_db),
) -> DiagnosticResponse:
    """
    **Main endpoint consumed by the frontend wizard.**

    Flow
    ────
    1. Normalise + clean the raw payload.
    2. Persist the Diagnostic row (raw JSON + extracted scalar columns).
    3. Call the LLM service (OpenAI or mock) → raw JSON string.
    4. Parse the LLM output into typed structures.
    5. Persist the Report row (raw string + parsed columns).
    6. Return the full DiagnosticResponse to the frontend.

    On any unrecoverable error a 500 is returned with a descriptive message.
    The LLM service handles its own fallback to mock, so a network error to
    OpenAI will never cause a 500.
    """
    logger.info(
        "Diagnostic submission received for business='%s' type='%s'",
        payload.business_name,
        payload.business_type,
    )

    # ── 1. Normalise payload ───────────────────────────────────────────────
    clean_data = normalise_payload(payload.model_dump())

    # ── 2. Persist Diagnostic ──────────────────────────────────────────────
    try:
        diagnostic = create_diagnostic(db=db, raw_input=clean_data)
    except Exception as exc:
        logger.exception("Failed to persist Diagnostic row")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while saving diagnostic: {exc}",
        ) from exc

    # ── 3. Call LLM service ────────────────────────────────────────────────
    try:
        llm_raw: str = generate_report(clean_data)
    except Exception as exc:
        logger.exception("LLM service raised an unhandled exception")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation failed: {exc}",
        ) from exc

    # ── 4. Parse LLM output ────────────────────────────────────────────────
    health_score, insights, recommendations = _parse_llm_output(
        llm_raw, fallback_data=clean_data
    )

    # ── 5. Persist Report ──────────────────────────────────────────────────
    try:
        report = create_report(
            db=db,
            diagnostic_id=diagnostic.id,
            llm_response=llm_raw,
            health_score=health_score,
            insights=insights,
            recommendations=recommendations,
        )
    except Exception as exc:
        logger.exception("Failed to persist Report row")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while saving report: {exc}",
        ) from exc

    # ── 6. Build and return response ───────────────────────────────────────
    logger.info(
        "Diagnostic complete — diagnostic_id=%d report_id=%d health_score=%d",
        diagnostic.id,
        report.id,
        health_score,
    )

    return DiagnosticResponse(
        diagnostic_id=diagnostic.id,
        report_id=report.id,
        status="submitted",
        message="Diagnostic submitted successfully.",
        health_score=health_score,
        insights=[Insight(**i) for i in insights],
        recommendations=[Recommendation(**r) for r in recommendations],
        llm_response=llm_raw,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /diagnostic/{diagnostic_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{diagnostic_id}",
    response_model=DiagnosticResponse,
    summary="Retrieve a previously submitted diagnostic report by ID",
)
def get_diagnostic(
    diagnostic_id: int,
    db: Session = Depends(get_db),
) -> DiagnosticResponse:
    """
    Retrieve a full diagnostic report by its ID.

    Returns 404 if the diagnostic_id does not exist.
    Returns 404 if no report has been generated yet for this diagnostic.
    """
    diagnostic = get_diagnostic_by_id(db=db, diagnostic_id=diagnostic_id)
    if diagnostic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic with id={diagnostic_id} not found.",
        )

    report = get_report_by_diagnostic_id(db=db, diagnostic_id=diagnostic_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found for diagnostic id={diagnostic_id}.",
        )

    # Re-hydrate insights / recommendations from stored JSONB
    insights_raw = report.insights_json or []
    recs_raw     = report.recommendations_json or []

    return DiagnosticResponse(
        diagnostic_id=diagnostic.id,
        report_id=report.id,
        status="submitted",
        message="Diagnostic retrieved successfully.",
        health_score=report.health_score or 0,
        insights=[Insight(**i) for i in insights_raw if isinstance(i, dict)],
        recommendations=[Recommendation(**r) for r in recs_raw if isinstance(r, dict)],
        llm_response=report.llm_response,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /diagnostics  (list – mounted on the parent router at /api/v1)
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "s",  # resolves to /api/v1/diagnostics
    response_model=list[DiagnosticSummary],
    summary="List all submitted diagnostics (paginated, newest first)",
)
def list_all_diagnostics(
    skip: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=200, description="Max rows to return")] = 20,
    db: Session = Depends(get_db),
) -> list[DiagnosticSummary]:
    """
    Return a paginated list of submitted diagnostics.

    Each item includes the diagnostic_id, business_name, business_type,
    health_score (if a report exists), and created_at timestamp.
    """
    rows = list_diagnostics(db=db, skip=skip, limit=limit)
    summaries = []
    for d in rows:
        report = get_report_by_diagnostic_id(db=db, diagnostic_id=d.id)
        summaries.append(
            DiagnosticSummary(
                diagnostic_id=d.id,
                business_name=d.business_name,
                business_type=d.business_type,
                health_score=report.health_score if report else None,
                created_at=d.created_at.isoformat(),
            )
        )
    return summaries


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_llm_output(
    llm_raw: str,
    fallback_data: dict,
) -> tuple[int, list[dict], list[dict]]:
    """
    Parse the raw LLM JSON string into typed components.

    On any parse / validation error falls back to:
    • health_score  → deterministic calculation from fallback_data
    • insights      → empty list
    • recommendations → empty list

    Returns (health_score, insights, recommendations).
    """
    try:
        parsed: dict = json.loads(llm_raw)
    except json.JSONDecodeError:
        logger.warning("LLM response was not valid JSON — using deterministic fallback")
        return calculate_health_score(fallback_data), [], []

    # health_score
    try:
        health_score = int(parsed.get("health_score", 0))
        health_score = max(0, min(100, health_score))
    except (TypeError, ValueError):
        health_score = calculate_health_score(fallback_data)

    # insights
    raw_insights = parsed.get("insights", [])
    insights: list[dict] = []
    for item in raw_insights:
        if isinstance(item, dict) and "category" in item and "text" in item:
            insights.append(
                {"category": str(item["category"]), "text": str(item["text"])}
            )

    # recommendations
    raw_recs = parsed.get("recommendations", [])
    recommendations: list[dict] = []
    valid_priorities = {"high", "medium", "low"}
    for item in raw_recs:
        if isinstance(item, dict):
            priority = str(item.get("priority", "medium")).lower()
            if priority not in valid_priorities:
                priority = "medium"
            recommendations.append(
                {
                    "priority": priority,
                    "action": str(item.get("action", "")),
                    "rationale": str(item.get("rationale", "")),
                }
            )

    return health_score, insights, recommendations

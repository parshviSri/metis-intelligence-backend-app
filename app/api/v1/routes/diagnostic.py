from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.diagnostic_repo import (
    create_business,
    create_report_bundle,
    find_user,
    get_business_by_id,
    get_or_create_user,
    get_report_by_business_id,
    get_user_analysis_types,
    list_businesses,
)
from app.schemas.diagnostic_schema import (
    AnalysisAccessRequest,
    AnalysisAccessResponse,
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


@router.post(
    "/analysis-access",
    response_model=AnalysisAccessResponse,
    summary="Check whether a user can access an analysis for free or must pay",
)
def check_analysis_access(
    payload: AnalysisAccessRequest,
    db: Session = Depends(get_db),
) -> AnalysisAccessResponse:
    user = find_user(db=db, user_id=payload.user_id, email=payload.email)
    if user is None:
        return AnalysisAccessResponse(
            user_exists=False,
            user_id=None,
            selected_analysis_type=payload.analysis_type,
            previous_analysis_types=[],
            is_first_analysis=True,
            has_used_selected_analysis=False,
            requires_payment=False,
            message="First analysis for this user. Allow free access.",
        )

    previous_analysis_types = get_user_analysis_types(db=db, user_id=user.user_id)
    has_used_selected_analysis = payload.analysis_type in previous_analysis_types
    is_first_analysis = len(previous_analysis_types) == 0
    requires_payment = not is_first_analysis and not has_used_selected_analysis

    if is_first_analysis:
        message = "First analysis for this user. Allow free access."
    elif has_used_selected_analysis:
        message = "User has already used this analysis type. No extra payment required for the same analysis type."
    else:
        message = "User has already used a different analysis type. Payment is required for a new analysis type."

    return AnalysisAccessResponse(
        user_exists=True,
        user_id=user.user_id,
        selected_analysis_type=payload.analysis_type,
        previous_analysis_types=previous_analysis_types,
        is_first_analysis=is_first_analysis,
        has_used_selected_analysis=has_used_selected_analysis,
        requires_payment=requires_payment,
        message=message,
    )


@router.post(
    "/submit",
    response_model=DiagnosticResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a business diagnostic and receive a structured AI report",
)
def submit_diagnostic(
    payload: DiagnosticRequest,
    db: Session = Depends(get_db),
    prompt_version: Literal["v1", "v2"] = Query(default="v1"),
) -> DiagnosticResponse:
    logger.info(
        "Diagnostic submission received for business='%s' type='%s' user_email='%s' analysis_type='%s'",
        payload.business_name,
        payload.business_type,
        payload.email,
        payload.analysis_type,
    )

    clean_data = normalise_payload(payload.model_dump())

    try:
        user = get_or_create_user(db=db, user_id=payload.user_id, email=payload.email)
        if payload.user_id is not None and user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id={payload.user_id} not found.",
            )
        business = create_business(db=db, raw_input=clean_data, user=user)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to persist business layer")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while saving business data: {exc}",
        ) from exc

    try:
        llm_raw = generate_report(clean_data, prompt_version=prompt_version)
        health_score, insights, recommendations = _parse_llm_output(llm_raw, fallback_data=clean_data)
    except Exception as exc:
        logger.exception("LLM service raised an unhandled exception")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation failed: {exc}",
        ) from exc

    try:
        report = create_report_bundle(
            db=db,
            user=user,
            business=business,
            clean_data=clean_data,
            llm_response=llm_raw,
            health_score=health_score,
            insights=insights,
            recommendations=recommendations,
            analysis_type=payload.analysis_type,
            status="completed",
            message="Diagnostic submitted successfully.",
        )
    except Exception as exc:
        logger.exception("Failed to persist diagnostic report bundle")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while saving report data: {exc}",
        ) from exc

    return DiagnosticResponse(
        diagnostic_id=business.business_id,
        report_id=report.report_id,
        business_id=business.business_id,
        user_id=user.user_id if user else None,
        analysis_type=payload.analysis_type,
        status=report.status,
        message=report.message,
        health_score=health_score,
        insights=[Insight(**i) for i in insights],
        recommendations=[Recommendation(**r) for r in recommendations],
        llm_response=llm_raw,
    )


@router.get(
    "/{diagnostic_id}",
    response_model=DiagnosticResponse,
    summary="Retrieve a previously submitted diagnostic report by business ID",
)
def get_diagnostic(
    diagnostic_id: int,
    db: Session = Depends(get_db),
) -> DiagnosticResponse:
    business = get_business_by_id(db=db, business_id=diagnostic_id)
    if business is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Business with id={diagnostic_id} not found.",
        )

    report = get_report_by_business_id(db=db, business_id=diagnostic_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No report found for business id={diagnostic_id}.",
        )

    return DiagnosticResponse(
        diagnostic_id=business.business_id,
        report_id=report.report_id,
        business_id=business.business_id,
        user_id=business.user_id,
        analysis_type=report.analysis_type,
        status=report.status,
        message=report.message,
        health_score=report.health_score or 0,
        insights=[Insight(category=i.category, text=i.text) for i in report.insights],
        recommendations=[
            Recommendation(priority=r.priority, action=r.action, rationale=r.rationale)
            for r in report.recommendations
        ],
        llm_response=report.llm_response,
    )


@router.get(
    "s",
    response_model=list[DiagnosticSummary],
    summary="List all submitted diagnostics (paginated, newest first)",
)
def list_all_diagnostics(
    skip: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=200, description="Max rows to return")] = 20,
    db: Session = Depends(get_db),
) -> list[DiagnosticSummary]:
    rows = list_businesses(db=db, skip=skip, limit=limit)
    summaries: list[DiagnosticSummary] = []
    for business in rows:
        report = get_report_by_business_id(db=db, business_id=business.business_id)
        summaries.append(
            DiagnosticSummary(
                diagnostic_id=business.business_id,
                report_id=report.report_id if report else None,
                business_id=business.business_id,
                user_id=business.user_id,
                analysis_type=report.analysis_type if report else "full_diagnostic",
                business_name=business.business_name,
                business_type=business.business_type,
                health_score=report.health_score if report else None,
                created_at=business.created_at.isoformat(),
            )
        )
    return summaries


def _parse_llm_output(llm_raw: str, fallback_data: dict) -> tuple[int, list[dict], list[dict]]:
    try:
        parsed: dict = json.loads(llm_raw)
    except json.JSONDecodeError:
        logger.warning("LLM response was not valid JSON; using deterministic fallback")
        return calculate_health_score(fallback_data), [], []

    try:
        health_score = int(parsed.get("health_score", 0))
        health_score = max(0, min(100, health_score))
    except (TypeError, ValueError):
        health_score = calculate_health_score(fallback_data)

    insights: list[dict] = []
    for item in parsed.get("insights", []):
        if isinstance(item, dict) and "category" in item and "text" in item:
            insights.append({"category": str(item["category"]), "text": str(item["text"])})

    recommendations: list[dict] = []
    valid_priorities = {"high", "medium", "low"}
    for item in parsed.get("recommendations", []):
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

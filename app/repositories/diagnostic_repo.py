from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.models.diagnostic import (
    Business,
    ChannelAnalysis,
    DiagnosticReport,
    GrowthExperiment,
    MetricsSnapshot,
    Profitability,
    ReportInsight,
    ReportRecommendation,
    RetentionLifecycle,
    User,
)

logger = get_logger(__name__)


def _stringify_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_numeric_channel_cac(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        numeric_values = [float(v) for v in value.values() if isinstance(v, (int, float))]
        if numeric_values:
            return sum(numeric_values) / len(numeric_values)
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


REPORT_RELATIONSHIPS = (
    selectinload(DiagnosticReport.insights),
    selectinload(DiagnosticReport.recommendations),
    selectinload(DiagnosticReport.business),
)


def get_or_create_user(
    db: Session,
    *,
    user_id: int | None = None,
    email: str | None = None,
) -> Optional[User]:
    if user_id is not None:
        return db.get(User, user_id)

    if not email:
        return None

    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        return existing

    user = User(email=email)
    db.add(user)
    db.flush()
    logger.info("Created User user_id=%d email=%s", user.user_id, email)
    return user


def create_business(db: Session, raw_input: dict[str, Any], user: User | None) -> Business:
    business = Business(
        user_id=user.user_id if user else None,
        business_name=str(raw_input.get("business_name", "")).strip() or "Unknown",
        business_type=str(raw_input.get("business_type", "")).strip() or "other",
        products=raw_input.get("products"),
        aov=float(raw_input.get("aov", 0) or 0),
        gross_margin=float(raw_input.get("margin", 0) or 0),
        monthly_marketing_spend=float(raw_input.get("marketing_spend", 0) or 0),
        repeat_purchase_rate=float(raw_input.get("repeat_purchase_rate", 0) or 0),
        cac=float(raw_input.get("cac", 0) or 0),
        conversion_rate=float(raw_input.get("conversion_rate", 0) or 0),
        biggest_challenge=raw_input.get("biggest_challenge"),
        raw_input_json=raw_input,
    )
    db.add(business)
    db.flush()
    logger.info("Created Business business_id=%d name=%s", business.business_id, business.business_name)
    return business


def create_report_bundle(
    db: Session,
    *,
    user: User | None,
    business: Business,
    clean_data: dict[str, Any],
    llm_response: str,
    health_score: int,
    insights: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    status: str = "completed",
    message: str = "Diagnostic submitted successfully.",
) -> DiagnosticReport:
    additional = clean_data.get("additional_inputs") or {}

    report = DiagnosticReport(
        user_id=user.user_id if user else None,
        business_id=business.business_id,
        status=status,
        message=message,
        health_score=health_score,
        llm_response=llm_response,
    )
    db.add(report)
    db.flush()

    profitability = Profitability(
        user_id=user.user_id if user else None,
        business_id=business.business_id,
        report_id=report.report_id,
        contribution_margin=additional.get("contribution_margin"),
        product_profitability=_stringify_text(additional.get("product_profitability")),
        revenue_breakdown=additional.get("revenue_breakdown"),
    )
    db.add(profitability)
    db.flush()

    channels = ChannelAnalysis(
        user_id=user.user_id if user else None,
        business_id=business.business_id,
        report_id=report.report_id,
        channel_name=(clean_data.get("channels") or [None])[0],
        channels=", ".join(clean_data.get("channels", [])) or None,
        conversion_rate=clean_data.get("conversion_rate"),
        cac_by_channel=_coerce_numeric_channel_cac(additional.get("cac_by_channel")),
    )
    db.add(channels)
    db.flush()

    retention = RetentionLifecycle(
        user_id=user.user_id if user else None,
        business_id=business.business_id,
        report_id=report.report_id,
        customer_lifetime_value=additional.get("ltv"),
        time_between_purchases=_stringify_text(additional.get("time_between_purchases")),
        cohort_tracking=additional.get("cohort_tracking"),
    )
    db.add(retention)
    db.flush()

    growth = GrowthExperiment(
        user_id=user.user_id if user else None,
        business_id=business.business_id,
        report_id=report.report_id,
        experiments=additional.get("experiments"),
        funnel_metrics=additional.get("funnel_metrics"),
        drop_off_rates=additional.get("drop_off_rates"),
    )
    db.add(growth)
    db.flush()

    insight_rows: list[ReportInsight] = []
    for item in insights:
        row = ReportInsight(
            report_id=report.report_id,
            user_id=user.user_id if user else None,
            business_id=business.business_id,
            category=str(item.get("category", "")),
            text=str(item.get("text", "")),
        )
        db.add(row)
        insight_rows.append(row)
    db.flush()

    recommendation_rows: list[ReportRecommendation] = []
    for item in recommendations:
        row = ReportRecommendation(
            report_id=report.report_id,
            user_id=user.user_id if user else None,
            business_id=business.business_id,
            priority=str(item.get("priority", "medium")),
            action=str(item.get("action", "")),
            rationale=str(item.get("rationale", "")),
        )
        db.add(row)
        recommendation_rows.append(row)
    db.flush()

    snapshot_inputs = [
        clean_data.get("aov"),
        clean_data.get("margin"),
        clean_data.get("marketing_spend"),
        clean_data.get("cac"),
        clean_data.get("conversion_rate"),
        clean_data.get("repeat_purchase_rate"),
        additional.get("ltv"),
        additional.get("revenue") or additional.get("revenue_monthly"),
        additional.get("orders"),
        additional.get("customers"),
        additional.get("snapshot_date"),
    ]
    if any(value is not None for value in snapshot_inputs):
        snapshot = MetricsSnapshot(
            user_id=user.user_id if user else None,
            business_id=business.business_id,
            report_id=report.report_id,
            aov=clean_data.get("aov"),
            margin=clean_data.get("margin"),
            marketing_spend=clean_data.get("marketing_spend"),
            cac=clean_data.get("cac"),
            conversion_rate=clean_data.get("conversion_rate"),
            repeat_purchase_rate=clean_data.get("repeat_purchase_rate"),
            ltv=additional.get("ltv"),
            revenue=additional.get("revenue") or additional.get("revenue_monthly"),
            orders=additional.get("orders"),
            customers=additional.get("customers"),
            snapshot_date=additional.get("snapshot_date"),
        )
        db.add(snapshot)
        db.flush()

    report.profitability_id = profitability.id
    report.channels_id = channels.id
    report.growth_expansion_id = growth.id
    report.recommendation_id = recommendation_rows[0].recommendation_id if recommendation_rows else None
    report.insight_id = insight_rows[0].insight_id if insight_rows else None
    report.retention_lifecycle_id = retention.id

    db.commit()
    db.refresh(report)
    logger.info(
        "Created DiagnosticReport report_id=%d business_id=%d health_score=%s",
        report.report_id,
        business.business_id,
        health_score,
    )
    return report


def get_business_by_id(db: Session, business_id: int) -> Optional[Business]:
    return db.get(Business, business_id)


def get_report_by_business_id(db: Session, business_id: int) -> Optional[DiagnosticReport]:
    return (
        db.query(DiagnosticReport)
        .options(*REPORT_RELATIONSHIPS)
        .filter(DiagnosticReport.business_id == business_id)
        .order_by(DiagnosticReport.created_at.desc())
        .first()
    )


def list_businesses(db: Session, skip: int = 0, limit: int = 50) -> list[Business]:
    limit = min(limit, 200)
    return (
        db.query(Business)
        .order_by(Business.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

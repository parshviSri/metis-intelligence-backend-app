from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

priority_level_enum = Enum("high", "medium", "low", name="priority_level")


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    businesses: Mapped[list["Business"]] = relationship("Business", back_populates="user")
    reports: Mapped[list["DiagnosticReport"]] = relationship("DiagnosticReport", back_populates="user")


class Business(Base):
    __tablename__ = "business"

    business_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    business_type: Mapped[str] = mapped_column(String(100), nullable=False)
    products: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aov: Mapped[float] = mapped_column(Float, nullable=False)
    gross_margin: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_marketing_spend: Mapped[float] = mapped_column(Float, nullable=False)
    repeat_purchase_rate: Mapped[float] = mapped_column(Float, nullable=False)
    cac: Mapped[float] = mapped_column(Float, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, nullable=False)
    biggest_challenge: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_input_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="businesses")
    reports: Mapped[list["DiagnosticReport"]] = relationship(
        "DiagnosticReport", back_populates="business", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["MetricsSnapshot"]] = relationship(
        "MetricsSnapshot", back_populates="business", cascade="all, delete-orphan"
    )


class DiagnosticReport(Base):
    __tablename__ = "diagnostic_report"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="Diagnostic submitted successfully.")
    health_score: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    llm_response: Mapped[str] = mapped_column(Text, nullable=False)
    profitability_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channels_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    growth_expansion_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    insight_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retention_lifecycle_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[Optional["User"]] = relationship("User", back_populates="reports")
    business: Mapped["Business"] = relationship("Business", back_populates="reports")
    profitability: Mapped[Optional["Profitability"]] = relationship(
        "Profitability", back_populates="report", uselist=False, cascade="all, delete-orphan"
    )
    channels: Mapped[Optional["ChannelAnalysis"]] = relationship(
        "ChannelAnalysis", back_populates="report", uselist=False, cascade="all, delete-orphan"
    )
    retention_lifecycle: Mapped[Optional["RetentionLifecycle"]] = relationship(
        "RetentionLifecycle", back_populates="report", uselist=False, cascade="all, delete-orphan"
    )
    growth_experiment: Mapped[Optional["GrowthExperiment"]] = relationship(
        "GrowthExperiment", back_populates="report", uselist=False, cascade="all, delete-orphan"
    )
    insights: Mapped[list["ReportInsight"]] = relationship(
        "ReportInsight", back_populates="report", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["ReportRecommendation"]] = relationship(
        "ReportRecommendation", back_populates="report", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["MetricsSnapshot"]] = relationship(
        "MetricsSnapshot", back_populates="report", cascade="all, delete-orphan"
    )


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshot"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, index=True)
    aov: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    marketing_spend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cac: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    conversion_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    repeat_purchase_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ltv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    orders: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    customers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snapshot_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    business: Mapped["Business"] = relationship("Business", back_populates="snapshots")
    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="snapshots")


class Profitability(Base):
    __tablename__ = "profitability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    contribution_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    product_profitability: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revenue_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="profitability")


class ChannelAnalysis(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    channel_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channels: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conversion_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cac_by_channel: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="channels")


class RetentionLifecycle(Base):
    __tablename__ = "retention_lifecycle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    customer_lifetime_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_between_purchases: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cohort_tracking: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="retention_lifecycle")


class GrowthExperiment(Base):
    __tablename__ = "growth_experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    experiments: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    funnel_metrics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    drop_off_rates: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="growth_experiment")


class ReportInsight(Base):
    __tablename__ = "insights"

    insight_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(150), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="insights")


class ReportRecommendation(Base):
    __tablename__ = "recommendations"

    recommendation_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_report.report_id", ondelete="CASCADE"), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(priority_level_enum, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.business_id", ondelete="CASCADE"), nullable=False, index=True)

    report: Mapped["DiagnosticReport"] = relationship("DiagnosticReport", back_populates="recommendations")

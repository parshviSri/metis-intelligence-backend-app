from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AnalysisType = Literal[
    "full_diagnostic",
    "profitability",
    "retention_lifecycle",
    "growth_experiments",
    "channels",
]


class AdditionalInputs(BaseModel):
    focus_areas: list[str] = Field(default_factory=list)
    ltv: Optional[float] = Field(default=None, ge=0)
    contribution_margin: Optional[float] = Field(default=None, ge=0, le=100)
    revenue_monthly: Optional[float] = Field(default=None, ge=0)
    revenue: Optional[float] = Field(default=None, ge=0)
    orders: Optional[int] = Field(default=None, ge=0)
    customers: Optional[int] = Field(default=None, ge=0)
    snapshot_date: Optional[date] = None
    product_profitability: Optional[dict[str, Any]] = None
    revenue_breakdown: Optional[dict[str, Any]] = None
    cac_by_channel: Optional[dict[str, Any]] = None
    time_between_purchases: Optional[float] = Field(default=None, ge=0)
    cohort_tracking: Optional[dict[str, Any]] = None
    experiments: Optional[dict[str, Any]] = None
    funnel_metrics: Optional[dict[str, Any]] = None
    drop_off_rates: Optional[dict[str, Any]] = None

    @field_validator("focus_areas", mode="before")
    @classmethod
    def coerce_focus_areas(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()][:10]
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()][:10]
        return []

    model_config = ConfigDict(extra="ignore")


class Insight(BaseModel):
    category: str
    text: str


class Recommendation(BaseModel):
    priority: Literal["high", "medium", "low"]
    action: str
    rationale: str


class AnalysisAccessRequest(BaseModel):
    user_id: Optional[int] = Field(default=None, ge=1)
    email: Optional[str] = Field(default=None, max_length=255)
    analysis_type: AnalysisType

    @model_validator(mode="after")
    def validate_identity(self) -> "AnalysisAccessRequest":
        if not self.user_id and not self.email:
            raise ValueError("Either user_id or email is required")
        return self


class AnalysisAccessResponse(BaseModel):
    user_exists: bool
    user_id: Optional[int] = None
    selected_analysis_type: AnalysisType
    previous_analysis_types: list[AnalysisType] = Field(default_factory=list)
    is_first_analysis: bool
    has_used_selected_analysis: bool
    requires_payment: bool
    message: str


class DiagnosticRequest(BaseModel):
    user_id: Optional[int] = Field(default=None, ge=1)
    email: Optional[str] = Field(default=None, max_length=255)
    analysis_type: AnalysisType = "full_diagnostic"
    business_name: str = Field(..., min_length=1, max_length=255)
    business_type: str = Field(..., min_length=1, max_length=100)
    products: str = Field(..., min_length=1, max_length=1000)
    aov: float = Field(..., gt=0)
    margin: float = Field(..., ge=0, le=100)
    marketing_spend: float = Field(..., ge=0)
    repeat_purchase_rate: float = Field(..., ge=0, le=100)
    cac: float = Field(..., ge=0)
    channels: list[str] = Field(..., min_length=1)
    conversion_rate: float = Field(..., ge=0, le=100)
    biggest_challenge: str = Field(..., min_length=1, max_length=2000)
    additional_inputs: AdditionalInputs = Field(default_factory=AdditionalInputs)

    @field_validator("channels", mode="before")
    @classmethod
    def coerce_channels(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            cleaned = [str(c).strip() for c in v if str(c).strip()]
            if not cleaned:
                raise ValueError("channels must contain at least one entry")
            return cleaned
        if isinstance(v, str):
            cleaned = [c.strip() for c in v.split(",") if c.strip()]
            if not cleaned:
                raise ValueError("channels must contain at least one entry")
            return cleaned
        raise ValueError("channels must be a list or a comma-separated string")

    @field_validator("business_name", "business_type", "products", "biggest_challenge", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="before")
    @classmethod
    def coerce_additional_inputs(cls, values: Any) -> Any:
        if isinstance(values, dict) and values.get("additional_inputs") is None:
            values["additional_inputs"] = {}
        return values

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "founder@example.com",
                "analysis_type": "profitability",
                "business_name": "Bloom Skincare",
                "business_type": "d2c",
                "products": "Natural skincare serums and moisturisers",
                "aov": 1800,
                "margin": 52,
                "marketing_spend": 120000,
                "repeat_purchase_rate": 22,
                "cac": 850,
                "channels": ["Instagram Ads", "Google Shopping", "Organic SEO"],
                "conversion_rate": 1.8,
                "biggest_challenge": "CAC has risen 35% in six months and we cannot find a profitable scaling channel.",
                "additional_inputs": {
                    "focus_areas": ["acquisition", "retention"],
                    "ltv": 3800,
                    "contribution_margin": 38,
                    "revenue_monthly": 450000,
                    "orders": 950,
                    "customers": 610,
                    "snapshot_date": "2026-03-24",
                    "cac_by_channel": {"Meta": 920, "Google": 770},
                },
            }
        }
    )


class DiagnosticResponse(BaseModel):
    diagnostic_id: int
    report_id: int
    business_id: int
    user_id: Optional[int] = None
    analysis_type: AnalysisType = "full_diagnostic"
    status: str
    message: str
    health_score: int = Field(..., ge=0, le=100)
    insights: list[Insight]
    recommendations: list[Recommendation]
    llm_response: str

    model_config = ConfigDict(from_attributes=True)


class DiagnosticSummary(BaseModel):
    diagnostic_id: int
    report_id: Optional[int] = None
    business_id: int
    user_id: Optional[int] = None
    analysis_type: AnalysisType = "full_diagnostic"
    business_name: str
    business_type: str
    health_score: Optional[int] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

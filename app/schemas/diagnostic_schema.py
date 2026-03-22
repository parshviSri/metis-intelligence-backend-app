"""
schemas/diagnostic_schema.py
──────────────────────────────────────────────────────────────────────────────
All Pydantic I/O models for the diagnostic endpoint.

Request  → DiagnosticRequest
Response → DiagnosticResponse  (contains Insight + Recommendation lists)

Design rules
────────────
• Every field matches exactly what the frontend sends (services/diagnosticService.js
  normalisePayload).
• Numeric fields are strictly typed as float with sensible range validators.
• channels accepts both a list and a comma-separated string (field_validator).
• additional_inputs is a free-form catch-all dict for optional / future fields.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Sub-models used inside DiagnosticResponse
# ─────────────────────────────────────────────────────────────────────────────

class Insight(BaseModel):
    """A single business insight returned by the LLM."""

    category: str = Field(..., description="Short label, e.g. 'Unit Economics'")
    text: str = Field(..., description="Human-readable insight body")


class Recommendation(BaseModel):
    """A single prioritised, actionable recommendation returned by the LLM."""

    priority: Literal["high", "medium", "low"] = Field(
        ..., description="Urgency level"
    )
    action: str = Field(..., description="Short imperative action title")
    rationale: str = Field(..., description="Data-driven explanation")


# ─────────────────────────────────────────────────────────────────────────────
# Request
# ─────────────────────────────────────────────────────────────────────────────

class DiagnosticRequest(BaseModel):
    """
    Payload sent by the frontend wizard.

    Field mapping (camelCase frontend → snake_case API)
    ────────────────────────────────────────────────────
    businessName          → business_name
    businessType          → business_type
    products              → products
    aov                   → aov
    grossMargin           → margin
    monthlyMarketingSpend → marketing_spend
    cac                   → cac
    repeatPurchaseRate    → repeat_purchase_rate
    channels              → channels
    conversionRate        → conversion_rate
    biggestChallenge      → biggest_challenge
    (rest)                → additional_inputs
    """

    # ── Step 1 – Business Basics ──────────────────────────────────────────
    business_name: str = Field(
        ..., min_length=1, max_length=255,
        description="Trading name of the business"
    )
    business_type: str = Field(
        ..., min_length=1, max_length=100,
        description="e.g. d2c, saas, services, agency, other"
    )
    products: str = Field(
        ..., min_length=1, max_length=1000,
        description="Description of products / services sold"
    )

    # ── Step 2 – Revenue & Profit ─────────────────────────────────────────
    aov: float = Field(
        ..., gt=0,
        description="Average Order Value (currency units)"
    )
    margin: float = Field(
        ..., ge=0, le=100,
        description="Gross margin percentage (0–100)"
    )
    marketing_spend: float = Field(
        ..., ge=0,
        description="Monthly marketing spend (currency units)"
    )

    # ── Step 3 – Customers & Retention ───────────────────────────────────
    repeat_purchase_rate: float = Field(
        ..., ge=0, le=100,
        description="% of customers who have made more than one purchase"
    )
    cac: float = Field(
        ..., ge=0,
        description="Customer Acquisition Cost (currency units)"
    )

    # ── Step 4 – Marketing & Acquisition ─────────────────────────────────
    channels: list[str] = Field(
        ..., min_length=1,
        description="Active marketing / sales channels"
    )
    conversion_rate: float = Field(
        ..., ge=0, le=100,
        description="Site / funnel conversion rate percentage (0–100)"
    )

    # ── Step 5 – Challenges ───────────────────────────────────────────────
    biggest_challenge: str = Field(
        ..., min_length=1, max_length=2000,
        description="Free-text description of the primary growth obstacle"
    )

    # ── Catch-all for optional / future fields ────────────────────────────
    additional_inputs: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        description="Any extra fields sent by the frontend (focus areas, LTV, etc.)"
    )

    # ── Validators ────────────────────────────────────────────────────────

    @field_validator("channels", mode="before")
    @classmethod
    def coerce_channels(cls, v: Any) -> list[str]:
        """Accept either a JSON array or a comma-separated string."""
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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
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
                },
            }
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Response
# ─────────────────────────────────────────────────────────────────────────────

class DiagnosticResponse(BaseModel):
    """
    Full structured response returned to the frontend after a successful submit.

    The frontend DiagnosticResults component consumes:
      health_score, insights, recommendations
    """

    # ── Identifiers ───────────────────────────────────────────────────────
    diagnostic_id: int = Field(..., description="PK of the Diagnostic DB row")
    report_id: int = Field(..., description="PK of the Report DB row")

    # ── Status ────────────────────────────────────────────────────────────
    status: str = Field(..., description="Always 'submitted' on success")
    message: str = Field(..., description="Human-readable status message")

    # ── Structured report ─────────────────────────────────────────────────
    health_score: int = Field(
        ..., ge=0, le=100,
        description="Overall business health score (0 = critical, 100 = excellent)"
    )
    insights: list[Insight] = Field(
        ..., description="4-6 data-driven insights covering key business dimensions"
    )
    recommendations: list[Recommendation] = Field(
        ..., description="3-6 prioritised, actionable recommendations"
    )

    # ── Raw LLM output (kept for debugging / audit) ───────────────────────
    llm_response: str = Field(
        ..., description="Raw JSON string returned by the LLM service"
    )

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight read models (used by GET /diagnostic/{id})
# ─────────────────────────────────────────────────────────────────────────────

class DiagnosticSummary(BaseModel):
    """Thin read model returned by GET /diagnostic/{id}."""

    diagnostic_id: int
    business_name: str
    business_type: str
    health_score: Optional[int] = None
    created_at: str  # ISO-8601 string

    model_config = ConfigDict(from_attributes=True)

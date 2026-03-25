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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Additional inputs sub-model
# ─────────────────────────────────────────────────────────────────────────────

class AdditionalInputs(BaseModel):
    """
    Optional, well-typed extra context forwarded to the LLM alongside the
    core KPIs.  All fields are optional; unknown keys sent by the frontend
    are silently dropped (extra='ignore') so old and future clients never
    break.

    Why a typed model instead of dict[str, Any]
    ───────────────────────────────────────────
    • Prevents unbounded payload size / injection via rogue keys.
    • Makes the contract explicit to frontend developers.
    • Allows _build_prompt() to safely read typed values with no
      defensive casting.
    • extra='ignore' means unknown keys are accepted but discarded,
      preserving forward-compatibility.
    """

    focus_areas: list[str] = Field(
        default_factory=list,
        description="Business areas to prioritise, e.g. ['acquisition', 'retention']",
    )
    ltv: Optional[float] = Field(
        default=None, ge=0,
        description="Founder-reported Lifetime Value (currency units)",
    )
    contribution_margin: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="Contribution margin % (0–100), if different from gross margin",
    )
    revenue_monthly: Optional[float] = Field(
        default=None, ge=0,
        description="Monthly revenue (currency units) for absolute-scale context",
    )

    @field_validator("focus_areas", mode="before")
    @classmethod
    def coerce_focus_areas(cls, v: Any) -> list[str]:
        """Accept a JSON array or a comma-separated string."""
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()][:10]
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()][:10]
        return []

    model_config = ConfigDict(extra="ignore")


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

    # ── Optional extra context forwarded to the LLM ─────────────────────
    additional_inputs: AdditionalInputs = Field(
        default_factory=AdditionalInputs,
        description=(
            "Optional typed context forwarded to the LLM: focus_areas, ltv, "
            "contribution_margin, revenue_monthly. Unknown keys are silently dropped."
        ),
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

    @model_validator(mode="before")
    @classmethod
    def coerce_additional_inputs(cls, values: Any) -> Any:
        """
        If the frontend sends additional_inputs as a plain dict (legacy clients),
        pass it straight through — Pydantic will coerce it into AdditionalInputs.
        If it is missing or None, substitute an empty dict so AdditionalInputs
        can apply its own defaults.
        """
        if isinstance(values, dict):
            if values.get("additional_inputs") is None:
                values["additional_inputs"] = {}
        return values

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
                    "revenue_monthly": 450000,
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

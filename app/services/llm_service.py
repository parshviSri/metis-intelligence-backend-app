"""
services/llm_service.py
──────────────────────────────────────────────────────────────────────────────
LLM service for the Metis Intelligence diagnostic platform.

Public interface
────────────────
  generate_report(data: dict) -> str

Returns a JSON string with the shape:
  {
    "health_score": <int 0-100>,
    "insights":        [{"category": str, "text": str}, ...],
    "recommendations": [{"priority": "high|medium|low", "action": str, "rationale": str}, ...]
  }

Execution path
──────────────
1. If LLM_MOCK_MODE=true  → deterministic mock (no API call)
2. If OPENAI_API_KEY set   → real OpenAI call with JSON mode
3. On any OpenAI error     → log warning, fall back to mock

The mock is data-aware: it derives numbers from the actual submitted KPIs so
the frontend always renders meaningful content even without an API key.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.utils import calculate_health_score, safe_float

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(data: dict[str, Any]) -> str:
    """
    Generate a structured business diagnostic report.

    Parameters
    ----------
    data : dict
        Validated + normalised request payload (output of DiagnosticRequest.model_dump()).

    Returns
    -------
    str
        JSON-encoded report string.  Always valid JSON.
    """
    from app.core.config import get_settings

    settings = get_settings()

    # Mock-mode bypass
    if settings.llm_mock_mode:
        logger.info("LLM_MOCK_MODE enabled — returning mock report")
        return _mock_report(data)

    # Live OpenAI call
    try:
        return _openai_report(data, settings)
    except Exception as exc:
        logger.warning(
            "OpenAI call failed — falling back to mock report. Error: %s",
            exc,
            exc_info=True,
        )
        return _mock_report(data)


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI path
# ─────────────────────────────────────────────────────────────────────────────

def _openai_report(data: dict[str, Any], settings: Any) -> str:
    """Call the OpenAI Chat Completions API with JSON mode."""
    import openai

    client = openai.OpenAI(api_key=settings.openai_api_key)
    prompt = _build_prompt(data)

    logger.info("Calling OpenAI model '%s' for diagnostic report", settings.llm_model)

    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior business analyst specialising in D2C, SaaS, and "
                    "services businesses. You always respond with valid JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=1500,
    )

    raw = response.choices[0].message.content or ""
    logger.info("OpenAI response received (%d chars)", len(raw))

    # Validate structure before returning
    parsed = json.loads(raw)
    _validate_llm_output(parsed)
    return raw


def _build_prompt(data: dict[str, Any]) -> str:
    """
    Construct a focused, structured prompt for the LLM.

    The prompt instructs the model to return a specific JSON schema and
    provides all relevant KPIs in a clean tabular format.
    """
    aov            = safe_float(data.get("aov"))
    margin         = safe_float(data.get("margin"))
    cac            = safe_float(data.get("cac"))
    rpr            = safe_float(data.get("repeat_purchase_rate"))
    marketing_spend = safe_float(data.get("marketing_spend"))
    conversion_rate = safe_float(data.get("conversion_rate"))
    channels        = data.get("channels", [])
    business_name   = data.get("business_name", "the business")
    business_type   = data.get("business_type", "")
    products        = data.get("products", "")
    challenge       = data.get("biggest_challenge", "")

    # Derived metrics for context
    roas = (aov * (margin / 100) / cac) if cac > 0 else 0
    ltv_est = (aov * rpr / 100) * 3 if rpr > 0 else aov

    return f"""
Analyse the following business diagnostic data for {business_name} and return a JSON report.

BUSINESS CONTEXT
────────────────
Business Name  : {business_name}
Business Type  : {business_type}
Products       : {products}
Primary Challenge: {challenge}

KEY METRICS
───────────
Average Order Value (AOV)  : {aov:,.0f}
Gross Margin               : {margin:.1f}%
Monthly Marketing Spend    : {marketing_spend:,.0f}
Customer Acquisition Cost  : {cac:,.0f}
Repeat Purchase Rate       : {rpr:.1f}%
Conversion Rate            : {conversion_rate:.2f}%
Active Channels            : {", ".join(channels)}

DERIVED METRICS (for reference)
────────────────────────────────
ROAS (AOV × margin / CAC)  : {roas:.2f}x
Estimated 3-order LTV      : {ltv_est:,.0f}

OUTPUT FORMAT
─────────────
Return ONLY this JSON object (no markdown, no explanation):

{{
  "health_score": <integer 0-100>,
  "insights": [
    {{"category": "<string>", "text": "<string>"}},
    ...
  ],
  "recommendations": [
    {{"priority": "high|medium|low", "action": "<string>", "rationale": "<string>"}},
    ...
  ]
}}

RULES
─────
- health_score: 0 = business in crisis, 100 = exceptional. Weight CAC efficiency (30%), margin (25%), retention (25%), conversion (20%).
- Provide exactly 5-6 insights covering: unit economics, margin, retention, channel mix, conversion, and the stated challenge.
- Provide exactly 4-5 recommendations ordered by priority (high first).
- Every insight and recommendation must reference specific numbers from the data above.
- Be direct, data-driven, and founder-friendly. Avoid generic advice.
- Return ONLY the JSON object.
"""


def _validate_llm_output(parsed: dict) -> None:
    """Raise ValueError if the LLM response is missing required keys."""
    if "health_score" not in parsed:
        raise ValueError("LLM response missing 'health_score'")
    if "insights" not in parsed or not isinstance(parsed["insights"], list):
        raise ValueError("LLM response missing or invalid 'insights'")
    if "recommendations" not in parsed or not isinstance(parsed["recommendations"], list):
        raise ValueError("LLM response missing or invalid 'recommendations'")


# ─────────────────────────────────────────────────────────────────────────────
# Rich mock report  (data-aware, deterministic)
# ─────────────────────────────────────────────────────────────────────────────

def _mock_report(data: dict[str, Any]) -> str:
    """
    Build a realistic mock report driven by the actual submitted KPIs.

    No API call is made.  The score is computed by utils.calculate_health_score().
    Insights and recommendations are templated from the real numbers so the
    frontend renders meaningful content during local development / CI.
    """
    aov              = safe_float(data.get("aov"))
    margin           = safe_float(data.get("margin"))
    cac              = safe_float(data.get("cac"))
    rpr              = safe_float(data.get("repeat_purchase_rate"))
    marketing_spend  = safe_float(data.get("marketing_spend"))
    conversion       = safe_float(data.get("conversion_rate"))
    channels: list   = data.get("channels", [])
    business_name    = data.get("business_name", "Your Business")
    challenge        = data.get("biggest_challenge", "scaling efficiently")

    # Derived
    roas     = (aov * (margin / 100) / cac) if cac > 0 else 0
    ltv_est  = (aov * rpr / 100) * 3 if rpr > 0 else aov
    score    = calculate_health_score(data)

    # ── Insights ──────────────────────────────────────────────────────────
    insights = [
        {
            "category": "Unit Economics",
            "text": (
                f"Your AOV of ₹{aov:,.0f} vs. CAC of ₹{cac:,.0f} delivers an estimated "
                f"ROAS of {roas:.1f}x. "
                + (
                    "This is healthy — every rupee spent on acquisition returns more than 1.5x in gross profit."
                    if roas >= 1.5
                    else "This is below the 1.5x break-even threshold. Review ad creative, targeting, and landing-page alignment."
                )
            ),
        },
        {
            "category": "Margin Health",
            "text": (
                f"At {margin:.0f}% gross margin "
                + (
                    "you have strong pricing power and room to invest in growth without margin erosion."
                    if margin >= 50
                    else "you have limited buffer. A 5pp margin improvement — via pricing or COGS renegotiation — could add significant EBITDA."
                )
            ),
        },
        {
            "category": "Customer Retention",
            "text": (
                f"A repeat-purchase rate of {rpr:.0f}% translates to an estimated 3-order LTV of ₹{ltv_est:,.0f}. "
                + (
                    "Strong retention — invest in a loyalty programme to push this above 40%."
                    if rpr >= 30
                    else "Low retention is your biggest compounding risk. A 10pp improvement in RPR could double LTV without additional ad spend."
                )
            ),
        },
        {
            "category": "Marketing Efficiency",
            "text": (
                f"Monthly marketing spend of ₹{marketing_spend:,.0f} across {len(channels)} channel(s) "
                f"({', '.join(channels[:3])}{'…' if len(channels) > 3 else ''}). "
                + (
                    "Good channel diversification reduces platform risk."
                    if len(channels) >= 3
                    else "Concentration in fewer channels increases platform dependency. Test one additional organic or referral channel."
                )
            ),
        },
        {
            "category": "Conversion Efficiency",
            "text": (
                f"A site conversion rate of {conversion:.2f}% "
                + (
                    "is above the 2% industry benchmark — maintain focus on UX and offer clarity."
                    if conversion >= 2.0
                    else "is below the industry average of 2%. A structured CRO programme (landing-page tests, checkout optimisation, social proof) could lift revenue by 20-40% on existing traffic."
                )
            ),
        },
        {
            "category": "Primary Challenge",
            "text": (
                f"Your stated challenge — \"{challenge}\" — is directly addressed in the recommendations below. "
                "The quantitative data above confirms this is the highest-leverage area to resolve first."
            ),
        },
    ]

    # ── Recommendations ────────────────────────────────────────────────────
    recommendations = []

    if roas < 1.5:
        recommendations.append({
            "priority": "high",
            "action": "Audit and restructure paid acquisition spend",
            "rationale": (
                f"With a ROAS of {roas:.1f}x you are likely losing money on new customer acquisition. "
                f"Pause the bottom 20% of ad sets by ROAS, and reallocate ₹{marketing_spend * 0.20:,.0f} "
                "to your best-performing creative and audience combination."
            ),
        })

    if rpr < 25:
        recommendations.append({
            "priority": "high",
            "action": "Launch a post-purchase retention sequence",
            "rationale": (
                f"At {rpr:.0f}% RPR you are leaving ₹{ltv_est:,.0f} of potential LTV unrealised. "
                "Implement a 3-touch email win-back flow: Day 7 (education), Day 21 (social proof), "
                "Day 45 (10% loyalty incentive). Target 5pp RPR uplift in 90 days."
            ),
        })

    if margin < 45:
        recommendations.append({
            "priority": "medium",
            "action": "Improve gross margin by 5pp within one quarter",
            "rationale": (
                f"Lifting margin from {margin:.0f}% to {margin + 5:.0f}% on existing revenue "
                "adds direct profit without growing topline. Levers: renegotiate top-3 supplier contracts, "
                "reduce packaging cost, or introduce a premium bundle SKU at higher price."
            ),
        })

    if conversion < 2.0:
        recommendations.append({
            "priority": "medium",
            "action": "Run a 6-week CRO sprint on the top-traffic landing page",
            "rationale": (
                f"Improving conversion from {conversion:.2f}% to 2.5% on current traffic is equivalent "
                "to a 25-39% revenue increase with zero additional ad spend. Focus: above-the-fold value "
                "proposition clarity, social proof placement, and 1-step checkout."
            ),
        })

    if len(channels) < 3:
        recommendations.append({
            "priority": "medium",
            "action": "Add one organic acquisition channel in the next 60 days",
            "rationale": (
                "Diversifying beyond paid channels reduces CAC volatility. "
                "Short-form video (Reels / YouTube Shorts) or SEO content targeting high-intent keywords "
                "can build compounding zero-CAC traffic within 3-6 months."
            ),
        })

    recommendations.append({
        "priority": "low",
        "action": f"Build a 90-day execution roadmap for {business_name}",
        "rationale": (
            "Sequence the above actions: Month 1 = retention sequence + ad audit; "
            "Month 2 = CRO sprint; Month 3 = new channel experiment. "
            "Set weekly KPI check-ins (CAC, RPR, CVR) and adjust budget allocation dynamically."
        ),
    })

    report = {
        "health_score": score,
        "insights": insights,
        "recommendations": recommendations,
    }

    return json.dumps(report, ensure_ascii=False)

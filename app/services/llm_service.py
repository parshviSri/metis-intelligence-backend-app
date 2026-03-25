"""
services/llm_service.py
──────────────────────────────────────────────────────────────────────────────
LLM service for the Metis Intelligence diagnostic platform.

Public interface
────────────────
  generate_report(data: dict, prompt_version: str = "v1") -> str

Returns a JSON string with the shape:
  {
    "health_score": <int 0-100>,
    "insights":        [{"category": str, "text": str}, ...],
    "recommendations": [{"priority": "high|medium|low", "action": str, "rationale": str}, ...]
  }

Execution path
──────────────
1. If LLM_MOCK_MODE=true  → deterministic mock (no API call)
2. Otherwise              → call_llm() dispatches to the configured provider
3. On any LLM error       → log warning, fall back to mock

Provider / model registry
─────────────────────────
• Controlled via environment variables (see Settings in core/config.py):
    LLM_PROVIDER    – "openai" (default) | future: "anthropic", "gemini"
    LLM_MODEL_TIER  – "cheap" | "default" (default) | "premium"
    LLM_MAX_TOKENS  – max completion tokens (default 1500)
    LLM_TEMPERATURE – sampling temperature (default 0.4)
• Add a new provider by registering it in PROVIDER_CONFIGS and adding an
  elif branch in call_llm().

Prompt versioning
──────────────────
• PROMPTS dict holds versioned system-prompt templates ("v1", "v2", …).
• Pass prompt_version="v2" from the route layer to use the lightweight prompt
  (lower token cost).  Defaults to "v1" (richest, most data-aware prompt).
• New prompt variants can be added without touching call_llm() or routes.

Cost optimisation
─────────────────
• Compact JSON serialisation of KPI data (no whitespace padding).
• max_tokens cap controlled per-call from settings.
• Low temperature (0.4) reduces stochastic verbosity.
• Optional response caching: see TODO below.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.logging import get_logger
from app.utils import calculate_health_score, safe_float

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Provider / model registry
# Add new providers here; switch with LLM_PROVIDER env-var.
# ─────────────────────────────────────────────────────────────────────────────

PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "openai": {
        "model_tiers": {
            "cheap":   "gpt-4o-mini",
            "default": "gpt-4o-mini",
            "premium": "gpt-4o",
        },
    },
    # Future providers – uncomment and implement call_llm() branch:
    # "anthropic": {
    #     "model_tiers": {
    #         "cheap":   "claude-3-haiku-20240307",
    #         "default": "claude-3-5-sonnet-20241022",
    #         "premium": "claude-3-5-sonnet-20241022",
    #     },
    # },
    # "gemini": {
    #     "model_tiers": {
    #         "cheap":   "gemini-1.5-flash",
    #         "default": "gemini-1.5-pro",
    #         "premium": "gemini-1.5-pro",
    #     },
    # },
}


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# Keep as minimal as possible; every extra token costs money at scale.
# ─────────────────────────────────────────────────────────────────────────────

PROMPTS: dict[str, str] = {
    # v1 – Rich, data-aware prompt.  Best quality, higher token use.
    "v1": """Analyse the following business diagnostic data for {business_name} and return a JSON report.

BUSINESS CONTEXT
────────────────
Business Name    : {business_name}
Business Type    : {business_type}
Products         : {products}
Primary Challenge: {challenge}

KEY METRICS
───────────
Average Order Value (AOV)  : {aov:,.0f}
Gross Margin               : {margin:.1f}%
Monthly Marketing Spend    : {marketing_spend:,.0f}
Customer Acquisition Cost  : {cac:,.0f}
Repeat Purchase Rate       : {rpr:.1f}%
Conversion Rate            : {conversion_rate:.2f}%
Active Channels            : {channels}

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
- health_score: Weight CAC efficiency (30%), margin (25%), retention (25%), conversion (20%).
- Provide exactly 5-6 insights covering unit economics, margin, retention, channel mix, conversion, and the stated challenge.
- Provide exactly 4-5 recommendations ordered by priority (high first).
- Every insight and recommendation must reference specific numbers from the data.
- Be direct, data-driven, and founder-friendly. Avoid generic advice.
- Return ONLY the JSON object.""",

    # v2 – Compact prompt.  Fewer tokens, slightly less detailed output.
    # Use when cost is the primary concern (e.g., high-volume batch runs).
    "v2": (
        "You are a business analyst. Analyse this diagnostic data and reply ONLY with a JSON object "
        "using exactly these keys: "
        "\"health_score\" (int 0-100, weight CAC 30% margin 25% retention 25% conversion 20%), "
        "\"insights\" (list of {{\"category\": str, \"text\": str}}, 5 items), "
        "\"recommendations\" (list of {{\"priority\": \"high|medium|low\", \"action\": str, \"rationale\": str}}, 4 items). "
        "Be concise and data-driven. No markdown.\n\n"
        "Data (JSON): {compact_data}"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_model(settings: Any) -> str:
    """Resolve the model name from the provider registry and the active tier.

    Parameters
    ----------
    settings : Settings
        Application settings loaded from environment variables.

    Returns
    -------
    str
        Model identifier to pass to the LLM API.

    Raises
    ------
    ValueError
        If the configured LLM_PROVIDER is not registered in PROVIDER_CONFIGS.
    """
    provider = settings.llm_provider
    provider_cfg = PROVIDER_CONFIGS.get(provider)
    if provider_cfg is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            f"Registered providers: {list(PROVIDER_CONFIGS)}"
        )
    tiers = provider_cfg["model_tiers"]
    tier  = settings.llm_model_tier
    # Fall back to "default" tier if an unrecognised tier is requested.
    return tiers.get(tier, tiers["default"])


def _build_prompt(data: dict[str, Any], prompt_version: str) -> str:
    """Render the prompt template for *prompt_version* with the KPI data.

    Parameters
    ----------
    data :
        Validated + normalised request payload dict.
    prompt_version :
        Key into :data:`PROMPTS` (e.g. ``"v1"``, ``"v2"``).

    Returns
    -------
    str
        Fully rendered prompt string ready to send to the LLM.

    Raises
    ------
    ValueError
        When *prompt_version* is not a registered key in :data:`PROMPTS`.
    """
    template = PROMPTS.get(prompt_version)
    if template is None:
        raise ValueError(
            f"Unknown prompt_version '{prompt_version}'. "
            f"Available versions: {list(PROMPTS)}"
        )

    aov             = safe_float(data.get("aov"))
    margin          = safe_float(data.get("margin"))
    cac             = safe_float(data.get("cac"))
    rpr             = safe_float(data.get("repeat_purchase_rate"))
    marketing_spend = safe_float(data.get("marketing_spend"))
    conversion_rate = safe_float(data.get("conversion_rate"))
    channels        = data.get("channels", [])
    business_name   = data.get("business_name", "the business")
    business_type   = data.get("business_type", "")
    products        = data.get("products", "")
    challenge       = data.get("biggest_challenge", "")

    # Derived metrics used by v1 and referenced in v2's compact data.
    roas    = (aov * (margin / 100) / cac) if cac > 0 else 0
    ltv_est = (aov * rpr / 100) * 3 if rpr > 0 else aov

    if prompt_version == "v2":
        # For v2 we serialise everything as compact JSON to minimise tokens.
        compact_data = json.dumps(
            {
                "business_name": business_name,
                "business_type": business_type,
                "products": products,
                "biggest_challenge": challenge,
                "aov": aov,
                "margin_pct": margin,
                "marketing_spend": marketing_spend,
                "cac": cac,
                "repeat_purchase_rate_pct": rpr,
                "conversion_rate_pct": conversion_rate,
                "channels": channels,
                "roas": round(roas, 2),
                "ltv_est": round(ltv_est, 0),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return template.format(compact_data=compact_data)

    # v1 (and any future rich-format prompts) use named placeholders.
    return template.format(
        business_name=business_name,
        business_type=business_type,
        products=products,
        challenge=challenge,
        aov=aov,
        margin=margin,
        marketing_spend=marketing_spend,
        cac=cac,
        rpr=rpr,
        conversion_rate=conversion_rate,
        channels=", ".join(channels),
        roas=roas,
        ltv_est=ltv_est,
    )


def _validate_llm_output(parsed: dict) -> None:
    """Raise ValueError if the LLM response is missing required top-level keys.

    Parameters
    ----------
    parsed : dict
        JSON-decoded LLM response.

    Raises
    ------
    ValueError
        If any of ``health_score``, ``insights``, or ``recommendations`` are
        absent or of the wrong type.
    """
    if "health_score" not in parsed:
        raise ValueError("LLM response missing 'health_score'")
    if "insights" not in parsed or not isinstance(parsed["insights"], list):
        raise ValueError("LLM response missing or invalid 'insights'")
    if "recommendations" not in parsed or not isinstance(parsed["recommendations"], list):
        raise ValueError("LLM response missing or invalid 'recommendations'")


# ─────────────────────────────────────────────────────────────────────────────
# LLM call layer
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(prompt: str, settings: Any | None = None) -> str:
    """Send *prompt* to the configured LLM provider and return raw text.

    Design goals
    ────────────
    • Provider-agnostic: the caller never imports a provider SDK directly.
    • Retries once on transient failure with a 2-second back-off before
      re-raising so upstream callers can decide on fallback strategy.
    • ``max_tokens`` and ``temperature`` are driven by Settings, not hard-coded,
      so they can be tuned without code changes.

    Parameters
    ----------
    prompt :
        Fully rendered prompt string to send to the model.
    settings :
        Application settings.  Loaded automatically if not supplied (useful
        for unit tests that patch ``get_settings``).

    Returns
    -------
    str
        Raw text content from the LLM response (never None; empty string on
        empty response).

    Raises
    ------
    Exception
        Re-raised if the API call fails on both the initial attempt and the
        single retry.
    NotImplementedError
        If the configured LLM_PROVIDER has no implementation branch below.
    """
    if settings is None:
        from app.core.config import get_settings  # noqa: PLC0415
        settings = get_settings()

    model       = _get_model(settings)
    max_tokens  = settings.llm_max_tokens
    temperature = settings.llm_temperature
    provider    = settings.llm_provider

    def _attempt() -> str:
        if provider == "openai":
            import openai  # noqa: PLC0415

            client = openai.OpenAI(api_key=settings.openai_api_key)
            logger.info(
                "Calling OpenAI model '%s' (tier=%s max_tokens=%d temp=%.1f)",
                model, settings.llm_model_tier, max_tokens, temperature,
            )
            response = client.chat.completions.create(
                model=model,
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
                temperature=temperature,
                max_tokens=max_tokens,
            )
            raw = response.choices[0].message.content or ""
            logger.info("OpenAI response received (%d chars)", len(raw))
            return raw

        # ── Future providers ──────────────────────────────────────────────
        # elif provider == "anthropic":
        #     import anthropic
        #     client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        #     message = client.messages.create(
        #         model=model, max_tokens=max_tokens,
        #         messages=[{"role": "user", "content": prompt}],
        #     )
        #     return message.content[0].text

        raise NotImplementedError(
            f"LLM provider '{provider}' is registered in PROVIDER_CONFIGS but "
            "has no implementation branch in call_llm(). Add an elif block."
        )

    try:
        return _attempt()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "LLM call failed (%s). Retrying once in 2 s …", exc, exc_info=True
        )
        time.sleep(2)
        return _attempt()  # Second failure propagates to the caller.


# ─────────────────────────────────────────────────────────────────────────────
# Public entry-point
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(data: dict[str, Any], prompt_version: str = "v1") -> str:
    """Generate a structured business diagnostic report.

    Execution path
    ──────────────
    1. If ``LLM_MOCK_MODE=true`` → return a rich, data-aware mock (no API call).
    2. Otherwise → build the prompt, call the LLM, validate the response.
    3. On any LLM error → log a warning and fall back to the mock.

    Parameters
    ----------
    data :
        Validated + normalised request payload (output of
        ``DiagnosticRequest.model_dump()`` passed through ``normalise_payload``).
    prompt_version :
        Which prompt template to use.  ``"v1"`` (default) is the richest and
        most data-aware.  ``"v2"`` is a compact, token-efficient variant.
        Pass ``prompt_version`` from the route layer to allow per-request
        control without changing the service signature.

    Returns
    -------
    str
        JSON-encoded report string.  Always valid JSON.

    Example
    -------
    >>> report_json = generate_report(payload, prompt_version="v2")
    >>> report = json.loads(report_json)
    >>> report["health_score"]
    72
    """
    # TODO: cache based on input hash
    # import hashlib
    # cache_key = hashlib.sha256(
    #     json.dumps(data, sort_keys=True).encode()
    # ).hexdigest()
    # if cached := _cache.get(cache_key):
    #     logger.info("Cache hit for diagnostic (key=%s)", cache_key[:8])
    #     return cached

    from app.core.config import get_settings  # noqa: PLC0415

    settings = get_settings()

    # ── Mock-mode bypass ──────────────────────────────────────────────────
    if settings.llm_mock_mode:
        logger.info("LLM_MOCK_MODE enabled — returning mock report")
        return _mock_report(data)

    # ── Live LLM call ─────────────────────────────────────────────────────
    try:
        prompt = _build_prompt(data, prompt_version)
        raw    = call_llm(prompt, settings)

        parsed = json.loads(raw)
        _validate_llm_output(parsed)

        logger.info(
            "Report generated via LLM (provider=%s tier=%s prompt=%s "
            "health_score=%s insights=%d recs=%d)",
            settings.llm_provider,
            settings.llm_model_tier,
            prompt_version,
            parsed.get("health_score"),
            len(parsed.get("insights", [])),
            len(parsed.get("recommendations", [])),
        )
        return raw

    except Exception as exc:
        logger.warning(
            "LLM path failed — falling back to mock report. Error: %s",
            exc,
            exc_info=True,
        )
        return _mock_report(data)


# ─────────────────────────────────────────────────────────────────────────────
# Rich mock report  (data-aware, deterministic)
# ─────────────────────────────────────────────────────────────────────────────

def _mock_report(data: dict[str, Any]) -> str:
    """Build a realistic mock report driven by the actual submitted KPIs.

    No API call is made.  The score is computed by
    :func:`utils.calculate_health_score`.  Insights and recommendations are
    templated from the real numbers so the frontend renders meaningful content
    during local development / CI.

    Parameters
    ----------
    data : dict
        Normalised diagnostic payload.

    Returns
    -------
    str
        JSON-encoded mock report string (same schema as the live LLM report).
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
    roas    = (aov * (margin / 100) / cac) if cac > 0 else 0
    ltv_est = (aov * rpr / 100) * 3 if rpr > 0 else aov
    score   = calculate_health_score(data)

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
    recommendations: list[dict[str, str]] = []

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

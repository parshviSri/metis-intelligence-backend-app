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
            # Official OpenAI models (default — used when OPENAI_BASE_URL is not set):
            # gpt-4o-mini → lowest cost, fastest
            # gpt-4o-mini → balanced cost/quality (recommended default)
            # gpt-4o      → highest quality, higher cost
            #
            # If using the GenSpark proxy (OPENAI_BASE_URL set), swap to:
            # cheap=gpt-5-nano, default=gpt-5-mini, premium=gpt-5
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
    # v1 – Rich, data-aware prompt with strict consultant persona.
    # Best quality; use for all standard diagnostic runs.
    "v1": """BUSINESS DATA
─────────────
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

DERIVED METRICS
───────────────
Gross Profit ROAS (AOV × margin% / CAC) : {gross_profit_roas:.2f}x
Estimated LTV (geometric series)        : {ltv_est:,.0f}
{additional_section}
STRICT RULES — read before generating:
1. Diagnose performance using ONLY the data above.
2. Do NOT calculate or invent any numbers not provided or derived above.
3. Do NOT assume missing data.
4. Do NOT give generic advice (e.g. "improve marketing", "optimise website").
5. Every recommendation must be specific and immediately executable.
6. Every insight and recommendation must cite at least one specific number from the data.
7. If a claim cannot be supported by the data, do not include it.
8. Identify the highest-leverage problems first.

HEALTH SCORE WEIGHTS: CAC efficiency 30% · Gross margin 25% · Retention 25% · Conversion 20%.

OUTPUT — return ONLY this JSON, no markdown, no explanation:
{{
  "health_score": <integer 0-100>,
  "insights": [
    {{"category": "<string>", "text": "<one concise sentence citing a specific number>"}},
    ... (exactly 5 insights covering: unit economics, margin, retention, channel mix, conversion)
  ],
  "recommendations": [
    {{"priority": "high|medium|low", "action": "<specific executable step>", "rationale": "<why, citing data>"}},
    ... (exactly 4 recommendations, ordered high → low priority; address focus_areas if provided)
  ]
}}""",

    # v2 – Compact prompt with the same strict consultant persona.
    # Fewer tokens; use for cost-sensitive or high-volume batch runs.
    "v2": (
        "You are a senior D2C growth consultant. "
        "Diagnose the business using ONLY the provided data. "
        "Do NOT invent numbers, assume missing data, or give generic advice. "
        "Every insight and recommendation must cite a specific number from the input. "
        "Reply ONLY with a JSON object — no markdown, no explanation — with exactly these keys: "
        "\"health_score\" (int 0-100; weights: CAC efficiency 30%, margin 25%, retention 25%, conversion 20%), "
        "\"insights\" (list of 5 {{\"category\": str, \"text\": str}} items, each citing a specific metric), "
        "\"recommendations\" (list of 4 {{\"priority\": \"high|medium|low\", \"action\": str, \"rationale\": str}} items, "
        "ordered high first, specific and executable, address focus_areas if present).\n\n"
        "Data: {compact_data}"
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


def _derive_metrics(
    aov: float,
    margin: float,
    cac: float,
    rpr: float,
) -> tuple[float, float]:
    """Compute the two derived financial metrics injected into every prompt.

    Both metrics replace the previous approximations with financially correct
    formulations:

    gross_profit_roas
        = AOV × (margin / 100) / CAC

        Previously labelled "ROAS" but that is conventionally revenue/spend.
        Renaming to *Gross Profit ROAS* makes the formula transparent to the
        LLM and avoids it contradicting the number with its own ROAS estimate.

    ltv_est  (geometric series LTV)
        = (AOV × margin%) / (1 − retention_rate)

        The previous formula assumed exactly 3 repeat orders for every
        customer, which overestimates LTV at low RPR and wildly underestimates
        it at high RPR.  The geometric series is the standard DCF-free LTV
        model under a constant retention assumption.
        retention_rate is capped at 0.95 to keep LTV finite.

    Parameters
    ----------
    aov    : Average Order Value
    margin : Gross margin percentage (0–100)
    cac    : Customer Acquisition Cost
    rpr    : Repeat Purchase Rate percentage (0–100)

    Returns
    -------
    (gross_profit_roas, ltv_est)
    """
    gross_profit_roas = (aov * (margin / 100) / cac) if cac > 0 else 0.0

    retention_rate = min(rpr / 100, 0.95)   # cap at 95% — LTV → ∞ otherwise
    gross_profit_per_order = aov * (margin / 100)
    if retention_rate > 0:
        ltv_est = gross_profit_per_order / (1 - retention_rate)
    else:
        ltv_est = gross_profit_per_order   # single-purchase customer

    return gross_profit_roas, ltv_est


def _build_additional_section(additional: dict[str, Any]) -> str:
    """Render the optional ADDITIONAL CONTEXT block for v1 prompts.

    Reads the known typed keys from ``additional_inputs`` (after
    ``normalise_payload`` has serialised the Pydantic model to a plain dict)
    and formats them as labelled lines.  Any unrecognised keys that survived
    normalisation are appended as a compact JSON blob so no data is silently
    dropped.

    Returns an empty string when ``additional`` is empty, so the v1 prompt
    renders cleanly with no stray blank sections.

    Parameters
    ----------
    additional : dict
        Plain dict produced by ``normalise_payload`` from ``AdditionalInputs``.

    Returns
    -------
    str
        Multi-line section string (including leading newline) or ``""``.
    """
    if not additional:
        return ""

    lines: list[str] = []
    known_keys: set[str] = set()

    # ── focus_areas ───────────────────────────────────────────────────────
    if "focus_areas" in additional and additional["focus_areas"]:
        areas = ", ".join(additional["focus_areas"])
        lines.append(f"Focus Areas              : {areas}")
        known_keys.add("focus_areas")

    # ── founder-reported LTV ──────────────────────────────────────────────
    if "ltv" in additional:
        ltv_val = safe_float(additional["ltv"])
        lines.append(f"Founder-Reported LTV     : {ltv_val:,.0f}")
        known_keys.add("ltv")

    # ── contribution margin ───────────────────────────────────────────────
    if "contribution_margin" in additional:
        cm = safe_float(additional["contribution_margin"])
        lines.append(f"Contribution Margin      : {cm:.1f}%")
        known_keys.add("contribution_margin")

    # ── monthly revenue ───────────────────────────────────────────────────
    if "revenue_monthly" in additional:
        rev = safe_float(additional["revenue_monthly"])
        lines.append(f"Monthly Revenue          : {rev:,.0f}")
        known_keys.add("revenue_monthly")

    # ── any remaining unrecognised keys (future-proofing) ─────────────────
    remaining = {k: v for k, v in additional.items() if k not in known_keys}
    if remaining:
        lines.append(
            f"Other Context            : "
            f"{json.dumps(remaining, separators=(',', ':'), ensure_ascii=False)}"
        )

    if not lines:
        return ""

    body = "\n".join(lines)
    return f"\nADDITIONAL CONTEXT\n──────────────────\n{body}\n"


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

    # ── Extract raw KPIs ──────────────────────────────────────────────────
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
    additional      = data.get("additional_inputs") or {}

    # ── Derived metrics (financially correct formulations) ────────────────
    gross_profit_roas, ltv_est = _derive_metrics(aov, margin, cac, rpr)

    if prompt_version == "v2":
        # For v2 serialise everything as compact JSON to minimise tokens.
        compact_data = json.dumps(
            {
                "business_name":          business_name,
                "business_type":          business_type,
                "products":               products,
                "biggest_challenge":      challenge,
                "aov":                    aov,
                "margin_pct":             margin,
                "marketing_spend":        marketing_spend,
                "cac":                    cac,
                "repeat_purchase_rate_pct": rpr,
                "conversion_rate_pct":    conversion_rate,
                "channels":               channels,
                # Corrected derived metrics
                "gross_profit_roas":      round(gross_profit_roas, 2),
                "ltv_est_geometric":      round(ltv_est, 0),
                # additional_inputs — merged at top level for compact layout
                **({"focus_areas": additional["focus_areas"]} if additional.get("focus_areas") else {}),
                **({"founder_ltv": additional["ltv"]} if "ltv" in additional else {}),
                **({"contribution_margin_pct": additional["contribution_margin"]} if "contribution_margin" in additional else {}),
                **({"revenue_monthly": additional["revenue_monthly"]} if "revenue_monthly" in additional else {}),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return template.format(compact_data=compact_data)

    # ── v1: rich tabular prompt with optional ADDITIONAL CONTEXT section ───
    additional_section = _build_additional_section(additional)

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
        gross_profit_roas=gross_profit_roas,
        ltv_est=ltv_est,
        additional_section=additional_section,
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

            # Pass base_url when provided so requests are routed through an
            # OpenAI-compatible proxy (e.g. GenSpark LLM gateway).
            # base_url=None lets the SDK use the official OpenAI endpoint.
            client_kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                client_kwargs["base_url"] = settings.openai_base_url

            client = openai.OpenAI(**client_kwargs)
            logger.info(
                "Calling OpenAI model '%s' (tier=%s max_tokens=%d temp=%.1f base_url=%s)",
                model, settings.llm_model_tier, max_tokens, temperature,
                settings.openai_base_url or "official",
            )
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a senior D2C growth consultant with expertise in performance "
                            "marketing, unit economics, and retention strategy. "
                            "Your job is to: (1) diagnose business performance using ONLY the "
                            "provided data, (2) identify the highest-leverage problems, "
                            "(3) recommend specific, actionable interventions. "
                            "STRICT RULES: do NOT calculate or invent numbers unless explicitly "
                            "provided, do NOT assume missing data, do NOT generate generic advice. "
                            "Every recommendation must be specific and executable. "
                            "OUTPUT MUST BE VALID JSON. NO extra text."
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

    # Derived — use the same corrected formulas as _derive_metrics() so the
    # mock and live paths are numerically consistent.
    gross_profit_roas, ltv_est = _derive_metrics(aov, margin, cac, rpr)
    score = calculate_health_score(data)

    # ── Insights ──────────────────────────────────────────────────────────
    insights = [
        {
            "category": "Unit Economics",
            "text": (
                f"Your AOV of ₹{aov:,.0f} vs. CAC of ₹{cac:,.0f} delivers a gross profit ROAS of "
                f"{gross_profit_roas:.1f}x. "
                + (
                    "This is healthy — every rupee spent on acquisition returns more than 1.5x in gross profit."
                    if gross_profit_roas >= 1.5
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
                f"A repeat-purchase rate of {rpr:.0f}% translates to an estimated LTV of ₹{ltv_est:,.0f} "
                f"(geometric series model). "
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

    if gross_profit_roas < 1.5:
        recommendations.append({
            "priority": "high",
            "action": "Audit and restructure paid acquisition spend",
            "rationale": (
                f"With a gross profit ROAS of {gross_profit_roas:.1f}x you are likely losing money on "
                f"new customer acquisition. Pause the bottom 20% of ad sets by ROAS, and reallocate "
                f"₹{marketing_spend * 0.20:,.0f} to your best-performing creative and audience combination."
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

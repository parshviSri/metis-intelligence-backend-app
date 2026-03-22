"""
utils/__init__.py
──────────────────────────────────────────────────────────────────────────────
Utility helpers for the Metis Intelligence backend.

Exports
───────
normalise_payload(data)  – clean / coerce a raw dict before DB storage
calculate_health_score() – deterministic score from core KPIs (used as
                           fallback when the LLM does not return a score)
clamp(value, lo, hi)     – constrain a number to [lo, hi]
safe_float(v, default)   – silent conversion to float
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Numeric helpers
# ─────────────────────────────────────────────────────────────────────────────

def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    """Return value clamped to [lo, hi] and rounded to the nearest integer."""
    return int(max(lo, min(hi, round(value))))


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Convert *value* to float without raising.
    Returns *default* for None, empty string, or non-numeric inputs.
    """
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Payload normaliser
# ─────────────────────────────────────────────────────────────────────────────

def normalise_payload(data: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitise and coerce a raw request dict before persisting to the DB or
    passing to the LLM service.

    Rules
    ─────
    • All string fields are stripped of leading / trailing whitespace.
    • Numeric fields are coerced to float (0.0 on failure).
    • channels is guaranteed to be a list[str] with no blank entries.
    • additional_inputs defaults to an empty dict if absent.

    Returns a new dict; the original is not mutated.
    """
    clean: dict[str, Any] = {}

    # Strings
    for key in ("business_name", "business_type", "products", "biggest_challenge"):
        raw = data.get(key, "")
        clean[key] = raw.strip() if isinstance(raw, str) else str(raw).strip()

    # Floats
    for key in ("aov", "margin", "marketing_spend", "cac",
                "repeat_purchase_rate", "conversion_rate"):
        clean[key] = safe_float(data.get(key), default=0.0)

    # Channels – accept list or comma-separated string
    raw_channels = data.get("channels", [])
    if isinstance(raw_channels, list):
        clean["channels"] = [str(c).strip() for c in raw_channels if str(c).strip()]
    elif isinstance(raw_channels, str):
        clean["channels"] = [c.strip() for c in raw_channels.split(",") if c.strip()]
    else:
        clean["channels"] = []

    # Catch-all
    clean["additional_inputs"] = data.get("additional_inputs") or {}

    return clean


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic health-score calculator
# ─────────────────────────────────────────────────────────────────────────────

def calculate_health_score(data: dict[str, Any]) -> int:
    """
    Compute a deterministic 0-100 business health score from core KPIs.

    Used as a fallback when the LLM response cannot be parsed.

    Scoring dimensions
    ──────────────────
    1. CAC efficiency  (CAC / AOV ratio)      — up to ±15 pts
    2. Gross margin                            — up to ±15 pts
    3. Customer retention                      — up to ±12 pts
    4. Conversion rate                         — up to ±8  pts
    Baseline: 50 pts
    """
    aov    = safe_float(data.get("aov"))
    margin = safe_float(data.get("margin"))
    cac    = safe_float(data.get("cac"))
    rpr    = safe_float(data.get("repeat_purchase_rate"))
    cr     = safe_float(data.get("conversion_rate"))

    score: float = 50.0

    # 1. CAC / AOV efficiency
    if aov > 0 and cac > 0:
        ratio = cac / aov
        if ratio < 0.30:
            score += 15
        elif ratio < 0.50:
            score += 10
        elif ratio < 0.80:
            score += 5
        elif ratio < 1.00:
            score += 0
        elif ratio < 1.50:
            score -= 8
        else:
            score -= 15

    # 2. Gross margin
    if margin >= 65:
        score += 15
    elif margin >= 50:
        score += 10
    elif margin >= 35:
        score += 4
    elif margin >= 20:
        score += 0
    else:
        score -= 10

    # 3. Repeat-purchase rate (retention proxy)
    if rpr >= 50:
        score += 12
    elif rpr >= 35:
        score += 8
    elif rpr >= 20:
        score += 3
    elif rpr >= 10:
        score += 0
    else:
        score -= 8

    # 4. Conversion rate
    if cr >= 4.0:
        score += 8
    elif cr >= 2.5:
        score += 5
    elif cr >= 1.5:
        score += 2
    elif cr >= 0.5:
        score += 0
    else:
        score -= 5

    return clamp(score)

from __future__ import annotations

from typing import Any


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalise_payload(data: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}

    clean["user_id"] = safe_int(data.get("user_id"), default=None)
    clean["email"] = str(data.get("email", "")).strip() or None
    clean["analysis_type"] = str(data.get("analysis_type", "full_diagnostic")).strip() or "full_diagnostic"

    for key in ("business_name", "business_type", "products", "biggest_challenge"):
        raw = data.get(key, "")
        clean[key] = raw.strip() if isinstance(raw, str) else str(raw).strip()

    for key in ("aov", "margin", "marketing_spend", "cac", "repeat_purchase_rate", "conversion_rate"):
        clean[key] = safe_float(data.get(key), default=0.0)

    raw_channels = data.get("channels", [])
    if isinstance(raw_channels, list):
        clean["channels"] = [str(c).strip() for c in raw_channels if str(c).strip()]
    elif isinstance(raw_channels, str):
        clean["channels"] = [c.strip() for c in raw_channels.split(",") if c.strip()]
    else:
        clean["channels"] = []

    raw_additional = data.get("additional_inputs") or {}
    if hasattr(raw_additional, "model_dump"):
        additional = raw_additional.model_dump()
    elif isinstance(raw_additional, dict):
        additional = dict(raw_additional)
    else:
        additional = {}

    clean["additional_inputs"] = {
        key: value
        for key, value in additional.items()
        if value is not None and value != [] and value != {}
    }

    return clean


def calculate_health_score(data: dict[str, Any]) -> int:
    aov = safe_float(data.get("aov"))
    margin = safe_float(data.get("margin"))
    cac = safe_float(data.get("cac"))
    rpr = safe_float(data.get("repeat_purchase_rate"))
    cr = safe_float(data.get("conversion_rate"))

    score: float = 50.0

    if aov > 0 and cac > 0:
        ratio = cac / aov
        if ratio < 0.30:
            score += 15
        elif ratio < 0.50:
            score += 10
        elif ratio < 0.80:
            score += 5
        elif ratio < 1.50:
            score -= 8
        else:
            score -= 15

    if margin >= 65:
        score += 15
    elif margin >= 50:
        score += 10
    elif margin >= 35:
        score += 4
    elif margin < 20:
        score -= 10

    if rpr >= 50:
        score += 12
    elif rpr >= 35:
        score += 8
    elif rpr >= 20:
        score += 3
    elif rpr < 10:
        score -= 8

    if cr >= 4.0:
        score += 8
    elif cr >= 2.5:
        score += 5
    elif cr >= 1.5:
        score += 2
    elif cr < 0.5:
        score -= 5

    return clamp(score)

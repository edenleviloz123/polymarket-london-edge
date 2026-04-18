"""
ליבת הלוגיקה הכמותית:
טמפ' חזויה (μ) + פיזור (σ) → הסתברות P(bucket) דרך ההתפלגות הנורמלית.
Edge = P_חזויה − מחיר_YES.  Kelly לגודל פוזיציה.
"""
import math
from typing import List, Optional

from scipy.stats import norm

from config import (
    EDGE_THRESHOLD_BUY, EDGE_THRESHOLD_STRONG,
    MIN_SIGMA, PRICE_MAX_TRADABLE, PRICE_MIN_TRADABLE,
)


def bucket_probability(bucket: dict, mu: float, sigma: float) -> float:
    """
    P שהטמפ' המקסימלית המעוגלת תיפול בתוך ה-bucket, תחת N(μ, σ).
    'below' = T ≤ t      → CDF(t + 0.5)            (continuity correction)
    'single' = T == t    → CDF(t+0.5) − CDF(t−0.5)
    'above' = T ≥ t      → 1 − CDF(t − 0.5)
    """
    t = bucket["temp"]
    btype = bucket["type"]
    if btype == "below":
        return float(norm.cdf(t + 0.5, loc=mu, scale=sigma))
    if btype == "above":
        return float(1.0 - norm.cdf(t - 0.5, loc=mu, scale=sigma))
    return float(
        norm.cdf(t + 0.5, loc=mu, scale=sigma)
        - norm.cdf(t - 0.5, loc=mu, scale=sigma)
    )


def kelly_fraction(p: float, yes_price: float) -> float:
    """
    גודל הימור אופטימלי לקנייה של YES במחיר yes_price כשההסתברות האמיתית היא p.
    b = (1 − price) / price = יחס התשלום.  f* = (b·p − (1−p)) / b.
    תוצאה נחתכת ל-[0, 1].
    """
    if yes_price <= 0 or yes_price >= 1:
        return 0.0
    b = (1.0 - yes_price) / yes_price
    f = (b * p - (1.0 - p)) / b
    return max(0.0, min(1.0, f))


def expected_value(p: float, yes_price: float) -> float:
    """EV של $1 המושקע ב-YES: p·(1/price) − 1."""
    if yes_price <= 0:
        return 0.0
    return p * (1.0 / yes_price) - 1.0


def compute_edges(contracts: List[dict], mu: float, sigma: Optional[float]) -> List[dict]:
    """
    σ אפקטיבי = max(σ_בין-מודלים, MIN_SIGMA).
    כך חוסר-הסכמה בין מודלים מגדיל את אי-הוודאות — ולא רק פרמטר קבוע.
    """
    effective_sigma = max(sigma or 0.0, MIN_SIGMA)
    results = []
    for c in contracts:
        p    = bucket_probability(c["bucket"], mu, effective_sigma)
        edge = p - c["yes_price"]
        results.append({
            **c,
            "our_prob":        p,
            "edge":            edge,
            "kelly":           kelly_fraction(p, c["yes_price"]),
            "ev":              expected_value(p, c["yes_price"]),
            "effective_sigma": effective_sigma,
        })
    return results


def classify_signal(edges: List[dict]) -> dict:
    """מחפש את ההזדמנות הטובה ביותר בין כל ה-buckets."""
    if not edges:
        return {"action": "NO_DATA", "best": None,
                "rationale": "אין חוזים זמינים לניתוח."}
    # רק חוזים שעדיין סחירים בטווח סביר
    tradable = [e for e in edges
                if PRICE_MIN_TRADABLE < e["yes_price"] < PRICE_MAX_TRADABLE]
    if not tradable:
        return {"action": "HOLD", "best": None,
                "rationale": "כל החוזים מעבר לטווח הסחיר — מחירים ≈0 או ≈1."}

    best = max(tradable, key=lambda e: e["edge"])

    if best["edge"] >= EDGE_THRESHOLD_STRONG:
        action = "STRONG_BUY"
    elif best["edge"] >= EDGE_THRESHOLD_BUY:
        action = "BUY"
    elif best["edge"] <= -EDGE_THRESHOLD_BUY:
        action = "AVOID"
    else:
        action = "HOLD"

    return {"action": action, "best": best,
            "rationale": _rationale(best, action)}


def _rationale(best: dict, action: str) -> str:
    label = best["bucket"]["label"]
    p     = best["our_prob"]
    px    = best["yes_price"]
    edge  = best["edge"]
    core  = (f"החוזה «{label}»: הסתברות חזויה {p*100:.1f}% "
             f"מול מחיר YES בשוק {px*100:.1f}% — יתרון {edge*100:+.2f}%.")
    if action == "STRONG_BUY":
        return f"{core} איתות קנייה חזק (Kelly≈{best['kelly']*100:.1f}% מהבנקרול, EV={best['ev']*100:+.1f}%)."
    if action == "BUY":
        return f"{core} איתות קנייה (Kelly≈{best['kelly']*100:.1f}% מהבנקרול)."
    if action == "AVOID":
        return f"{core} השוק מתמחר יתר — עדיף לקנות NO או להתרחק."
    return f"{core} היתרון מתחת לסף הפעולה (3%)."

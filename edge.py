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
    MIN_PROB_FOR_BUY, MIN_SIGMA,
    PRICE_MAX_TRADABLE, PRICE_MIN_TRADABLE,
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
    """
    מחפש את ההזדמנות הטובה ביותר בין כל ה-buckets תוך שמירה על שני תנאים:
    (1) יתרון (Edge) מעל הסף, (2) ההסתברות שלנו ל-bucket הזה ≥ MIN_PROB_FOR_BUY.
    התנאי השני מונע המלצת קנייה על "זנב" לא-סביר רק בגלל מחיר שוק זול.
    מחזיר גם את ה-bucket הכי סביר לפי המודל, כדי לתת למשתמש פרספקטיבה כפולה.
    """
    empty = {
        "action":         "NO_DATA",
        "best":           None,
        "most_likely":    None,
        "best_edge":      None,
        "qualified_best": None,
        "rationale":      "אין חוזים זמינים לניתוח.",
    }
    if not edges:
        return empty

    # רק חוזים שעדיין סחירים בטווח סביר
    tradable = [e for e in edges
                if PRICE_MIN_TRADABLE < e["yes_price"] < PRICE_MAX_TRADABLE]
    if not tradable:
        return {**empty, "action": "HOLD",
                "rationale": "כל החוזים מעבר לטווח הסחיר — מחירים ≈0 או ≈1."}

    most_likely = max(tradable, key=lambda e: e["our_prob"])
    best_edge   = max(tradable, key=lambda e: e["edge"])
    worst_edge  = min(tradable, key=lambda e: e["edge"])

    # מועמדים לקנייה: רק buckets שגם סבירים מספיק אצלנו
    buy_candidates = [e for e in tradable
                      if e["our_prob"] >= MIN_PROB_FOR_BUY]
    qualified_best = (max(buy_candidates, key=lambda e: e["edge"])
                      if buy_candidates else None)

    # קביעת הפעולה
    action, best = "HOLD", None
    if qualified_best is not None:
        if qualified_best["edge"] >= EDGE_THRESHOLD_STRONG:
            action, best = "STRONG_BUY", qualified_best
        elif qualified_best["edge"] >= EDGE_THRESHOLD_BUY:
            action, best = "BUY", qualified_best

    # אם אין הזדמנות קנייה מוצדקת — בדוק תמחור-יתר
    if best is None and worst_edge["edge"] <= -EDGE_THRESHOLD_BUY:
        action, best = "AVOID", worst_edge

    return {
        "action":         action,
        "best":           best,
        "most_likely":    most_likely,
        "best_edge":      best_edge,
        "qualified_best": qualified_best,
        "rationale":      _rationale(action, best, most_likely,
                                     best_edge, qualified_best),
    }


def _describe_bucket(e: dict) -> str:
    """טקסט תמציתי לחוזה יחיד."""
    return (f"«{e['bucket']['label']}» "
            f"(הסתברות {e['our_prob']*100:.1f}%, "
            f"שוק {e['yes_price']*100:.1f}%)")


def _rationale(action: str, best, most_likely, best_edge, qualified_best) -> str:
    ml_part = (f"ה-bucket הסביר ביותר לפי המודל הוא "
               f"{_describe_bucket(most_likely)}.")
    if action in ("STRONG_BUY", "BUY") and best is not None:
        core = (f"החוזה {_describe_bucket(best)}: "
                f"יתרון {best['edge']*100:+.2f}%, "
                f"Kelly≈{best['kelly']*100:.1f}% מהבנקרול, "
                f"EV={best['ev']*100:+.1f}%.")
        if best_edge is not None and best_edge is not best:
            extra = (f" קיים bucket עם יתרון גבוה יותר "
                     f"({_describe_bucket(best_edge)}, "
                     f"יתרון {best_edge['edge']*100:+.2f}%) — "
                     f"אך ההסתברות שלו מתחת ל-30% ולכן סוננה.")
            core += extra
        return f"{core} {ml_part}"

    if action == "AVOID" and best is not None:
        return (f"השוק מתמחר יתר את {_describe_bucket(best)} "
                f"(יתרון {best['edge']*100:+.2f}%). עדיף לקנות NO או להתרחק. "
                f"{ml_part}")

    # HOLD
    if qualified_best is None and best_edge is not None and best_edge['edge'] >= EDGE_THRESHOLD_BUY:
        return (f"היתרון הגדול ביותר הוא ב-{_describe_bucket(best_edge)} "
                f"({best_edge['edge']*100:+.2f}%), אך ההסתברות שלו נמוכה "
                f"מסף הפעולה (30%) — לכן לא ממליצים לקנות. {ml_part}")
    return (f"אין יתרון מספיק כדי להצדיק פעולה "
            f"(סף 3% ביתרון + 30% בהסתברות). {ml_part}")

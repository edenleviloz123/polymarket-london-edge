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
    ENSEMBLE_AGREEMENT_MAX_C,
    MAX_PROB_FOR_BUY, MIN_PRICE_FOR_BUY, MIN_PROB_FOR_BUY, MIN_SIGMA,
    PRICE_MAX_TRADABLE, PRICE_MIN_TRADABLE,
)


# σ אפקטיבי של "השיא בשעות שנותרו" סביב התחזית השעתית.
# ערך קטן יחסית כי תחזית לשעות הקרובות (עד 6 שעות) מדויקת למדי,
# במיוחד בשעות הצינון של הערב. ערך גדול מדי מנפח הסתברויות בקצוות.
POST_PEAK_SIGMA = 0.25


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


def bucket_probability_metar(bucket: dict,
                              observed_max_int: int,
                              remaining_mu: Optional[float],
                              remaining_sigma: float) -> float:
    """
    הסתברות ל-bucket בהינתן:
      - observed_max_int: מקסימום METAR שנמדד עד עכשיו (מספר שלם, °C)
      - remaining_mu: תחזית לשיא בשעות שנותרו (°C, המשכי) או None אם היום נגמר
      - remaining_sigma: אי-ודאות של התחזית לשעות הנותרות

    המקסימום היומי הוא max(observed_max_int, future_peak). future_peak הוא
    משתנה מקרי שאת ההתפלגות שלו (כ-N(remaining_mu, remaining_sigma)) מביאים
    מהתחזית השעתית של Open-Meteo. ה-METAR בסוף היום יוכרע על ידי round של
    ה-future_peak אם הוא עוקף את observed_max_int.
    """
    t = bucket["temp"]
    btype = bucket["type"]
    m = observed_max_int

    # ── אם אין שעות שנותרו (יום נגמר מבחינת תחזית) ──
    if remaining_mu is None:
        # היום נסגר עם observed_max_int כתוצאה הסופית
        if btype == "below":
            return 1.0 if m <= t else 0.0
        if btype == "above":
            return 1.0 if m >= t else 0.0
        return 1.0 if m == t else 0.0

    # ── יש שעות שנותרו: daily_max = max(m, future_peak) ──
    sigma = max(remaining_sigma, 1e-6)

    def P_future_le(x: float) -> float:
        """P(future_peak ≤ x)."""
        return float(norm.cdf(x, loc=remaining_mu, scale=sigma))

    def P_future_in(lo: float, hi: float) -> float:
        """P(lo ≤ future_peak ≤ hi)."""
        return max(0.0, P_future_le(hi) - P_future_le(lo))

    if btype == "below":
        # daily_max_int ≤ t  ⇔  m ≤ t ו-future_peak < t + 0.5
        if m > t:
            return 0.0
        return P_future_le(t + 0.5)

    if btype == "above":
        # daily_max_int ≥ t  ⇔  m ≥ t או future_peak ≥ t - 0.5
        if m >= t:
            return 1.0
        return 1.0 - P_future_le(t - 0.5)

    # single t
    if m > t:
        return 0.0
    if m == t:
        # daily = t אם-ורק-אם future_peak < t + 0.5
        return P_future_le(t + 0.5)
    # m < t: daily = t אם-ורק-אם future_peak ∈ [t-0.5, t+0.5]
    return P_future_in(t - 0.5, t + 0.5)


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


def compute_edges(contracts: List[dict], mu: float, sigma: Optional[float],
                   observation: Optional[dict] = None,
                   ensemble_std: Optional[float] = None) -> List[dict]:
    """
    מחשב Edge לכל חוזה.

    שני מסלולי חישוב:

    (1) observation-aware (ליום הנוכחי):
        observation כולל observed_max_int מ-METAR + remaining_forecast_max.
        החישוב: daily_max_int = max(observed_max_int, round(future_peak))
        כאשר future_peak ~ N(remaining_mu, POST_PEAK_SIGMA).

    (2) forecast-only (ליום עתידי):
        μ מהקונצנזוס של 5 מודלים.
        σ אפקטיבי = max(σ_בין-מודלים, σ_ensemble, MIN_SIGMA).
        σ_ensemble הוא מדד סטטיסטי אמיתי של אי-ודאות (מ-50 חברי ECMWF EPS).
    """
    results = []
    observed_max_int = None
    remaining_mu = None
    remaining_sigma = POST_PEAK_SIGMA
    post_peak = False

    if observation and observation.get("observed_max_int") is not None:
        observed_max_int = int(observation["observed_max_int"])
        rem_fc = observation.get("remaining_forecast_max")
        remaining_mu = rem_fc
        if rem_fc is None or observed_max_int >= rem_fc:
            post_peak = True

    # σ אפקטיבי למסלול forecast-only: המקסימום מבין שלושה מדדים
    sigma_sources = [sigma or 0.0, ensemble_std or 0.0, MIN_SIGMA]
    eff_sigma_forecast = max(sigma_sources)

    for c in contracts:
        if observed_max_int is not None:
            p = bucket_probability_metar(
                c["bucket"], observed_max_int, remaining_mu, remaining_sigma)
            eff_sigma = remaining_sigma
        else:
            eff_sigma = eff_sigma_forecast
            p = bucket_probability(c["bucket"], mu, eff_sigma)
        edge = p - c["yes_price"]
        results.append({
            **c,
            "our_prob":          p,
            "edge":              edge,
            "kelly":             kelly_fraction(p, c["yes_price"]),
            "ev":                expected_value(p, c["yes_price"]),
            "effective_sigma":   eff_sigma,
            "observed_max_used": observed_max_int,
            "post_peak":         post_peak,
        })
    return results


def classify_signal(edges: List[dict],
                     ensemble: Optional[dict] = None) -> dict:
    """
    האסטרטגיה הראשית: most_likely (ה-bucket עם ההסתברות הגבוהה ביותר).
    בנתונים שצברנו, אסטרטגיה זו נתנה ROI עקבי של ~25% לעומת ~9% של max_edge,
    ולכן היא הופכת לכלי הראשי לקביעת ההמלצה בדשבורד.

    תנאי קנייה (על most_likely):
      - הסתברות שלנו ≥ MIN_PROB_FOR_BUY
      - יתרון (Edge) ≥ EDGE_THRESHOLD_BUY (3%)

    אם most_likely לא עובר את התנאים, בודקים אם יש bucket עם תמחור-יתר חמור
    (worst_edge ≤ -3%) ואז מציגים AVOID. אחרת HOLD.

    max_edge עדיין מחושב ומוצג כ"חלופה" בדשבורד, ולוג ה-paper-trading
    ממשיך לרשום אותו כאסטרטגיה שנייה כדי שנוכל להשוות.
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

    tradable = [e for e in edges
                if PRICE_MIN_TRADABLE < e["yes_price"] < PRICE_MAX_TRADABLE]
    if not tradable:
        return {**empty, "action": "HOLD",
                "rationale": "כל החוזים מעבר לטווח הסחיר — מחירים ≈0 או ≈1."}

    most_likely = max(tradable, key=lambda e: e["our_prob"])
    best_edge   = max(tradable, key=lambda e: e["edge"])
    worst_edge  = min(tradable, key=lambda e: e["edge"])

    # סינון אנסמבלים: אם ECMWF ו-GEFS לא מסכימים, אי-הוודאות גבוהה מדי
    if ensemble:
        agreement = ensemble.get("agreement_c")
        if agreement is not None and agreement > ENSEMBLE_AGREEMENT_MAX_C:
            return {
                "action":         "HOLD",
                "best":           None,
                "most_likely":    most_likely,
                "best_edge":      best_edge,
                "qualified_best": None,
                "rationale":      (f"חוסר הסכמה בין האנסמבלים — פער של "
                                    f"{agreement:.2f}°C בין ECMWF ל-GEFS, "
                                    f"מעבר לסף ההסכמה ({ENSEMBLE_AGREEMENT_MAX_C}°C). "
                                    f"אי-הוודאות גבוהה מדי, אין קנייה."),
            }

    # סינוני איכות שנלמדו מההיסטוריה (תוצרי ניתוח 288 איתותים):
    # 1) חסום הימור עם prob >= 95% — 0/7 ניצחו כשהמערכת אמרה "100% בטוח"
    # 2) חסום הימור עם מחיר שוק < 5% — 0/20 ניצחו במחירים האלה
    def _quality_filter_reason(b):
        if b is None:
            return None
        if b["our_prob"] >= MAX_PROB_FOR_BUY:
            return f"הסתברות גבוהה מדי ({b['our_prob']*100:.0f}% ≥ {MAX_PROB_FOR_BUY*100:.0f}%)"
        if b["yes_price"] < MIN_PRICE_FOR_BUY:
            return f"מחיר שוק נמוך מדי ({b['yes_price']*100:.1f}% < {MIN_PRICE_FOR_BUY*100:.0f}%)"
        return None

    # האסטרטגיה הראשית: most_likely.
    # האם הוא עובר את שני התנאים: הסתברות וגם יתרון?
    action, best = "HOLD", None
    filter_reason = _quality_filter_reason(most_likely)
    if filter_reason:
        return {
            "action":         "HOLD",
            "best":           None,
            "most_likely":    most_likely,
            "best_edge":      best_edge,
            "qualified_best": None,
            "rationale":      (f"סינון איכות חסם את ההזדמנות: {filter_reason}. "
                                f"מבוסס על ניתוח 288 איתותים היסטוריים."),
        }
    ml_qualifies = (
        most_likely["our_prob"] >= MIN_PROB_FOR_BUY
        and most_likely["edge"] >= EDGE_THRESHOLD_BUY
    )
    if ml_qualifies:
        if most_likely["edge"] >= EDGE_THRESHOLD_STRONG:
            action, best = "STRONG_BUY", most_likely
        else:
            action, best = "BUY", most_likely

    # אם most_likely לא עובר — בדוק תמחור-יתר חמור על המודל הסביר
    if best is None and worst_edge["edge"] <= -EDGE_THRESHOLD_BUY:
        action, best = "AVOID", worst_edge

    # qualified_best — שמור על השם הישן כדי לא לשבור צרכנים אחרים;
    # מציין את ה-bucket שמצדיק את הפעולה (אם בכלל)
    qualified_best = best if action in ("BUY", "STRONG_BUY") else None

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
    """
    הנמקה תחת המדיניות החדשה: most_likely הוא הראשי. אם יש BUY,
    זה אוטומטית על most_likely. max_edge יכול להיות חלופה עם יתרון
    גדול יותר אבל פחות סביר.
    """
    if action in ("STRONG_BUY", "BUY") and best is not None:
        core = (f"החוזה הסביר ביותר {_describe_bucket(best)}: "
                f"יתרון {best['edge']*100:+.2f}%, "
                f"Kelly≈{best['kelly']*100:.1f}% מהבנקרול, "
                f"EV={best['ev']*100:+.1f}%. "
                f"זה הסיגנל הראשי כי עוקב אחרי ה-bucket עם ההסתברות הגבוהה ביותר.")
        # אם max_edge הוא bucket אחר עם יתרון גבוה יותר, מציעים אותו כחלופה
        if best_edge is not None and best_edge is not best \
                and best_edge["edge"] > best["edge"] + 0.05:
            extra = (f" חלופה: bucket {_describe_bucket(best_edge)} מציע "
                     f"יתרון גדול יותר ({best_edge['edge']*100:+.2f}%) "
                     f"אך עם הסתברות נמוכה יותר — סיכון/תמורה גבוה יותר.")
            core += extra
        return core

    if action == "AVOID" and best is not None:
        ml_part = (f"ה-bucket הסביר ביותר הוא {_describe_bucket(most_likely)}.")
        return (f"השוק מתמחר יתר את {_describe_bucket(best)} "
                f"(יתרון {best['edge']*100:+.2f}%). עדיף לקנות NO או להתרחק. "
                f"{ml_part}")

    # HOLD
    ml_str = _describe_bucket(most_likely) if most_likely else "—"
    ml_edge = (most_likely.get('edge', 0) * 100) if most_likely else 0
    if most_likely and most_likely["our_prob"] < MIN_PROB_FOR_BUY:
        return (f"ה-bucket הסביר ביותר הוא {ml_str} אבל ההסתברות שלו "
                f"מתחת לסף הקנייה (30%). אין אמון מספק להמליץ.")
    if most_likely and most_likely["edge"] < EDGE_THRESHOLD_BUY:
        return (f"ה-bucket הסביר ביותר הוא {ml_str} עם יתרון של {ml_edge:+.2f}% — "
                f"מתחת לסף 3%. השוק מתמחר אותו פחות-או-יותר נכון, "
                f"אין הזדמנות אמיתית.")
    return f"אין יתרון מספיק כדי להצדיק פעולה. ה-bucket הסביר ביותר: {ml_str}."

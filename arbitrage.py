"""
זיהוי הזדמנויות ארביטראז' בין חוזי bucket שמתנים זה את זה.

רציונל: באירוע של Polymarket עם 11 buckets לטמפרטורה, בדיוק אחד ינצח.
אם השוק מתמחר את הסט כולו באופן לא-עקבי (סכום מחירים רחוק מ-100%),
אפשר לבצע עסקה שבסוף היום מבטיחה רווח ללא תלות בתוצאה.

דיסקליימר חשוב:
- החישוב מבוסס על bestBid / bestAsk מ-Gamma API, אבל ה-CLOB בפועל
  יכול להיות רדוד. ייתכן שגודל הפוזיציה הנדרש יחרוג מהנזילות הזמינה.
- Polymarket גובה ~2% על המרת USDC בכניסה/יציאה.
- אם אחד החוזים אין לו bestBid או bestAsk — לא ניתן לחשב ארביטראז' מדויק.
"""
from typing import List, Optional

# הפרש מרוחק מספיק מ-100% כדי להחשיב הזדמנות ראויה
ARB_MIN_PROFIT = 0.02   # 2% רווח מובטח (לפני עמלות) כדי לסמן


def compute_arbitrage(contracts: List[dict]) -> Optional[dict]:
    """
    מזהה הזדמנות ארביטראז' בין buckets של אותו אירוע.

    שתי אסטרטגיות אפשריות:
      (A) BUY YES על כולם: עלות = sum(yes_ask), תשלום בסוף = 1.
          רווח = 1 - sum(yes_ask).  אפשרי רק אם יש ask לכל ה-buckets.
      (B) SELL YES על כולם (≡ BUY NO על כולם):
          סכום המכירה = sum(yes_bid), חייב לשלם 1 בסוף.
          רווח = sum(yes_bid) - 1.  אפשרי רק אם יש bid לכל ה-buckets.

    תמיד מחזיר מילון עם הסכומים והסטטוס; has_opportunity מופעל רק כשיש
    רווח תאורטי מעל ARB_MIN_PROFIT *וגם* כל הציטוטים הנדרשים קיימים.
    """
    if not contracts:
        return None
    n = len(contracts)

    bids = [c.get("yes_best_bid") for c in contracts]
    asks = [c.get("yes_best_ask") for c in contracts]
    missing_bids = sum(1 for v in bids if v is None)
    missing_asks = sum(1 for v in asks if v is None)
    sum_yes_bid_partial = sum(v for v in bids if v is not None)
    sum_yes_ask_partial = sum(v for v in asks if v is not None)

    # רווח תאורטי לכל אסטרטגיה — רק אם יש ציטוט מלא בצד הרלוונטי
    profit_sell_yes = profit_buy_yes = None
    if missing_bids == 0:
        profit_sell_yes = sum_yes_bid_partial - 1.0
    if missing_asks == 0:
        profit_buy_yes = 1.0 - sum_yes_ask_partial

    candidates = []
    if profit_sell_yes is not None and profit_sell_yes > 0:
        candidates.append(("sell_yes", profit_sell_yes, n - sum_yes_bid_partial))
    if profit_buy_yes is not None and profit_buy_yes > 0:
        candidates.append(("buy_yes", profit_buy_yes, sum_yes_ask_partial))

    if candidates:
        best_name, best_profit, best_cost = max(candidates, key=lambda x: x[1])
        roi = (best_profit / best_cost) if best_cost > 0 else 0.0
        has_opp = best_profit >= ARB_MIN_PROFIT
    else:
        best_name, best_profit, best_cost, roi = None, 0.0, 0.0, 0.0
        has_opp = False

    # הסבר מילולי למקרה שאין הזדמנות
    reason = None
    if not has_opp:
        parts = []
        if missing_bids:
            parts.append(f"{missing_bids}/{n} חוזים ללא bid")
        if missing_asks:
            parts.append(f"{missing_asks}/{n} חוזים ללא ask")
        if parts:
            reason = ("השוק רזה באחד הצדדים ("
                      + ", ".join(parts) + ") — אסטרטגיה זו לא אפשרית מלאה.")
        else:
            reason = (f"סכום המחירים (YES-bid={sum_yes_bid_partial:.3f}, "
                      f"YES-ask={sum_yes_ask_partial:.3f}) קרוב מדי ל-100%. "
                      f"ה-spread של השוק גדול מהמרווח הפוטנציאלי.")

    return {
        "n_buckets":         n,
        "sum_yes_bid":       sum_yes_bid_partial,
        "sum_yes_ask":       sum_yes_ask_partial,
        "missing_bids":      missing_bids,
        "missing_asks":      missing_asks,
        "profit_sell_yes":   profit_sell_yes,
        "profit_buy_yes":    profit_buy_yes,
        "best_strategy":     best_name,
        "best_profit_usd":   best_profit,
        "best_cost_usd":     best_cost,
        "roi":               roi,
        "has_opportunity":   has_opp,
        "reason_if_none":    reason,
    }

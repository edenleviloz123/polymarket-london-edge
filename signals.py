"""
מעקב איתותים (paper trading).

רעיון: כל פעם שהמערכת מוציאה איתות קנייה, רושמים אותו כעסקה מדומה
עם המחיר שהיה בשוק באותו רגע. כשהיום מסתיים, מצליבים מול METAR המדידה:
האם ה-bucket שהמלצנו ניצח? מחשבים רווח/הפסד ומצברים סטטיסטיקות.

זה לא מסחור אמיתי. זה ולידציה: כמה המערכת באמת מפיקה רווח לו הייתה
סוחרת. אחרי 30-50 איתותים זה יעיד בצורה אמינה אם יש edge אמיתי.
"""
import datetime as dt
import json
import logging
import os
from typing import Any, Dict, List, Optional

from config import (
    EDGE_THRESHOLD_BUY, KELLY_FRACTION, MIN_PROB_FOR_BUY,
    PAPER_BANKROLL_USD, SIGNALS_LOG, USER_TZ,
)

# שמות האסטרטגיות — שני תיקים מדומים מקבילים
STRATEGY_MAX_EDGE    = "max_edge"    # הימור על הפער הגדול ביותר
STRATEGY_MOST_LIKELY = "most_likely" # הימור על ה-bucket הסביר ביותר

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────

def _load() -> List[dict]:
    if not os.path.exists(SIGNALS_LOG):
        return []
    out = []
    with open(SIGNALS_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _save(rows: List[dict]) -> None:
    with open(SIGNALS_LOG, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


# ─────────────────────────────────────────────
# רישום איתות כעסקה מדומה
# ─────────────────────────────────────────────

def _signal_id(strategy: str, city_key: str, target_date: str,
               bucket_label: str) -> str:
    """מזהה ייחודי: (אסטרטגיה, עיר, יום, bucket). מאפשר שתי אסטרטגיות במקביל."""
    return f"{strategy}|{city_key}|{target_date}|{bucket_label}"


def _minutes_to_close(ts_iso: str, event_end: Optional[str]) -> Optional[int]:
    """מרחק בדקות בין ts_iso לזמן סגירת האירוע בפולימארקט (endDate)."""
    if not event_end:
        return None
    try:
        end_str = event_end.replace("Z", "+00:00") if event_end.endswith("Z") else event_end
        end_dt = dt.datetime.fromisoformat(end_str)
        ts_dt = dt.datetime.fromisoformat(ts_iso)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=dt.timezone.utc)
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=dt.timezone.utc)
        return max(0, int((end_dt - ts_dt).total_seconds() / 60))
    except Exception:
        return None


def _timing_bucket(minutes: Optional[int]) -> Optional[str]:
    """קטגוריזציה של איכות תזמון — מוקדם/אמצע/מאוחר."""
    if minutes is None:
        return None
    if minutes >= 480:
        return "early"       # יותר מ-8 שעות לפני סגירה
    if minutes >= 60:
        return "mid"         # בין שעה ל-8 שעות
    return "late"            # פחות משעה — שוק קרוב להתייצב


def _record_one(city_key: str, target_date: dt.date, strategy: str,
                 bucket_edge: dict, action: str, ts_iso: str,
                 event_end: Optional[str] = None) -> None:
    """רישום עסקה מדומה אחת עבור אסטרטגיה מסוימת."""
    bucket = bucket_edge.get("bucket") or {}
    label = bucket.get("label")
    if not label:
        return
    sid = _signal_id(strategy, city_key, target_date.isoformat(), label)

    rows = _load()
    # אם יש כבר איתות פתוח זהה (אסטרטגיה+עיר+יום+bucket) — לא כופלים
    for r in rows:
        if r.get("id") == sid and r.get("status") == "pending":
            return

    yes_price = float(bucket_edge.get("yes_price") or 0)
    our_prob  = float(bucket_edge.get("our_prob")  or 0)
    kelly     = float(bucket_edge.get("kelly")     or 0)
    edge      = float(bucket_edge.get("edge")      or 0)
    ev        = float(bucket_edge.get("ev")        or 0)

    stake_usd = max(0.0, KELLY_FRACTION * kelly * PAPER_BANKROLL_USD)
    if stake_usd < 1.0:
        stake_usd = 1.0

    minutes_to_close = _minutes_to_close(ts_iso, event_end)
    timing = _timing_bucket(minutes_to_close)

    rows.append({
        "id":                sid,
        "ts":                ts_iso,
        "strategy":          strategy,
        "city":              city_key,
        "target_date":       target_date.isoformat(),
        "action":            action,
        "bucket_label":      label,
        "bucket_type":       bucket.get("type"),
        "bucket_temp":       bucket.get("temp"),
        "yes_price":         yes_price,
        "our_prob":          our_prob,
        "edge":              edge,
        "kelly":             kelly,
        "ev":                ev,
        "stake_usd":         stake_usd,
        "minutes_to_close":  minutes_to_close,
        "timing":            timing,
        "status":            "pending",
        "outcome_pnl":       None,
        "observed_max":      None,
        "settled_at":        None,
    })
    _save(rows)
    log.info("נרשם איתות [%s|%s]: %s @ price=%.3f (stake $%.2f, %s דק׳ לסגירה)",
             strategy, timing or "?", sid, yes_price, stake_usd,
             minutes_to_close if minutes_to_close is not None else "?")


def record_signals(city_key: str, target_date: dt.date, signal: dict,
                    ts_iso: str, event_end: Optional[str] = None) -> None:
    """
    רושם עד שני איתותי paper-trading מקבילים:
    (1) max_edge — ה-bucket עם היתרון הגדול ביותר (הפעולה הראשית)
    (2) most_likely — ה-bucket הסביר ביותר לפי המודל, רק אם הוא
        שונה מ-(1) וגם בעצמו עובר את סף הקנייה (edge ≥ 3% והסתברות ≥ 30%).

    event_end הוא endDate של האירוע בפולימארקט (ISO); משמש לחישוב
    "דקות עד סגירה" לכל עסקה לצורך ניתוח איכות-תזמון בהמשך.
    """
    action = (signal or {}).get("action")
    if action not in ("BUY", "STRONG_BUY"):
        return

    best = signal.get("best") or {}
    most_likely = signal.get("most_likely") or {}
    best_label = (best.get("bucket") or {}).get("label")
    ml_label = (most_likely.get("bucket") or {}).get("label")

    if best_label:
        _record_one(city_key, target_date, STRATEGY_MAX_EDGE,
                     best, action, ts_iso, event_end=event_end)

    if ml_label and ml_label != best_label:
        ml_edge = float(most_likely.get("edge") or 0)
        ml_prob = float(most_likely.get("our_prob") or 0)
        if ml_edge >= EDGE_THRESHOLD_BUY and ml_prob >= MIN_PROB_FOR_BUY:
            ml_action = ("STRONG_BUY" if ml_edge >= 0.08 else "BUY")
            _record_one(city_key, target_date, STRATEGY_MOST_LIKELY,
                         most_likely, ml_action, ts_iso, event_end=event_end)


# ─────────────────────────────────────────────
# ישוב איתותים אחרי שסתיים היום
# ─────────────────────────────────────────────

def _bucket_won(bucket_type: str, bucket_temp: int,
                observed_max_int: int) -> bool:
    if bucket_type == "single":
        return observed_max_int == bucket_temp
    if bucket_type == "below":
        return observed_max_int <= bucket_temp
    if bucket_type == "above":
        return observed_max_int >= bucket_temp
    return False


def settle_pending_signals(observations: Dict[str, Dict[str, int]]) -> dict:
    """
    עבור כל איתות עם status=pending שיש לנו תצפית עבורו —
    מסמן won/lost ומחשב P&L.
    """
    rows = _load()
    now_iso = dt.datetime.now(USER_TZ).isoformat()
    settled = won = lost = 0

    for r in rows:
        if r.get("status") != "pending":
            continue
        city = r["city"]
        date = r["target_date"]
        if city not in observations or date not in observations[city]:
            continue
        obs = int(observations[city][date])
        won_flag = _bucket_won(r["bucket_type"], r["bucket_temp"], obs)
        stake = float(r["stake_usd"])
        price = float(r["yes_price"])
        if price <= 0:
            # לא ניתן לחשב P&L — משאירים פתוח
            continue
        if won_flag:
            pnl = stake * (1.0 - price) / price   # רווח נטו בדולרים
            r["status"] = "won"; won += 1
        else:
            pnl = -stake
            r["status"] = "lost"; lost += 1
        r["outcome_pnl"] = round(pnl, 4)
        r["observed_max"] = obs
        r["settled_at"] = now_iso
        settled += 1

    if settled:
        _save(rows)
        log.info("יושבו %d איתותים — %d זכיות, %d הפסדים", settled, won, lost)
    return {"settled": settled, "won": won, "lost": lost}


# ─────────────────────────────────────────────
# ביצועים מצטברים
# ─────────────────────────────────────────────

def _aggregate(rows: List[dict]) -> dict:
    """מחשב את קבוצת המדדים הסטנדרטית לרשימת איתותים נתונה."""
    if not rows:
        return {
            "total": 0, "pending": 0, "settled": 0, "won": 0, "lost": 0,
            "win_rate": None, "realized_pnl": 0.0, "expected_pnl": 0.0,
            "pending_stake": 0.0, "settled_stake": 0.0,
            "roi_on_settled_stake": None,
        }
    pending = [r for r in rows if r.get("status") == "pending"]
    settled = [r for r in rows if r.get("status") in ("won", "lost")]
    won  = [r for r in settled if r["status"] == "won"]

    realized_pnl = sum(r.get("outcome_pnl") or 0.0 for r in settled)
    settled_stake = sum(r.get("stake_usd") or 0.0 for r in settled)
    pending_stake = sum(r.get("stake_usd") or 0.0 for r in pending)
    expected_pnl = sum((r.get("stake_usd") or 0.0) * (r.get("ev") or 0.0)
                       for r in settled)
    return {
        "total":               len(rows),
        "pending":             len(pending),
        "settled":             len(settled),
        "won":                 len(won),
        "lost":                len(settled) - len(won),
        "win_rate":            (len(won) / len(settled)) if settled else None,
        "realized_pnl":        round(realized_pnl, 2),
        "expected_pnl":        round(expected_pnl, 2),
        "pending_stake":       round(pending_stake, 2),
        "settled_stake":       round(settled_stake, 2),
        "roi_on_settled_stake": (realized_pnl / settled_stake) if settled_stake > 0 else None,
    }


def compute_performance() -> dict:
    rows = _load()
    all_agg = _aggregate(rows)

    # פיצול לפי אסטרטגיה (max_edge vs most_likely)
    by_strategy: Dict[str, dict] = {}
    for s_name in (STRATEGY_MAX_EDGE, STRATEGY_MOST_LIKELY):
        strat_rows = [r for r in rows if r.get("strategy") == s_name]
        by_strategy[s_name] = _aggregate(strat_rows)

    # פיצול לפי תזמון (early / mid / late)
    by_timing: Dict[str, dict] = {}
    for t_name in ("early", "mid", "late"):
        t_rows = [r for r in rows if r.get("timing") == t_name]
        by_timing[t_name] = _aggregate(t_rows)

    # פיצול לפי עיר (על כל האסטרטגיות)
    per_city: Dict[str, dict] = {}
    for r in rows:
        c = r["city"]
        slot = per_city.setdefault(c, {"total": 0, "won": 0, "lost": 0,
                                        "pending": 0, "pnl": 0.0})
        slot["total"] += 1
        st = r.get("status", "pending")
        if st == "won":
            slot["won"] += 1
            slot["pnl"] += r.get("outcome_pnl") or 0.0
        elif st == "lost":
            slot["lost"] += 1
            slot["pnl"] += r.get("outcome_pnl") or 0.0
        else:
            slot["pending"] += 1

    result = {
        **all_agg,
        "by_strategy": by_strategy,
        "by_timing":   by_timing,
        "per_city":    per_city,
        "recent":      rows[-10:],
    }
    return result

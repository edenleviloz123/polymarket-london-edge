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
from typing import Dict, List, Optional

from config import (
    KELLY_FRACTION, PAPER_BANKROLL_USD, SIGNALS_LOG, USER_TZ,
)

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

def _signal_id(ts_iso: str, city_key: str, target_date: str,
               bucket_label: str) -> str:
    """מזהה ייחודי לאיתות — אותו (עיר, יום, bucket) לא ייושם יותר מפעם אחת."""
    return f"{city_key}|{target_date}|{bucket_label}"


def record_signals(city_key: str, target_date: dt.date, signal: dict,
                    ts_iso: str) -> None:
    """
    רושם את האיתות הנוכחי כעסקה מדומה — רק אם הפעולה היא קנייה.
    אם כבר קיים איתות זהה פתוח לאותו (city, date, bucket), לא נרשום כפול.
    """
    action = (signal or {}).get("action")
    if action not in ("BUY", "STRONG_BUY"):
        return
    best = signal.get("best") or {}
    bucket = best.get("bucket") or {}
    label = bucket.get("label")
    if not label:
        return

    sid = _signal_id(ts_iso, city_key, target_date.isoformat(), label)

    rows = _load()
    # אם יש כבר איתות פתוח לאותו (עיר+יום+bucket) — לא כופלים
    for r in rows:
        if r.get("id") == _signal_id(r.get("ts",""), r["city"],
                                       r["target_date"], r["bucket_label"]):
            pass
        existing_sid = f"{r['city']}|{r['target_date']}|{r['bucket_label']}"
        if existing_sid == f"{city_key}|{target_date.isoformat()}|{label}" \
                and r.get("status") == "pending":
            return   # כבר יש איתות פתוח זהה

    yes_price = float(best.get("yes_price") or 0)
    our_prob  = float(best.get("our_prob")  or 0)
    kelly     = float(best.get("kelly")     or 0)
    edge      = float(best.get("edge")      or 0)
    ev        = float(best.get("ev")        or 0)

    stake_usd = max(0.0, KELLY_FRACTION * kelly * PAPER_BANKROLL_USD)
    # גודל מינימום לפוזיציה מדומה — כדי למנוע "סטייק 0"
    if stake_usd < 1.0:
        stake_usd = 1.0

    rows.append({
        "id":             sid,
        "ts":             ts_iso,
        "city":           city_key,
        "target_date":    target_date.isoformat(),
        "action":         action,
        "bucket_label":   label,
        "bucket_type":    bucket.get("type"),
        "bucket_temp":    bucket.get("temp"),
        "yes_price":      yes_price,
        "our_prob":       our_prob,
        "edge":           edge,
        "kelly":          kelly,
        "ev":             ev,
        "stake_usd":      stake_usd,
        "status":         "pending",
        "outcome_pnl":    None,
        "observed_max":   None,
        "settled_at":     None,
    })
    _save(rows)
    log.info("נרשם איתות: %s — %s @ price=%.3f (stake $%.2f)",
             sid, action, yes_price, stake_usd)


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

def compute_performance() -> dict:
    rows = _load()
    if not rows:
        return {
            "total": 0, "pending": 0, "settled": 0,
            "won": 0, "lost": 0, "win_rate": None,
            "realized_pnl": 0.0, "pending_stake": 0.0,
            "roi_on_settled_stake": None,
            "expected_vs_realized": None,
            "per_city": {},
            "recent":  [],
        }

    pending = [r for r in rows if r.get("status") == "pending"]
    settled = [r for r in rows if r.get("status") in ("won", "lost")]
    won = [r for r in settled if r["status"] == "won"]
    lost = [r for r in settled if r["status"] == "lost"]

    realized_pnl = sum(r.get("outcome_pnl") or 0.0 for r in settled)
    settled_stake = sum(r.get("stake_usd") or 0.0 for r in settled)
    pending_stake = sum(r.get("stake_usd") or 0.0 for r in pending)

    # EV צפוי על הסטייק של העסקאות שהיו (לצורך השוואה)
    expected_pnl = sum((r.get("stake_usd") or 0.0) * (r.get("ev") or 0.0)
                       for r in settled)

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

    return {
        "total":               len(rows),
        "pending":             len(pending),
        "settled":             len(settled),
        "won":                 len(won),
        "lost":                len(lost),
        "win_rate":            (len(won) / len(settled)) if settled else None,
        "realized_pnl":        round(realized_pnl, 2),
        "expected_pnl":        round(expected_pnl, 2),
        "pending_stake":       round(pending_stake, 2),
        "settled_stake":       round(settled_stake, 2),
        "roi_on_settled_stake": (realized_pnl / settled_stake) if settled_stake > 0 else None,
        "per_city":            per_city,
        "recent":              rows[-10:],
    }

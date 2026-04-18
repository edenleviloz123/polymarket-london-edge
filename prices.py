"""
מעקב מחירי שוק לאורך זמן — snapshot של כל ה-buckets בכל אירוע פעיל
פעם ב-~30 דקות. מאפשר ניתוח "מתי השוק צודק יותר" ו-"מתי משתלם להיכנס"
אחרי שמצטברת היסטוריה של שבועיים-שלושה.

כל רישום הוא נקודה אחת: (city, target_date, bucket, ts) עם המחירים,
הנפח, וכמות הדקות לסגירה באותו רגע. אחרי שהיום נסגר (תצפית METAR
זמינה), אפשר לשאוב מהלוג הזה את הגרף של "איך התנהג המחיר של ה-bucket
המנצח לאורך היום".
"""
import datetime as dt
import json
import logging
import os
from typing import Any, List, Optional

from config import PRICES_LOG, PRICES_MIN_INTERVAL_MIN

log = logging.getLogger(__name__)


def _load() -> List[dict]:
    if not os.path.exists(PRICES_LOG):
        return []
    out = []
    with open(PRICES_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append_rows(rows_to_append: List[dict]) -> None:
    """רק מוסיף — לא כותב את כל הקובץ בכל פעם (קובץ עשוי לגדול)."""
    with open(PRICES_LOG, "a", encoding="utf-8") as f:
        for r in rows_to_append:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _minutes_to_close(ts_iso: str, event_end: Optional[str]) -> Optional[int]:
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


def _last_ts_for(rows: List[dict], city_key: str, target_date: str) -> Optional[dt.datetime]:
    """מחזיר את ה-ts האחרון שנרשם ל-(עיר, תאריך). מאפשר rate-limiting."""
    latest = None
    for r in rows:
        if r.get("city") != city_key or r.get("target_date") != target_date:
            continue
        ts = r.get("ts")
        if not ts:
            continue
        try:
            dt_ts = dt.datetime.fromisoformat(ts)
        except ValueError:
            continue
        if latest is None or dt_ts > latest:
            latest = dt_ts
    return latest


def record_market_snapshot(city_key: str, target_date: dt.date,
                            contracts: List[dict], edges: List[dict],
                            event_end: Optional[str], ts_iso: str) -> int:
    """
    רושם snapshot של כל ה-buckets לאירוע הזה, אם עברו לפחות
    PRICES_MIN_INTERVAL_MIN דקות מאז המדידה הקודמת לאותו (עיר, יום).

    edges — רשימת ה-edges המלאה עם our_prob כדי שנוכל לחסוך join בעתיד.
    מחזיר את מספר השורות שנוספו (0 אם עברנו rate-limit).
    """
    if not contracts:
        return 0

    td_iso = target_date.isoformat()
    rows = _load()
    last = _last_ts_for(rows, city_key, td_iso)
    if last is not None:
        try:
            now_dt = dt.datetime.fromisoformat(ts_iso)
            elapsed_min = (now_dt - last).total_seconds() / 60
            if elapsed_min < PRICES_MIN_INTERVAL_MIN:
                return 0
        except ValueError:
            pass

    mtc = _minutes_to_close(ts_iso, event_end)

    # אינדקס our_prob לפי bucket label, אם edges סופק
    our_prob_by_label = {}
    for e in (edges or []):
        label = (e.get("bucket") or {}).get("label")
        if label:
            our_prob_by_label[label] = e.get("our_prob")

    new_rows = []
    for c in contracts:
        bucket = c.get("bucket") or {}
        label = bucket.get("label")
        if not label:
            continue
        new_rows.append({
            "ts":               ts_iso,
            "city":             city_key,
            "target_date":      td_iso,
            "bucket_label":     label,
            "bucket_type":      bucket.get("type"),
            "bucket_temp":      bucket.get("temp"),
            "yes_price":        c.get("yes_price"),
            "yes_best_bid":     c.get("yes_best_bid"),
            "yes_best_ask":     c.get("yes_best_ask"),
            "volume":           c.get("volume"),
            "our_prob":         our_prob_by_label.get(label),
            "minutes_to_close": mtc,
        })

    if not new_rows:
        return 0
    _append_rows(new_rows)
    log.info("[prices] נרשם snapshot: %s %s — %d buckets (mtc=%s דק׳)",
             city_key, td_iso, len(new_rows), mtc)
    return len(new_rows)


def load_all() -> List[dict]:
    return _load()

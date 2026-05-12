"""
Persistence gate for paper-trading signals.

A signal is not recorded immediately. Instead we maintain a 'candidate'
per (strategy, city, target_date). The candidate must persist (same
bucket across multiple consecutive runs) for at least
PERSISTENCE_MIN_MINUTES before being promoted to a real signal record.

The Stage-1 data showed -60% ROI for noon signals — many of those were
short-lived 'flicker' signals where the top bucket changed every few
minutes. Persistence filters those out.
"""
import datetime as dt
import json
import logging
import os
from typing import Optional, Tuple

from config import (
    CANDIDATES_FILE, CANDIDATE_STALE_MINUTES, PERSISTENCE_MIN_MINUTES,
)

log = logging.getLogger(__name__)


def _load() -> dict:
    if not os.path.exists(CANDIDATES_FILE):
        return {}
    try:
        with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save(d: dict) -> None:
    with open(CANDIDATES_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, default=str)


def _key(strategy: str, city_key: str, target_date_iso: str) -> str:
    return f"{strategy}|{city_key}|{target_date_iso}"


def _minutes_between(earlier_iso: str, later_iso: str) -> float:
    try:
        a = dt.datetime.fromisoformat(earlier_iso)
        b = dt.datetime.fromisoformat(later_iso)
        return (b - a).total_seconds() / 60.0
    except Exception:
        return 0.0


def is_qualified(strategy: str, city_key: str, target_date,
                  bucket_label: str, ts_iso: str) -> Tuple[bool, float]:
    """
    מעדכן את מצב המועמד עבור (אסטרטגיה, עיר, תאריך) ומחזיר:
    (qualified, age_minutes)
    qualified=True רק כשהמועמד הנוכחי שאותו bucket התמיד מעל הסף.
    """
    td_iso = (target_date.isoformat() if not isinstance(target_date, str)
              else target_date)
    cands = _load()

    # ניקוי מועמדים שעברו זמן מאז ראייתם האחרונה
    fresh = {}
    for k, v in cands.items():
        last = v.get("last_seen", ts_iso)
        if _minutes_between(last, ts_iso) <= CANDIDATE_STALE_MINUTES:
            fresh[k] = v
    cands = fresh

    k = _key(strategy, city_key, td_iso)
    existing = cands.get(k)

    if existing and existing.get("bucket_label") == bucket_label:
        # אותו bucket — מעדכנים זמן ראייה אחרון, שומרים first_seen
        existing["last_seen"] = ts_iso
        existing["count"] = existing.get("count", 1) + 1
        age = _minutes_between(existing["first_seen"], ts_iso)
        cands[k] = existing
        _save(cands)
        return (age >= PERSISTENCE_MIN_MINUTES, age)
    else:
        # bucket חדש (או לא היה קודם) — מאתחלים מועמד
        cands[k] = {
            "bucket_label": bucket_label,
            "first_seen":   ts_iso,
            "last_seen":    ts_iso,
            "count":        1,
        }
        _save(cands)
        return (False, 0.0)


def candidate_age(strategy: str, city_key: str, target_date,
                   bucket_label: str) -> Optional[float]:
    """גיל המועמד הנוכחי בדקות (לצורך תיעוד/דשבורד), או None אם אין."""
    td_iso = (target_date.isoformat() if not isinstance(target_date, str)
              else target_date)
    cands = _load()
    existing = cands.get(_key(strategy, city_key, td_iso))
    if not existing or existing.get("bucket_label") != bucket_label:
        return None
    return _minutes_between(existing["first_seen"], existing["last_seen"])

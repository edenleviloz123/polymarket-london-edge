"""
מעקב דיוק מודלים לאורך זמן:
1. לוג תחזיות שנעשו בעבר (forecasts.jsonl)
2. שליפת טמפרטורה מקסימלית שנצפתה בפועל (observations.json)
3. חישוב מדדי דיוק לכל מודל (accuracy.json): MAE, הטיה, שיעור פגיעה בטווח 1°C
"""
import datetime as dt
import json
import logging
import os
import time
from typing import Dict, List, Optional

import requests

from config import (
    ACCURACY_HIT_WINDOW_C, ACCURACY_JSON, ACCURACY_MAX_DAYS,
    FORECASTS_LOG, HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT,
    LAT, LON, OBSERVATION_CUTOFF_HOURS, OBSERVATIONS_JSON,
    TEMP_SANITY_MAX, TEMP_SANITY_MIN, TIMEZONE, TIMEZONE_TZ,
    WEATHER_MODELS,
)

log = logging.getLogger(__name__)
ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# ─────────────────────────────────────────────
# שליפה של טמפ' שנצפתה בפועל (פוסט-רזולוציה)
# ─────────────────────────────────────────────

def _http_get(url: str, params: dict) -> dict:
    last = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(HTTP_BACKOFF ** attempt)
    raise RuntimeError(f"GET {url} failed: {last}")


def fetch_observations(dates: List[dt.date]) -> Dict[str, Optional[float]]:
    """
    מחזיר {date_iso: observed_temp_max_or_None} עבור תאריכי עבר.
    מעדיף את Open-Meteo Forecast API עם past_days (רענון יומי, 0-5 ימי השהיה),
    ונופל חזרה ל-Archive ERA5 עבור תאריכים ישנים (>5 ימים).
    """
    if not dates:
        return {}
    dates = sorted(set(dates))
    now = dt.datetime.now(TIMEZONE_TZ)
    out: Dict[str, Optional[float]] = {}

    # נקודת החתך: אוספים רק תצפיות שסגרו לפחות OBSERVATION_CUTOFF_HOURS
    # אחרי סוף היום (למנוע שימוש בתחזית שעדיין לא "נקבעה").
    cutoff_day = (now - dt.timedelta(hours=OBSERVATION_CUTOFF_HOURS)).date()
    dates = [d for d in dates if d < cutoff_day]
    if not dates:
        return {}

    # שני חלונות: recent (<=5 ימים לאחור) דרך forecast API,
    # older (6-90 יום לאחור) דרך archive API.
    today = now.date()
    recent_dates = [d for d in dates if (today - d).days <= 5]
    archive_dates = [d for d in dates if (today - d).days > 5]

    if recent_dates:
        try:
            past_days = max((today - d).days for d in recent_dates)
            data = _http_get(FORECAST_URL, {
                "latitude":  LAT,
                "longitude": LON,
                "daily":     "temperature_2m_max",
                "temperature_unit": "celsius",
                "timezone":  TIMEZONE,
                "past_days": past_days + 1,
                "forecast_days": 1,
            })
            times = (data.get("daily") or {}).get("time") or []
            vals  = (data.get("daily") or {}).get("temperature_2m_max") or []
            for t, v in zip(times, vals):
                if v is None:
                    continue
                if not (TEMP_SANITY_MIN <= v <= TEMP_SANITY_MAX):
                    continue
                out[t] = float(v)
        except Exception as e:
            log.warning("לא הצלחתי לשלוף תצפיות טריות: %s", e)

    if archive_dates:
        try:
            data = _http_get(ARCHIVE_URL, {
                "latitude":  LAT,
                "longitude": LON,
                "daily":     "temperature_2m_max",
                "temperature_unit": "celsius",
                "timezone":  TIMEZONE,
                "start_date": min(archive_dates).isoformat(),
                "end_date":   max(archive_dates).isoformat(),
            })
            times = (data.get("daily") or {}).get("time") or []
            vals  = (data.get("daily") or {}).get("temperature_2m_max") or []
            for t, v in zip(times, vals):
                if v is None:
                    continue
                if not (TEMP_SANITY_MIN <= v <= TEMP_SANITY_MAX):
                    continue
                out[t] = float(v)
        except Exception as e:
            log.warning("לא הצלחתי לשלוף תצפיות מהארכיון: %s", e)

    return out


# ─────────────────────────────────────────────
# לוג תחזיות והעשרה עם תצפיות
# ─────────────────────────────────────────────

def _load_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _save_jsonl(path: str, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def append_forecast_snapshot(target_date: dt.date,
                             per_model: Dict[str, Optional[float]],
                             consensus_mean: Optional[float],
                             consensus_std: Optional[float],
                             ts_iso: str) -> None:
    """שומר את ערכי התחזית של כל מודל להרצה הנוכחית (append-only)."""
    rows = _load_jsonl(FORECASTS_LOG)
    rows.append({
        "ts":          ts_iso,
        "target_date": target_date.isoformat(),
        "models":      {k: v for k, v in per_model.items()},
        "consensus":   consensus_mean,
        "sigma":       consensus_std,
    })
    # גיזום ל-ACCURACY_MAX_DAYS ימים לאחור כפול ~100 הרצות ליום
    if len(rows) > ACCURACY_MAX_DAYS * 100:
        rows = rows[-ACCURACY_MAX_DAYS * 100:]
    _save_jsonl(FORECASTS_LOG, rows)


def _load_observations() -> Dict[str, float]:
    if not os.path.exists(OBSERVATIONS_JSON):
        return {}
    try:
        with open(OBSERVATIONS_JSON, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_observations(obs: Dict[str, float]) -> None:
    with open(OBSERVATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(obs, f, ensure_ascii=False, indent=2, sort_keys=True)


def refresh_observations() -> Dict[str, float]:
    """מזהה תאריכי עבר שעדיין חסרה להם תצפית ושולף אותם."""
    known = _load_observations()
    rows  = _load_jsonl(FORECASTS_LOG)
    seen_dates = sorted({r["target_date"] for r in rows})
    now_date = dt.datetime.now(TIMEZONE_TZ).date()
    candidates = []
    for d in seen_dates:
        try:
            dd = dt.date.fromisoformat(d)
        except ValueError:
            continue
        if d in known:
            continue
        if (now_date - dd).days < 1:
            continue  # היום/עתיד — אין תצפית
        if (now_date - dd).days > ACCURACY_MAX_DAYS:
            continue  # מעבר לחלון המעקב
        candidates.append(dd)
    if not candidates:
        return known
    fetched = fetch_observations(candidates)
    if fetched:
        known.update(fetched)
        _save_observations(known)
        log.info("נוספו תצפיות: %s", ", ".join(sorted(fetched.keys())))
    return known


# ─────────────────────────────────────────────
# חישוב מדדי דיוק לכל מודל
# ─────────────────────────────────────────────

def compute_model_scores() -> dict:
    """
    עבור כל מודל מחשב:
    - n:       מספר ימים עם גם תחזית וגם תצפית
    - mae:     שגיאה מוחלטת ממוצעת
    - bias:    ממוצע (תחזית − תצפית) — חיובי = מודל חם מדי
    - hit_1c:  שיעור הימים שהפרש ≤ 1°C
    - rank_avg: ממוצע דירוג (1=הכי מדויק אותו יום)
    """
    rows = _load_jsonl(FORECASTS_LOG)
    obs  = _load_observations()
    if not rows or not obs:
        return {"models": {m: _empty_score() for m in WEATHER_MODELS},
                "consensus": _empty_score(),
                "days_measured": 0, "last_update": None}

    # מאחדים: לכל target_date, ניקח את התחזית האחרונה שצילמנו לפני סוף היום
    # (הקרובה ביותר להתרחשות בפועל).
    latest_per_date: Dict[str, dict] = {}
    for r in rows:
        td = r["target_date"]
        if td not in obs:
            continue
        prev = latest_per_date.get(td)
        if prev is None or r["ts"] > prev["ts"]:
            latest_per_date[td] = r

    per_model_errors: Dict[str, List[float]] = {m: [] for m in WEATHER_MODELS}
    consensus_errors: List[float] = []
    rank_counts: Dict[str, List[int]] = {m: [] for m in WEATHER_MODELS}

    for td, r in latest_per_date.items():
        obs_v = obs[td]
        # דירוגים באותו יום לפי מרחק מהתצפית
        distances = []
        for m, v in (r.get("models") or {}).items():
            if v is None or m not in WEATHER_MODELS:
                continue
            err = v - obs_v
            per_model_errors[m].append(err)
            distances.append((abs(err), m))
        distances.sort()
        for rank_idx, (_, m) in enumerate(distances, start=1):
            rank_counts[m].append(rank_idx)
        cm = r.get("consensus")
        if cm is not None:
            consensus_errors.append(cm - obs_v)

    def _score(errors: List[float], ranks: Optional[List[int]] = None) -> dict:
        if not errors:
            return _empty_score()
        n = len(errors)
        abs_errs = [abs(e) for e in errors]
        mae = sum(abs_errs) / n
        bias = sum(errors) / n
        hit = sum(1 for a in abs_errs if a <= ACCURACY_HIT_WINDOW_C) / n
        rank_avg = (sum(ranks) / len(ranks)) if ranks else None
        return {"n": n, "mae": mae, "bias": bias,
                "hit_1c": hit, "rank_avg": rank_avg}

    model_scores = {m: _score(per_model_errors[m], rank_counts[m])
                    for m in WEATHER_MODELS}
    consensus_score = _score(consensus_errors)

    result = {
        "models":        model_scores,
        "consensus":     consensus_score,
        "days_measured": len(latest_per_date),
        "last_update":   dt.datetime.now(TIMEZONE_TZ).isoformat(),
        "hit_window_c":  ACCURACY_HIT_WINDOW_C,
    }
    with open(ACCURACY_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


def _empty_score() -> dict:
    return {"n": 0, "mae": None, "bias": None, "hit_1c": None, "rank_avg": None}

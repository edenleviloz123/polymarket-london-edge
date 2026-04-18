"""
מעקב דיוק לכל מודל ולכל עיר לאורך זמן.

שלושה קבצי מצב (בתוך docs/):
  forecasts.jsonl   — לוג של כל תחזית לכל עיר לכל תאריך (append-only).
  observations.json — מפה של {city_key: {date_iso: observed_max_int}}.
  accuracy.json     — סנאפשוט מחושב של MAE/bias/hit-rate לכל מודל לכל עיר.

התצפיות נשאבות מ-METAR (מקור הרזולוציה של Polymarket), לא מ-Open-Meteo.
"""
import datetime as dt
import json
import logging
import os
from typing import Dict, List, Optional

from config import (
    ACCURACY_HIT_WINDOW_C, ACCURACY_JSON, ACCURACY_MAX_DAYS,
    CITIES, FORECASTS_LOG, OBSERVATION_CUTOFF_HOURS,
    OBSERVATIONS_JSON, USER_TZ, WEATHER_MODELS,
)
from metar import fetch_metar_daily_max_history

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# לוגיקה של קריאה / כתיבה לקבצי המצב
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


def _load_observations() -> Dict[str, Dict[str, float]]:
    """{city_key: {date_iso: observed_max_int}}"""
    if not os.path.exists(OBSERVATIONS_JSON):
        return {}
    try:
        with open(OBSERVATIONS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        # תאימות עם פורמט ישן (לפני שהיה city_key)
        if data and all(isinstance(v, (int, float)) for v in data.values()):
            return {"london": {k: v for k, v in data.items()}}
        return data
    except Exception:
        return {}


def _save_observations(obs: Dict[str, Dict[str, float]]) -> None:
    with open(OBSERVATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(obs, f, ensure_ascii=False, indent=2, sort_keys=True)


# ─────────────────────────────────────────────
# לוגיקה של תחזיות
# ─────────────────────────────────────────────

def append_forecast_snapshot(city_key: str, target_date: dt.date,
                              per_model: Dict[str, Optional[float]],
                              consensus_mean: Optional[float],
                              consensus_std: Optional[float],
                              ts_iso: str) -> None:
    rows = _load_jsonl(FORECASTS_LOG)
    rows.append({
        "ts":          ts_iso,
        "city":        city_key,
        "target_date": target_date.isoformat(),
        "models":      {k: v for k, v in per_model.items()},
        "consensus":   consensus_mean,
        "sigma":       consensus_std,
    })
    max_entries = ACCURACY_MAX_DAYS * 100 * max(1, len(CITIES))
    if len(rows) > max_entries:
        rows = rows[-max_entries:]
    _save_jsonl(FORECASTS_LOG, rows)


# ─────────────────────────────────────────────
# לוגיקה של תצפיות
# ─────────────────────────────────────────────

def refresh_observations_metar() -> Dict[str, Dict[str, float]]:
    """
    שולף METAR היסטורי עבור כל עיר ברשימה, ומעדכן את observations.json
    עבור ימים שסגרו את חלון ה-cutoff.
    """
    known = _load_observations()
    now_generic = dt.datetime.now(USER_TZ)

    for city in CITIES:
        city_key = city["key"]
        city_obs = known.get(city_key, {})
        try:
            fetched = fetch_metar_daily_max_history(city, now_generic, days_back=5)
        except Exception as e:
            log.warning("[%s] שליפת METAR היסטורי נכשלה: %s", city_key, e)
            continue
        # מוסיפים רק תאריכים שעדיין חסרים אצלנו
        added = 0
        for date_iso, val in fetched.items():
            if date_iso not in city_obs:
                city_obs[date_iso] = int(val)
                added += 1
        if added:
            log.info("[%s] נוספו %d תצפיות METAR", city_key, added)
            known[city_key] = city_obs

    _save_observations(known)
    return known


# ─────────────────────────────────────────────
# חישוב מדדי דיוק לכל מודל לכל עיר
# ─────────────────────────────────────────────

def _empty_score() -> dict:
    return {"n": 0, "mae": None, "bias": None, "hit_1c": None,
            "bucket_hit": None, "rank_avg": None}


def _score(errors: List[float],
           bucket_hits: Optional[List[bool]] = None,
           ranks: Optional[List[int]] = None) -> dict:
    """
    errors: הפרשים רציפים (forecast_continuous - observed_int)
    bucket_hits: האם round(forecast) == observed_int לכל תצפית
    ranks: דירוג המודל מול המודלים האחרים באותו יום
    """
    if not errors:
        return _empty_score()
    n = len(errors)
    abs_errs = [abs(e) for e in errors]
    mae = sum(abs_errs) / n
    bias = sum(errors) / n
    hit = sum(1 for a in abs_errs if a <= ACCURACY_HIT_WINDOW_C) / n
    bhit = (sum(1 for b in bucket_hits if b) / len(bucket_hits)
            if bucket_hits else None)
    rank_avg = (sum(ranks) / len(ranks)) if ranks else None
    return {"n": n, "mae": mae, "bias": bias,
            "hit_1c": hit, "bucket_hit": bhit,
            "rank_avg": rank_avg}


def compute_model_scores() -> dict:
    """
    מחזיר מבנה:
    {
      "per_city": { city_key: { models: {...}, consensus: {...}, days_measured: n } },
      "global":   { models: {...}, consensus: {...}, days_measured: n },
      "last_update": iso_timestamp,
    }
    """
    rows = _load_jsonl(FORECASTS_LOG)
    obs = _load_observations()

    # קיבוץ: עבור כל (city, target_date) ניקח את התחזית האחרונה
    latest: Dict[tuple, dict] = {}
    for r in rows:
        city = r.get("city") or "london"   # fallback ישן
        td = r.get("target_date")
        if not td or city not in obs or td not in obs[city]:
            continue
        key = (city, td)
        prev = latest.get(key)
        if prev is None or r["ts"] > prev["ts"]:
            latest[key] = {**r, "_city": city}

    # צבירה לכל עיר בנפרד
    per_city_errors:  Dict[str, Dict[str, List[float]]] = {}
    per_city_hits:    Dict[str, Dict[str, List[bool]]]  = {}
    per_city_ranks:   Dict[str, Dict[str, List[int]]]   = {}
    per_city_cons:    Dict[str, List[float]]            = {}
    per_city_consh:   Dict[str, List[bool]]             = {}
    per_city_days:    Dict[str, int]                    = {}

    global_errors:  Dict[str, List[float]] = {m: [] for m in WEATHER_MODELS}
    global_hits:    Dict[str, List[bool]]  = {m: [] for m in WEATHER_MODELS}
    global_ranks:   Dict[str, List[int]]   = {m: [] for m in WEATHER_MODELS}
    global_cons:    List[float]            = []
    global_consh:   List[bool]             = []

    for (city_key, td), r in latest.items():
        obs_v = obs[city_key][td]   # מספר שלם מ-METAR
        per_city_errors.setdefault(city_key, {m: [] for m in WEATHER_MODELS})
        per_city_hits.setdefault(city_key,   {m: [] for m in WEATHER_MODELS})
        per_city_ranks.setdefault(city_key,  {m: [] for m in WEATHER_MODELS})
        per_city_cons.setdefault(city_key, [])
        per_city_consh.setdefault(city_key, [])
        per_city_days[city_key] = per_city_days.get(city_key, 0) + 1

        distances = []
        for m, v in (r.get("models") or {}).items():
            if v is None or m not in WEATHER_MODELS:
                continue
            err = v - obs_v
            bucket_hit = (round(v) == obs_v)   # האם round(חיזוי) = METAR
            per_city_errors[city_key][m].append(err)
            per_city_hits[city_key][m].append(bucket_hit)
            global_errors[m].append(err)
            global_hits[m].append(bucket_hit)
            distances.append((abs(err), m))
        distances.sort()
        for rank_idx, (_, m) in enumerate(distances, start=1):
            per_city_ranks[city_key][m].append(rank_idx)
            global_ranks[m].append(rank_idx)
        cm = r.get("consensus")
        if cm is not None:
            per_city_cons[city_key].append(cm - obs_v)
            per_city_consh[city_key].append(round(cm) == obs_v)
            global_cons.append(cm - obs_v)
            global_consh.append(round(cm) == obs_v)

    per_city_result = {}
    for city_key in per_city_errors:
        per_city_result[city_key] = {
            "models":        {m: _score(per_city_errors[city_key][m],
                                        per_city_hits[city_key][m],
                                        per_city_ranks[city_key][m])
                              for m in WEATHER_MODELS},
            "consensus":     _score(per_city_cons[city_key],
                                    per_city_consh[city_key]),
            "days_measured": per_city_days[city_key],
        }

    global_result = {
        "models":        {m: _score(global_errors[m], global_hits[m],
                                    global_ranks[m])
                          for m in WEATHER_MODELS},
        "consensus":     _score(global_cons, global_consh),
        "days_measured": len(latest),
    }

    result = {
        "per_city":    per_city_result,
        "global":      global_result,
        "last_update": dt.datetime.now(USER_TZ).isoformat(),
        "hit_window_c": ACCURACY_HIT_WINDOW_C,
    }
    with open(ACCURACY_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result

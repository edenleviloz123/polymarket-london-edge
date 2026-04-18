"""
שליפת תחזיות מחמישה מודלי מזג-אוויר דרך Open-Meteo, וחישוב
קונצנזוס + פיזור בין-מודלי + אנסמבלים עצמאיים (ECMWF EPS + NOAA GEFS).

כל הפונקציות מקבלות את מילון העיר כפרמטר ראשון — כך אותה מערכת
עובדת על לונדון, פריז, או כל עיר אחרת ב-CITIES.
"""
import datetime as dt
import logging
import time
from typing import Dict, Optional

import requests

from config import (
    ENSEMBLE_MIN_MEMBERS, ENSEMBLE_MODELS,
    HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT,
    OPEN_METEO_ENSEMBLE_URL,
    TEMP_SANITY_MAX, TEMP_SANITY_MIN,
    WEATHER_MODELS,
)

log = logging.getLogger(__name__)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _http_get(url: str, params: dict) -> dict:
    last_err = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            sleep = HTTP_BACKOFF ** attempt
            log.warning("open-meteo attempt %d/%d failed: %s (sleeping %.1fs)",
                        attempt + 1, HTTP_RETRIES, e, sleep)
            time.sleep(sleep)
    raise RuntimeError(f"open-meteo failed after {HTTP_RETRIES} retries: {last_err}")


def fetch_forecasts(city: dict,
                    forecast_days: int = 4) -> Dict[str, Dict[str, Optional[float]]]:
    """
    {target_date: {שם_מודל: טמפ_מקס_או_None}} עבור העיר הנתונה.
    """
    models_csv = ",".join(WEATHER_MODELS.values())
    params = {
        "latitude":          city["lat"],
        "longitude":         city["lon"],
        "daily":             "temperature_2m_max",
        "temperature_unit":  "celsius",
        "models":            models_csv,
        "timezone":          city["timezone"],
        "forecast_days":     forecast_days,
    }
    data = _http_get(OPEN_METEO_URL, params)
    daily = data.get("daily", {}) or {}
    dates = daily.get("time", []) or []
    result: Dict[str, Dict[str, Optional[float]]] = {d: {} for d in dates}

    for display_name, slug in WEATHER_MODELS.items():
        key = f"temperature_2m_max_{slug}"
        values = daily.get(key) or []
        for i, date in enumerate(dates):
            val = values[i] if i < len(values) else None
            if val is not None and not (TEMP_SANITY_MIN <= val <= TEMP_SANITY_MAX):
                log.warning("[%s] ערך חריג: %s %s = %s°C — מסנן",
                            city["key"], display_name, date, val)
                val = None
            result[date][display_name] = val
    return result


def detect_outliers(per_model: Dict[str, Optional[float]],
                    threshold_c: float) -> Dict[str, float]:
    available = {m: v for m, v in per_model.items() if v is not None}
    if len(available) < 3:
        return {}
    vals = sorted(available.values())
    n = len(vals)
    median = vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    outliers = {}
    for name, v in available.items():
        deviation = v - median
        if abs(deviation) > threshold_c:
            outliers[name] = deviation
    return outliers


def consensus(per_model: Dict[str, Optional[float]],
              outliers: Optional[Dict[str, float]] = None) -> dict:
    outliers = outliers or {}
    used = {m: v for m, v in per_model.items()
            if v is not None and m not in outliers}
    n = len(used)
    if n == 0:
        return {"mean": None, "std": None, "n": 0,
                "models": {}, "all_models": per_model, "outliers": outliers}
    values = list(used.values())
    mean = sum(values) / n
    if n >= 2:
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        std = var ** 0.5
    else:
        std = 0.0
    return {
        "mean":       mean,
        "std":        std,
        "n":          n,
        "models":     used,
        "all_models": per_model,
        "outliers":   outliers,
    }


def _fetch_single_ensemble(city: dict, model_slug: str,
                            target_date: dt.date,
                            forecast_days: int = 3) -> Optional[dict]:
    params = {
        "latitude":         city["lat"],
        "longitude":        city["lon"],
        "daily":            "temperature_2m_max",
        "temperature_unit": "celsius",
        "models":           model_slug,
        "timezone":         city["timezone"],
        "forecast_days":    forecast_days,
    }
    try:
        data = _http_get(OPEN_METEO_ENSEMBLE_URL, params)
    except Exception as e:
        log.warning("[%s] שליפת ensemble (%s) נכשלה: %s",
                    city["key"], model_slug, e)
        return None

    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    tgt = target_date.isoformat()
    if tgt not in dates:
        return None
    idx = dates.index(tgt)

    values = []
    for key, series in daily.items():
        if not key.startswith("temperature_2m_max"):
            continue
        if "_member" not in key:
            continue
        if idx >= len(series):
            continue
        v = series[idx]
        if v is None:
            continue
        if not (TEMP_SANITY_MIN <= v <= TEMP_SANITY_MAX):
            continue
        values.append(float(v))

    if len(values) < ENSEMBLE_MIN_MEMBERS:
        return None

    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    std = var ** 0.5
    return {
        "mean":       mean,
        "std":        std,
        "n_members":  n,
        "min":        min(values),
        "max":        max(values),
    }


def fetch_ensemble_spread(city: dict, target_date: dt.date,
                           forecast_days: int = 3) -> Optional[dict]:
    systems = {}
    for display_name, slug in ENSEMBLE_MODELS.items():
        result = _fetch_single_ensemble(city, slug, target_date, forecast_days)
        if result is not None:
            systems[display_name] = result
    if not systems:
        return None
    stds = [s["std"] for s in systems.values()]
    combined_std = max(stds) if stds else None
    total_members = sum(s["n_members"] for s in systems.values())
    means = [s["mean"] for s in systems.values()]
    agreement = (max(means) - min(means)) if len(means) >= 2 else 0.0
    return {
        "systems":           systems,
        "combined_std":      combined_std,
        "combined_members":  total_members,
        "agreement_c":       agreement,
    }


def fetch_remaining_hourly_forecast(city: dict, now) -> Optional[dict]:
    """תחזית שעתית לשעות שנותרו היום בעיר הנתונה."""
    today_iso = now.date().isoformat()
    try:
        data = _http_get(OPEN_METEO_URL, {
            "latitude":          city["lat"],
            "longitude":         city["lon"],
            "hourly":            "temperature_2m",
            "temperature_unit":  "celsius",
            "timezone":          city["timezone"],
            "start_date":        today_iso,
            "end_date":          today_iso,
        })
    except Exception as e:
        log.warning("[%s] שליפת תחזית שעתית נכשלה: %s", city["key"], e)
        return None

    hourly = (data.get("hourly") or {})
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    remaining_vals = []
    for t_iso, v in zip(times, temps):
        if v is None or not (TEMP_SANITY_MIN <= v <= TEMP_SANITY_MAX):
            continue
        try:
            t_dt = dt.datetime.fromisoformat(t_iso).replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
        if t_dt > now:
            remaining_vals.append(v)

    if not remaining_vals:
        return {"remaining_forecast_max": None, "hours_remaining": 0,
                "remaining_values": []}
    return {
        "remaining_forecast_max": max(remaining_vals),
        "hours_remaining":        len(remaining_vals),
        "remaining_values":       remaining_vals,
    }

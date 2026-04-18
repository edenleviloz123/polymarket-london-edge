"""
שליפת תחזיות טמפ' מקסימלית יומית מחמישה מודלי מזג-אוויר דרך Open-Meteo,
עם retry, ולידציה, וחישוב קונצנזוס + פיזור בין-מודלי.
"""
import logging
import time
from typing import Dict, Optional

import requests

from config import (
    HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT,
    LAT, LON, TIMEZONE,
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


def fetch_forecasts(forecast_days: int = 4) -> Dict[str, Dict[str, Optional[float]]]:
    """
    מחזיר {תאריך_ISO: {שם_מודל: טמפ_מקס_או_None}}.
    ערכי None = המודל לא מספק תחזית לאותו יום או חרג מטווח שפיות.
    """
    models_csv = ",".join(WEATHER_MODELS.values())
    params = {
        "latitude":          LAT,
        "longitude":         LON,
        "daily":             "temperature_2m_max",
        "temperature_unit":  "celsius",
        "models":            models_csv,
        "timezone":          TIMEZONE,
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
                log.warning("ערך חריג בטווח: %s %s = %s°C — מסנן", display_name, date, val)
                val = None
            result[date][display_name] = val
    return result


def consensus(per_model: Dict[str, Optional[float]]) -> dict:
    """
    מחשב ממוצע קונצנזוס + סטיית תקן בין-מודלית על הערכים שזמינים.
    n הוא מספר המודלים שהגיבו בהצלחה.
    """
    available = {m: v for m, v in per_model.items() if v is not None}
    n = len(available)
    if n == 0:
        return {"mean": None, "std": None, "n": 0, "models": {}, "all_models": per_model}
    values = list(available.values())
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
        "models":     available,      # רק הזמינים
        "all_models": per_model,      # כולל None לציון "נכשל"
    }

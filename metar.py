"""
שליפת METAR חי של London City Airport (EGLC) מ-aviationweather.gov.
זה הנתון האמיתי שממנו Wunderground שואב, ולכן זה המקור שממנו
Polymarket יקבע את התוצאה בסוף היום.

הערה חשובה: METAR מדווחים כבר במעלות שלמות. לכן observed_max הוא מספר שלם,
ואין צורך בתיקון continuity בהשוואה לקצוות ה-buckets.
"""
import datetime as dt
import json
import logging
import time
from typing import List, Optional

import requests

from config import (
    HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT,
    TEMP_SANITY_MAX, TEMP_SANITY_MIN, TIMEZONE_TZ,
)

log = logging.getLogger(__name__)

METAR_URL = "https://aviationweather.gov/api/data/metar"
STATION_ICAO = "EGLC"   # London City Airport (תחנת הרזולוציה של Polymarket)


def _http_get(url: str, params: dict) -> object:
    headers = {
        "Accept":        "application/json",
        "Cache-Control": "no-cache",
        "User-Agent":    "polymarket-london-edge/1.0",
    }
    last = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, params=params, headers=headers,
                             timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            # ה-API מחזיר לעיתים application/json ולעיתים text עם JSON
            try:
                return r.json()
            except json.JSONDecodeError:
                return json.loads(r.text)
        except Exception as e:
            last = e
            time.sleep(HTTP_BACKOFF ** attempt)
    raise RuntimeError(f"METAR GET failed: {last}")


def _parse_iso_utc(ts: str) -> Optional[dt.datetime]:
    """METAR reportTime יכול להגיע ב-ISO עם Z או עם רווח — תומכים בשניהם."""
    if not ts:
        return None
    s = str(ts).strip()
    # "2026-04-18T16:20:00.000Z" → "2026-04-18T16:20:00.000+00:00"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except ValueError:
        pass
    # fallback: "YYYY-MM-DD HH:MM:SS" בלי TZ
    s2 = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s2, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def _extract_temp(report: dict) -> Optional[int]:
    """שולף טמפרטורה שלמה °C מ-METAR. עדיפות ל-tempC אם קיים."""
    t = report.get("tempC")
    if t is None:
        t = report.get("temp")
    if t is None:
        return None
    try:
        t = float(t)
    except (TypeError, ValueError):
        return None
    if not (TEMP_SANITY_MIN <= t <= TEMP_SANITY_MAX):
        return None
    return int(round(t))


def fetch_metar_observations(now: dt.datetime, hours: int = 24) -> Optional[dict]:
    """
    מחזיר:
      {observed_max_int, peak_time_local, hours_past_today, report_count, latest_temp, latest_time_local}
    עבור התאריך המקומי הנוכחי בלונדון, מבוסס אך ורק על METAR של EGLC.
    None אם נכשל או אין דיווחים להיום.
    """
    try:
        data = _http_get(METAR_URL, {
            "ids":    STATION_ICAO,
            "format": "json",
            "hours":  hours,
        })
    except Exception as e:
        log.warning("METAR fetch failed: %s", e)
        return None

    if not isinstance(data, list) or not data:
        log.info("METAR: לא הוחזרו דיווחים לתחנה %s", STATION_ICAO)
        return None

    today_local = now.date()
    rows: List[dict] = []
    for rep in data:
        report_time_str = rep.get("reportTime") or rep.get("obsTime")
        if isinstance(report_time_str, (int, float)):
            # Unix seconds
            t_utc = dt.datetime.fromtimestamp(report_time_str, tz=dt.timezone.utc)
        else:
            t_utc = _parse_iso_utc(str(report_time_str) if report_time_str else "")
        if t_utc is None:
            continue
        t_local = t_utc.astimezone(TIMEZONE_TZ)
        if t_local.date() != today_local:
            continue
        temp = _extract_temp(rep)
        if temp is None:
            continue
        rows.append({"t_local": t_local, "temp": temp, "raw": rep.get("rawOb")})

    if not rows:
        log.info("METAR: אין דיווחים לתאריך המקומי %s", today_local)
        return None

    # ממיינים כרונולוגית
    rows.sort(key=lambda r: r["t_local"])
    observed_max = max(r["temp"] for r in rows)
    peak_row = max(rows, key=lambda r: r["temp"])
    latest = rows[-1]

    return {
        "observed_max_int":  observed_max,
        "peak_time_local":   peak_row["t_local"].strftime("%H:%M"),
        "peak_temp":         peak_row["temp"],
        "report_count":      len(rows),
        "latest_time_local": latest["t_local"].strftime("%H:%M"),
        "latest_temp":       latest["temp"],
        "raw_sample":        latest.get("raw"),
    }

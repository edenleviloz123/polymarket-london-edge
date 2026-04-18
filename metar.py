"""
שליפת METAR חי וגם היסטורי מ-aviationweather.gov.
מקור התצפית האמיתי שממנו Wunderground שואב וממנו Polymarket מיישב.

הפונקציות מקבלות את מילון העיר ועובדות עבור כל תחנת METAR בעולם.
"""
import datetime as dt
import json
import logging
import time
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests

from config import (
    HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT,
    TEMP_SANITY_MAX, TEMP_SANITY_MIN,
)

log = logging.getLogger(__name__)
METAR_URL = "https://aviationweather.gov/api/data/metar"


def _http_get(url: str, params: dict) -> object:
    headers = {
        "Accept":        "application/json",
        "Cache-Control": "no-cache",
        "User-Agent":    "polymarket-weather-edge/1.0",
    }
    last = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, params=params, headers=headers,
                             timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            try:
                return r.json()
            except json.JSONDecodeError:
                return json.loads(r.text)
        except Exception as e:
            last = e
            time.sleep(HTTP_BACKOFF ** attempt)
    raise RuntimeError(f"METAR GET failed: {last}")


def _parse_iso_utc(ts: str) -> Optional[dt.datetime]:
    if not ts:
        return None
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except ValueError:
        pass
    s2 = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s2, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def _extract_temp(report: dict) -> Optional[int]:
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


def _report_to_row(report: dict) -> Optional[dict]:
    report_time_str = report.get("reportTime") or report.get("obsTime")
    if isinstance(report_time_str, (int, float)):
        t_utc = dt.datetime.fromtimestamp(report_time_str, tz=dt.timezone.utc)
    else:
        t_utc = _parse_iso_utc(str(report_time_str) if report_time_str else "")
    if t_utc is None:
        return None
    temp = _extract_temp(report)
    if temp is None:
        return None
    return {"t_utc": t_utc, "temp": temp, "raw": report.get("rawOb")}


def _fetch_raw_metars(station: str, hours: int = 24) -> List[dict]:
    try:
        data = _http_get(METAR_URL, {
            "ids": station, "format": "json", "hours": hours,
        })
    except Exception as e:
        log.warning("METAR fetch failed (%s): %s", station, e)
        return []
    if not isinstance(data, list):
        return []
    rows = []
    for rep in data:
        r = _report_to_row(rep)
        if r:
            rows.append(r)
    rows.sort(key=lambda r: r["t_utc"])
    return rows


def fetch_metar_observations(city: dict, now: dt.datetime,
                              hours: int = 24) -> Optional[dict]:
    """תצפיות METAR של היום המקומי עד עכשיו עבור העיר הנתונה."""
    station = city["metar_station"]
    tz = ZoneInfo(city["timezone"])
    today_local = now.astimezone(tz).date()
    rows = _fetch_raw_metars(station, hours=hours)
    if not rows:
        return None

    todays = []
    for r in rows:
        t_local = r["t_utc"].astimezone(tz)
        if t_local.date() == today_local:
            todays.append({
                **r,
                "t_local": t_local,
            })
    if not todays:
        return None
    todays.sort(key=lambda r: r["t_local"])
    observed_max = max(r["temp"] for r in todays)
    peak_row = max(todays, key=lambda r: r["temp"])
    latest = todays[-1]
    age_min = max(0, int((now - latest["t_local"]).total_seconds() / 60))
    return {
        "observed_max_int":  observed_max,
        "peak_time_local":   peak_row["t_local"].strftime("%H:%M"),
        "peak_temp":         peak_row["temp"],
        "report_count":      len(todays),
        "latest_time_local": latest["t_local"].strftime("%H:%M"),
        "latest_temp":       latest["temp"],
        "latest_age_min":    age_min,
        "raw_sample":        latest.get("raw"),
    }


def fetch_metar_daily_max_history(city: dict, now: dt.datetime,
                                   days_back: int = 5) -> dict:
    """
    מחזיר {date_iso: observed_max_int} עבור ימי עבר שהסתיימו.
    משמש לישוב איתותים (paper trading) ולחישוב דיוק מודלים.
    """
    station = city["metar_station"]
    tz = ZoneInfo(city["timezone"])
    hours = max(48, (days_back + 1) * 24)
    rows = _fetch_raw_metars(station, hours=hours)
    if not rows:
        return {}
    by_date: dict = {}
    today_local = now.astimezone(tz).date()
    cutoff = today_local - dt.timedelta(days=days_back)
    for r in rows:
        t_local = r["t_utc"].astimezone(tz)
        d = t_local.date()
        if d >= today_local or d < cutoff:
            continue   # רק ימים שלמים שכבר נסגרו
        key = d.isoformat()
        by_date[key] = max(by_date.get(key, r["temp"]), r["temp"])
    return by_date

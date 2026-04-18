"""
לקוח Polymarket Gamma API:
- שליפת אירוע לפי slug (מהיר, ישיר)
- סריקה רחבה לפי מילות מפתח (fallback)
- חיתוך חוזים מקוננים → מבנה מובנה (bucket, מחיר YES, נפח)
"""
import json
import logging
import re
import time
from typing import Any, List, Optional

import requests

from config import (
    BROAD_SCAN_LIMIT, GAMMA_BASE,
    HTTP_BACKOFF, HTTP_RETRIES, HTTP_TIMEOUT,
    MARKET_CITY_SLUG, MARKET_KEYWORDS_ANY, MARKET_KEYWORDS_REQUIRED,
)

log = logging.getLogger(__name__)

# ניתוח תוויות כמו "11°C or below", "14°C", "21°C or higher"
BUCKET_BELOW_RE  = re.compile(r"(-?\d+)\s*°?\s*C\s*or\s*below",           re.I)
BUCKET_ABOVE_RE  = re.compile(r"(-?\d+)\s*°?\s*C\s*or\s*(?:higher|above)", re.I)
BUCKET_SINGLE_RE = re.compile(r"(-?\d+)\s*°?\s*C\b",                       re.I)


def _http_get(url: str, params: Optional[dict] = None) -> Any:
    last_err = None
    for attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, params=params or {}, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            sleep = HTTP_BACKOFF ** attempt
            log.warning("gamma attempt %d/%d failed (%s): %s",
                        attempt + 1, HTTP_RETRIES, url, e)
            time.sleep(sleep)
    raise RuntimeError(f"gamma GET failed: {last_err}")


def _parse_json_if_str(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def parse_bucket(label: str) -> Optional[dict]:
    """ 'or below' / 'or higher' / מספר בודד °C → מבנה bucket """
    if not label:
        return None
    s = label.strip()
    m = BUCKET_BELOW_RE.search(s)
    if m:
        return {"type": "below", "temp": int(m.group(1)), "label": s}
    m = BUCKET_ABOVE_RE.search(s)
    if m:
        return {"type": "above", "temp": int(m.group(1)), "label": s}
    m = BUCKET_SINGLE_RE.search(s)
    if m:
        return {"type": "single", "temp": int(m.group(1)), "label": s}
    return None


def _parse_prices(raw) -> Optional[List[float]]:
    parsed = _parse_json_if_str(raw)
    if not isinstance(parsed, list):
        return None
    try:
        return [float(x) for x in parsed]
    except (TypeError, ValueError):
        return None


def _yes_price(market: dict, prices: List[float]) -> float:
    """מחלץ את מחיר ה-YES גם אם סדר ה-outcomes הפוך."""
    outcomes = _parse_json_if_str(market.get("outcomes"))
    if isinstance(outcomes, list) and len(outcomes) >= 2:
        if str(outcomes[1]).strip().lower() == "yes":
            return prices[1]
    return prices[0]


def _as_float(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def event_to_contracts(event: dict) -> List[dict]:
    """מחלץ רשימת חוזים סדורה מאירוע Polymarket מרובה-תוצאות."""
    contracts = []
    for m in event.get("markets", []) or []:
        label = m.get("groupItemTitle") or m.get("question") or ""
        bucket = parse_bucket(label)
        if not bucket:
            continue
        prices = _parse_prices(m.get("outcomePrices"))
        if not prices or len(prices) < 2:
            continue
        yes_price = _yes_price(m, prices)
        volume    = _as_float(m.get("volumeNum")    or m.get("volume"))
        liquidity = _as_float(m.get("liquidityNum") or m.get("liquidity"))
        contracts.append({
            "bucket":    bucket,
            "yes_price": yes_price,
            "no_price":  1.0 - yes_price,
            "volume":    volume,
            "liquidity": liquidity,
            "question":  m.get("question"),
            "slug":      m.get("slug"),
        })
    # סידור: below ראשון, אח"כ singles לפי טמפ', בסוף above
    type_order = {"below": 0, "single": 1, "above": 2}
    contracts.sort(key=lambda c: (type_order[c["bucket"]["type"]], c["bucket"]["temp"]))
    return contracts


def fetch_event_by_slug(slug: str) -> Optional[dict]:
    data = _http_get(f"{GAMMA_BASE}/events", {"slug": slug})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data.get("slug"):
        return data
    return None


def build_candidate_slugs(target_date) -> List[str]:
    """
    ה-slug של Polymarket בדר"כ: highest-temperature-in-<city>-on-<month>-<day>-<year>
    (מקרים ישנים נעדרים מה-year, אז ננסה שניהם.)
    """
    month = target_date.strftime("%B").lower()
    day   = target_date.day
    year  = target_date.year
    base  = f"highest-temperature-in-{MARKET_CITY_SLUG}-on-{month}-{day}"
    return [f"{base}-{year}", base]


def broad_scan(
    limit: int = BROAD_SCAN_LIMIT,
    required_keywords: Optional[List[str]] = None,
    any_keywords: Optional[List[str]] = None,
) -> List[dict]:
    """
    סריקה רחבה של אירועים פעילים. מחזירה את מי שכותרתו:
    (א) מכילה את כל המילים מ-required_keywords,
    (ב) ומכילה לפחות אחת מ-any_keywords.
    """
    req = [k.lower() for k in (required_keywords or MARKET_KEYWORDS_REQUIRED)]
    anyk = [k.lower() for k in (any_keywords      or MARKET_KEYWORDS_ANY)]
    matches, offset, page = [], 0, 100
    while offset < limit:
        batch = _http_get(f"{GAMMA_BASE}/events", {
            "active":   "true",
            "closed":   "false",
            "limit":    min(page, limit - offset),
            "offset":   offset,
        })
        if not isinstance(batch, list) or not batch:
            break
        for e in batch:
            title = (e.get("title") or "").lower()
            if all(k in title for k in req) and (not anyk or any(k in title for k in anyk)):
                matches.append(e)
        if len(batch) < page:
            break
        offset += page
    log.info("broad scan: בדקנו %d אירועים, %d תואמים", offset + len(batch) if isinstance(batch, list) else offset, len(matches))
    return matches

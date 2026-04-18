"""
Orchestrator — סורק את כל הערים ברשימת CITIES, מחשב איתותים, מעדכן
לוג ובצעים, ומפיק דשבורד.

תהליך לכל עיר:
  1. שליפת תחזיות 5 מודלים
  2. שליפת אנסמבלים (ECMWF EPS + NOAA GEFS) לכל תאריך
  3. תצפית METAR חיה ליום הנוכחי + תחזית לשעות שנותרו
  4. זיהוי אירוע Polymarket לכל תאריך
  5. חישוב edge + signal לכל תאריך
  6. רישום איתותי קנייה ללוג paper trading

אחרי כל הערים:
  7. שליפת METAR היסטורי + ישוב איתותים סגורים
  8. חישוב מדדי דיוק ו-P&L
  9. רינדור HTML
"""
import datetime as dt
import json
import logging
import os
from typing import List, Optional
from zoneinfo import ZoneInfo

from accuracy import (
    append_forecast_snapshot, compute_model_scores, refresh_observations_metar,
)
from arbitrage import compute_arbitrage
from exports import export_all
from prices import record_market_snapshot
from config import (
    CITIES, HISTORY_JSON, HISTORY_MAX_ENTRIES,
    MIN_MODELS_REQUIRED, OUTLIER_THRESHOLD_C,
    OUTPUT_DIR, OUTPUT_HTML, OUTPUT_JSON,
    TIMEZONE_TZ, USER_TZ, USER_TZ_NAME,
)
from dashboard import render_dashboard
from edge import classify_signal, compute_edges
from markets import (
    broad_scan, build_candidate_slugs,
    event_to_contracts, fetch_event_by_slug,
)
from metar import fetch_metar_observations
from signals import (
    compute_performance, record_signals, settle_pending_signals,
)
from weather import (
    consensus, detect_outliers,
    fetch_ensemble_spread, fetch_forecasts,
    fetch_remaining_hourly_forecast,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def find_event_for_date(city: dict, target_date: dt.date) -> Optional[dict]:
    for slug in build_candidate_slugs(city, target_date):
        try:
            ev = fetch_event_by_slug(slug)
        except Exception as e:
            log.warning("[%s] slug lookup נכשל ל-%s: %s",
                        city["key"], slug, e)
            continue
        if ev and ev.get("markets"):
            return ev

    log.info("[%s] slug ישיר נכשל — עוברים לסריקה רחבה", city["key"])
    target_token = f"{target_date.strftime('%B').lower()} {target_date.day}"
    city_name_lower = city["polymarket_city_slug"].lower()
    try:
        events = broad_scan()
    except Exception as e:
        log.error("[%s] broad_scan נכשל: %s", city["key"], e)
        return None
    for e in events:
        title = (e.get("title") or "").lower()
        if city_name_lower in title and target_token in title:
            return e
    return None


def run_city_date(city: dict, target_date: dt.date, forecasts: dict,
                  ts_iso: str, observation: Optional[dict] = None,
                  ensemble: Optional[dict] = None) -> dict:
    per_model = forecasts.get(target_date.isoformat(), {})
    outliers = detect_outliers(per_model, OUTLIER_THRESHOLD_C)
    cons = consensus(per_model, outliers=outliers)
    if ensemble:
        cons["ensemble"] = ensemble

    append_forecast_snapshot(
        city_key=city["key"],
        target_date=target_date,
        per_model=per_model,
        consensus_mean=cons.get("mean"),
        consensus_std=cons.get("std"),
        ts_iso=ts_iso,
    )

    ev = find_event_for_date(city, target_date)
    contracts = event_to_contracts(ev) if ev else []

    edges: List[dict] = []
    signal = {
        "action": "NO_DATA", "best": None,
        "rationale": "אין מספיק נתוני מודלים או חוזים להסיק איתות.",
    }
    if cons["n"] >= MIN_MODELS_REQUIRED and cons["mean"] is not None and contracts:
        ensemble_std = (ensemble or {}).get("combined_std")
        edges = compute_edges(contracts, cons["mean"], cons["std"],
                              observation=observation,
                              ensemble_std=ensemble_std)
        signal = classify_signal(edges)
    elif cons["n"] < MIN_MODELS_REQUIRED:
        signal["rationale"] = (
            f"רק {cons['n']}/{len(cons.get('all_models') or {})} מודלים זמינים — "
            f"פחות מהסף המינימלי ({MIN_MODELS_REQUIRED})."
        )
    elif not contracts:
        signal["rationale"] = "אירוע Polymarket לא נמצא או אין בו חוזים סחירים."

    arbitrage = compute_arbitrage(contracts) if contracts else None

    # רישום איתות ללוג paper trading (רק אם זו קנייה), כולל זמן-לסגירה
    event_end = ev.get("endDate") if ev else None
    record_signals(city["key"], target_date, signal, ts_iso,
                   event_end=event_end)

    # מעקב מחירי שוק לאורך זמן (rate-limited ל-30 דק׳ ל-(עיר,יום))
    if contracts:
        try:
            record_market_snapshot(city["key"], target_date, contracts,
                                    edges, event_end, ts_iso)
        except Exception as e:
            log.warning("[%s] רישום snapshot מחירים נכשל: %s",
                        city["key"], e)

    return {
        "target_date": target_date.isoformat(),
        "consensus":   cons,
        "event":       ({"title":   ev.get("title"),
                         "slug":    ev.get("slug"),
                         "endDate": ev.get("endDate")} if ev else None),
        "edges":       edges,
        "signal":      signal,
        "observation": observation,
        "arbitrage":   arbitrage,
    }


def scan_city(city: dict, ts_iso: str, now) -> dict:
    """
    סריקה מלאה של עיר אחת ליום הנוכחי + מחר לפי אזור הזמן שלה.
    קריטי שנשתמש באזור הזמן של העיר עצמה, לא של ברירת המחדל —
    אחרת ערים שאחרי חצי-לילה יחפשו תחזית לתאריך עבר ויחזרו ריקות.
    """
    city_tz = ZoneInfo(city["timezone"])
    today_city = now.astimezone(city_tz).date()
    target_dates = [today_city, today_city + dt.timedelta(days=1)]

    # 1. תחזיות 5 מודלים
    try:
        forecasts = fetch_forecasts(city, forecast_days=4)
    except Exception as e:
        log.error("[%s] שליפת תחזיות נכשלה: %s", city["key"], e)
        forecasts = {}

    # 2. METAR היום + תחזית שעות שנותרו
    metar = None; remaining = None
    try:
        metar = fetch_metar_observations(city, now)
    except Exception as e:
        log.warning("[%s] METAR נכשל: %s", city["key"], e)
    try:
        remaining = fetch_remaining_hourly_forecast(city, now)
    except Exception as e:
        log.warning("[%s] תחזית שעות-שנותרו נכשלה: %s", city["key"], e)

    observation_today = None
    if metar:
        observation_today = {
            **metar,
            "remaining_forecast_max": (remaining or {}).get("remaining_forecast_max"),
            "hours_remaining":        (remaining or {}).get("hours_remaining", 0),
        }
        log.info("[%s] METAR max=%d°C @ %s (%d דיווחים, remaining=%s)",
                 city["key"], metar["observed_max_int"],
                 metar.get("peak_time_local"), metar.get("report_count"),
                 observation_today["remaining_forecast_max"])

    # 3. אנסמבלים לכל תאריך
    ensembles: dict = {}
    for d in target_dates:
        try:
            eps = fetch_ensemble_spread(city, d)
            if eps:
                ensembles[d.isoformat()] = eps
        except Exception as e:
            log.warning("[%s] ensemble נכשל לתאריך %s: %s",
                        city["key"], d, e)

    # 4. הרצת ניתוח לכל תאריך
    runs = []
    for d in target_dates:
        obs_for_date = observation_today if d == today_city else None
        eps_for_date = ensembles.get(d.isoformat())
        run = run_city_date(city, d, forecasts, ts_iso,
                             observation=obs_for_date,
                             ensemble=eps_for_date)
        runs.append(run)
        sig = run["signal"]; best = (sig.get("best") or {})
        best_label = (best.get("bucket") or {}).get("label", "—")
        log.info("[%s] %s → %s (%s)",
                 city["key"], run["target_date"], sig["action"], best_label)

    return {
        "key":             city["key"],
        "display_name_he": city["display_name_he"],
        "display_name_en": city["display_name_en"],
        "wu_url_part":     city["wu_url_part"],
        "unit":            city["unit"],
        "timezone":        city["timezone"],
        "runs":            runs,
    }


def _history_row(city_key: str, run: dict) -> dict:
    sig  = run.get("signal") or {}
    best = sig.get("best") or {}
    cons = run.get("consensus") or {}
    return {
        "city":        city_key,
        "target_date": run["target_date"],
        "action":      sig.get("action"),
        "best_label":  (best.get("bucket") or {}).get("label"),
        "best_edge":   best.get("edge"),
        "mu":          cons.get("mean"),
        "sigma":       cons.get("std"),
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now_london = dt.datetime.now(TIMEZONE_TZ)
    now_user = now_london.astimezone(USER_TZ)
    ts_iso = now_london.isoformat()

    # שעונים להצגה בכותרת — לכל עיר וגם לזמן המשתמש
    city_times: List[dict] = []
    for city in CITIES:
        tz = ZoneInfo(city["timezone"])
        t_local = now_london.astimezone(tz)
        city_times.append({
            "key":  city["key"],
            "name": city["display_name_he"],
            "time": t_local.strftime("%H:%M"),
            "date": t_local.strftime("%Y-%m-%d"),
        })
    city_times.append({
        "key":  "user",
        "name": "ישראל",
        "time": now_user.strftime("%H:%M"),
        "date": now_user.strftime("%Y-%m-%d"),
    })

    # סריקה של כל הערים
    cities_data = []
    for city in CITIES:
        try:
            cities_data.append(scan_city(city, ts_iso, now_london))
        except Exception as e:
            log.error("[%s] סריקה נכשלה לגמרי: %s", city["key"], e)

    # עדכון תצפיות + ישוב איתותים פתוחים + מדדי דיוק
    try:
        observations = refresh_observations_metar()
    except Exception as e:
        log.warning("רענון תצפיות נכשל: %s", e)
        observations = {}
    try:
        settle_pending_signals(observations)
    except Exception as e:
        log.warning("ישוב איתותים נכשל: %s", e)
    try:
        accuracy = compute_model_scores()
    except Exception as e:
        log.warning("חישוב דיוק נכשל: %s", e)
        accuracy = None
    try:
        performance = compute_performance()
    except Exception as e:
        log.warning("חישוב ביצועים נכשל: %s", e)
        performance = None

    payload = {
        "generated_at":         ts_iso,
        "generated_at_utc_ms":  int(now_london.timestamp() * 1000),
        "generated_local":      now_london.strftime("%H:%M"),
        "generated_user":       now_user.strftime("%H:%M"),
        "generated_date_local": now_london.strftime("%Y-%m-%d"),
        "timezone_local":       str(TIMEZONE_TZ),
        "timezone_user":        USER_TZ_NAME,
        "city_times":           city_times,
        "cities":               cities_data,
        "accuracy":             accuracy,
        "performance":          performance,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    # היסטוריה תמציתית (לגרפים עתידיים)
    history = []
    if os.path.exists(HISTORY_JSON):
        try:
            with open(HISTORY_JSON, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    entry = {"ts": ts_iso, "rows": []}
    for cd in cities_data:
        for r in cd.get("runs", []):
            entry["rows"].append(_history_row(cd["key"], r))
    history.append(entry)
    history = history[-HISTORY_MAX_ENTRIES:]
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, default=str)

    # יצוא CSV + XLSX לצריכה חיצונית ב-Excel
    try:
        export_all(performance or {}, accuracy or {}, ts_iso)
    except Exception as e:
        log.warning("יצוא XLSX/CSV נכשל: %s", e)

    html = render_dashboard(payload)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    log.info("נכתבו: %s, %s", OUTPUT_HTML, OUTPUT_JSON)


if __name__ == "__main__":
    main()

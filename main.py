"""
Orchestrator — נקודת הכניסה:
1. שולף תחזיות מ-5 מודלים
2. מזהה חריגים בין-מודלים ומסיר אותם מהקונצנזוס
3. מוצא את אירוע Polymarket לתאריכים היום+מחר
4. מחשב הסתברויות ו-Edge לכל bucket
5. שומר לוג תחזיות + מרענן תצפיות + מחשב מדדי דיוק
6. מפיק HTML סטטי + JSON
"""
import datetime as dt
import json
import logging
import os
from typing import Optional

from accuracy import (
    append_forecast_snapshot, compute_model_scores, refresh_observations,
)
from config import (
    HISTORY_JSON, HISTORY_MAX_ENTRIES,
    MIN_MODELS_REQUIRED,
    OUTLIER_THRESHOLD_C,
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


def find_event_for_date(target_date: dt.date) -> Optional[dict]:
    """קודם ננסה slug ישיר (מהיר), ואז נפנה לסריקה רחבה אם נכשל."""
    for slug in build_candidate_slugs(target_date):
        try:
            ev = fetch_event_by_slug(slug)
        except Exception as e:
            log.warning("slug lookup failed for %s: %s", slug, e)
            continue
        if ev and ev.get("markets"):
            log.info("נמצא אירוע דרך slug: %s", slug)
            return ev

    log.info("slug ישיר נכשל — עוברים לסריקה רחבה של Polymarket")
    target_token = f"{target_date.strftime('%B').lower()} {target_date.day}"
    try:
        events = broad_scan()
    except Exception as e:
        log.error("broad_scan נכשל: %s", e)
        return None
    for e in events:
        title = (e.get("title") or "").lower()
        if target_token in title:
            log.info("נמצא אירוע דרך סריקה רחבה: %s", e.get("slug"))
            return e
    return None


def run_for_date(target_date: dt.date, forecasts: dict, ts_iso: str,
                 observation: Optional[dict] = None,
                 ensemble: Optional[dict] = None) -> dict:
    per_model = forecasts.get(target_date.isoformat(), {})
    outliers = detect_outliers(per_model, OUTLIER_THRESHOLD_C)
    cons = consensus(per_model, outliers=outliers)
    if ensemble:
        cons["ensemble"] = ensemble  # מצורף לקונצנזוס לתצוגה + שקיפות

    # לוג התחזית בכל הרצה (כולל חריגים, כדי שנוכל לצבור דיוק היסטורי)
    append_forecast_snapshot(
        target_date=target_date,
        per_model=per_model,
        consensus_mean=cons.get("mean"),
        consensus_std=cons.get("std"),
        ts_iso=ts_iso,
    )

    ev = find_event_for_date(target_date)
    contracts = event_to_contracts(ev) if ev else []

    edges, signal = [], {
        "action": "NO_DATA", "best": None,
        "rationale": "אין מספיק נתוני מודלים או חוזים כדי להסיק איתות.",
    }
    if cons["n"] >= MIN_MODELS_REQUIRED and cons["mean"] is not None and contracts:
        ensemble_std = (ensemble or {}).get("std")
        edges = compute_edges(contracts, cons["mean"], cons["std"],
                              observation=observation,
                              ensemble_std=ensemble_std)
        signal = classify_signal(edges)
    elif cons["n"] < MIN_MODELS_REQUIRED:
        signal["rationale"] = (
            f"רק {cons['n']}/{len(cons.get('all_models') or {})} מודלים זמינים ולא חריגים — "
            f"פחות מהסף המינימלי ({MIN_MODELS_REQUIRED}). ממתינים לנתונים נוספים."
        )
    elif not contracts:
        signal["rationale"] = "אירוע Polymarket לא נמצא או אין בו חוזים סחירים לתאריך זה."

    return {
        "target_date": target_date.isoformat(),
        "consensus":   cons,
        "event":       ({"title":   ev.get("title"),
                         "slug":    ev.get("slug"),
                         "endDate": ev.get("endDate")} if ev else None),
        "edges":       edges,
        "signal":      signal,
        "observation": observation,
    }


def _history_row(run: dict) -> dict:
    sig  = run.get("signal") or {}
    best = sig.get("best") or {}
    cons = run.get("consensus") or {}
    return {
        "target_date": run["target_date"],
        "action":      sig.get("action"),
        "best_label":  (best.get("bucket") or {}).get("label"),
        "best_edge":   best.get("edge"),
        "mu":          cons.get("mean"),
        "sigma":       cons.get("std"),
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now = dt.datetime.now(TIMEZONE_TZ)
    today = now.date()
    ts_iso = now.isoformat()

    try:
        forecasts = fetch_forecasts(forecast_days=4)
    except Exception as e:
        log.error("שליפת תחזיות נכשלה לחלוטין: %s", e)
        forecasts = {}

    # תצפיות אמיתיות של היום: METAR חי מתחנת EGLC (מקור הרזולוציה של Polymarket)
    # + תחזית שעתית לשעות שנותרו (לחישוב הסתברות לחציית השיא עד סוף היום).
    observation_today = None
    try:
        metar = fetch_metar_observations(now)
    except Exception as e:
        log.warning("METAR fetch exception: %s", e)
        metar = None
    try:
        remaining = fetch_remaining_hourly_forecast(now)
    except Exception as e:
        log.warning("שליפת תחזית שעות-שנותרו נכשלה: %s", e)
        remaining = None

    if metar:
        observation_today = {
            "observed_max_int":       metar["observed_max_int"],
            "peak_time_local":        metar.get("peak_time_local"),
            "report_count":           metar.get("report_count"),
            "latest_time_local":      metar.get("latest_time_local"),
            "latest_temp":            metar.get("latest_temp"),
            "raw_sample":             metar.get("raw_sample"),
            "remaining_forecast_max": (remaining or {}).get("remaining_forecast_max"),
            "hours_remaining":        (remaining or {}).get("hours_remaining", 0),
        }
        log.info("METAR היום: max=%d°C (שיא בשעה %s, %d דיווחים). "
                 "נותרו %d שעות עם תחזית max=%s°C",
                 metar["observed_max_int"],
                 metar.get("peak_time_local"),
                 metar.get("report_count"),
                 observation_today["hours_remaining"],
                 observation_today["remaining_forecast_max"])

    target_dates = [today, today + dt.timedelta(days=1)]

    # ECMWF EPS — 50 חברי ensemble לכל תאריך, כדי לאמוד σ סטטיסטי
    ensembles = {}
    for d in target_dates:
        try:
            eps = fetch_ensemble_spread(d)
            if eps:
                ensembles[d.isoformat()] = eps
                log.info("EPS %s: %d חברים, mean=%.2f°C, std=%.2f°C, range=%.1f-%.1f",
                         d.isoformat(), eps["n_members"],
                         eps["mean"], eps["std"], eps["min"], eps["max"])
        except Exception as e:
            log.warning("EPS נכשל לתאריך %s: %s", d, e)

    runs = [run_for_date(d, forecasts, ts_iso,
                         observation=(observation_today if d == today else None),
                         ensemble=ensembles.get(d.isoformat()))
            for d in target_dates]

    # רענון תצפיות לתאריכים שחלפו + חישוב מדדי דיוק
    try:
        refresh_observations()
        accuracy = compute_model_scores()
    except Exception as e:
        log.warning("חישוב דיוק נכשל: %s", e)
        accuracy = None

    now_user = now.astimezone(USER_TZ)
    payload = {
        "generated_at":         ts_iso,                       # ISO עם offset לונדון
        "generated_at_utc_ms":  int(now.timestamp() * 1000),  # Unix ms (למונה "לפני X דקות")
        "generated_local":      now.strftime("%H:%M"),        # שעה בלונדון
        "generated_user":       now_user.strftime("%H:%M"),   # שעה בישראל
        "generated_date_local": now.strftime("%Y-%m-%d"),
        "timezone_local":       str(TIMEZONE_TZ),
        "timezone_user":        USER_TZ_NAME,
        "runs":                 runs,
        "accuracy":             accuracy,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    # עדכון היסטוריה תמציתית (לצורך גרפים עתידיים)
    history = []
    if os.path.exists(HISTORY_JSON):
        try:
            with open(HISTORY_JSON, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception as e:
            log.warning("לא הצלחתי לקרוא היסטוריה קודמת: %s — מתחיל מחדש", e)
            history = []
    history.append({"ts": ts_iso,
                    "runs": [_history_row(r) for r in runs]})
    history = history[-HISTORY_MAX_ENTRIES:]
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, default=str)

    html = render_dashboard(payload)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    log.info("נכתבו: %s, %s, %s", OUTPUT_HTML, OUTPUT_JSON, HISTORY_JSON)
    for r in runs:
        log.info("• %s → %s (%s)",
                 r["target_date"],
                 (r["signal"] or {}).get("action"),
                 ((r["signal"] or {}).get("best") or {}).get("bucket", {}).get("label"))


if __name__ == "__main__":
    main()

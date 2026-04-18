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
    TIMEZONE_TZ,
)
from dashboard import render_dashboard
from edge import classify_signal, compute_edges
from markets import (
    broad_scan, build_candidate_slugs,
    event_to_contracts, fetch_event_by_slug,
)
from weather import consensus, detect_outliers, fetch_forecasts

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


def run_for_date(target_date: dt.date, forecasts: dict, ts_iso: str) -> dict:
    per_model = forecasts.get(target_date.isoformat(), {})
    outliers = detect_outliers(per_model, OUTLIER_THRESHOLD_C)
    cons = consensus(per_model, outliers=outliers)

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
        edges = compute_edges(contracts, cons["mean"], cons["std"])
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

    target_dates = [today, today + dt.timedelta(days=1)]
    runs = [run_for_date(d, forecasts, ts_iso) for d in target_dates]

    # רענון תצפיות לתאריכים שחלפו + חישוב מדדי דיוק
    try:
        refresh_observations()
        accuracy = compute_model_scores()
    except Exception as e:
        log.warning("חישוב דיוק נכשל: %s", e)
        accuracy = None

    payload = {
        "generated_at": ts_iso,
        "timezone":     str(TIMEZONE_TZ),
        "runs":         runs,
        "accuracy":     accuracy,
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

"""
רינדור HTML סטטי רב-עירי.

מבנה:
  ┌ header: כותרת + שעונים + מחוון גיל נתונים
  ├ סקירה מהירה: טבלה של כל הערים × (היום, מחר) עם האיתות
  ├ ביצועי paper-trading מצטברים
  ├ פרטי כל עיר בנפרד (כרטיסיה מתקפלת)
  ├ איכות מודלים לאורך זמן
  └ footer

העיקרון: המסך הראשי חייב להיות קריא ומידי. כל פרט נוסף נגיש בלחיצה.
"""
import html
from typing import Optional

from config import CITIES, TOP_N_BUCKETS, WEATHER_MODELS


ACTION_HE = {
    "STRONG_BUY": "קנייה חזקה",
    "BUY":        "קנייה",
    "HOLD":       "המתנה",
    "AVOID":      "הימנעות",
    "NO_DATA":    "אין נתונים",
}
ACTION_COLOR = {
    "STRONG_BUY": "#5FC87A",
    "BUY":        "#B5EBBF",
    "HOLD":       "#7A858C",
    "AVOID":      "#E45858",
    "NO_DATA":    "#3A464E",
}

HELP = {
    "consensus":     "ממוצע תחזיות המודלים לאחר הסרת חריגים.",
    "sigma":         "כמה המודלים מסכימים. σ גבוה = אי-ודאות גבוהה.",
    "ensemble":      "סטיית התקן בין חברי אנסמבל — מדד סטטיסטי של אי-הוודאות של התחזית.",
    "prob_ours":     "ההסתברות שלנו ל-bucket, לפי התפלגות נורמלית.",
    "market_price":  "מחיר YES בשוק = ההסתברות שהשוק מתמחר.",
    "edge":          "פער בין המודל לשוק. חיובי = הזדמנות קנייה.",
    "kelly":         "אחוז מהבנקרול שמומלץ לפוזיציה.",
    "ev":            "רווח צפוי על כל 1$ מושקע.",
    "volume":        "נפח המסחר בדולרים בחוזה.",
    "metar":         "תחנת METAR — מקור המדידה שממנו Polymarket מיישב.",
    "arb":           "הזדמנות רווח מובטח ללא תלות בתחזית.",
    "paper":         "ניטור ביצועים מדומים: כל איתות קנייה נרשם, ואחרי התצפית מסתכמים רווח/הפסד.",
}


def _esc(s) -> str:
    return html.escape(str(s), quote=True) if s is not None else ""


def _fmt(v: Optional[float], suffix="", digits=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}{suffix}"


def _pct(v: Optional[float], digits=1, signed=True) -> str:
    if v is None:
        return "—"
    if signed:
        return f"{v*100:+.{digits}f}%"
    return f"{v*100:.{digits}f}%"


def _info(key: str) -> str:
    return f'<span class="info" title="{_esc(HELP[key])}">ⓘ</span>'


# ─────────────────────────────────────────────
# סקירה כוללת
# ─────────────────────────────────────────────

def _cell_for_run(run: dict) -> str:
    sig = run.get("signal") or {}
    action = sig.get("action", "NO_DATA")
    color = ACTION_COLOR[action]
    best = (sig.get("best") or {}).get("bucket") or {}
    label = best.get("label", "—")
    action_he = ACTION_HE[action]
    return (f'<td class="cell" style="--sig:{color}">'
            f'<div class="cell__action">{_esc(action_he)}</div>'
            f'<div class="cell__label">{_esc(label) if action not in ("HOLD","NO_DATA") else ""}</div>'
            f'</td>')


def _render_overview(payload: dict) -> str:
    cities = payload.get("cities", []) or []
    if not cities:
        return ""
    # ניחוש: היום הוא runs[0], מחר runs[1]
    dates = []
    if cities and cities[0].get("runs"):
        dates = [r["target_date"] for r in cities[0]["runs"]]

    head_cells = "".join(f"<th>{_esc(d)}</th>" for d in dates)
    rows = []
    for c in cities:
        runs = c.get("runs") or []
        cells = "".join(_cell_for_run(r) for r in runs)
        rows.append(
            f'<tr>'
            f'<th class="city">'
            f'<a href="#city-{_esc(c["key"])}">{_esc(c["display_name_he"])}</a>'
            f'</th>{cells}</tr>'
        )
    return f"""
    <section class="overview">
      <h2>סקירה — כל הערים</h2>
      <table>
        <thead><tr><th></th>{head_cells}</tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
      <p class="muted small">לחיצה על שם עיר פותחת את הפרטים שלה למטה.</p>
    </section>
    """


# ─────────────────────────────────────────────
# Paper-trading performance
# ─────────────────────────────────────────────

def _render_performance(perf: Optional[dict]) -> str:
    if not perf:
        return ""
    total = perf.get("total", 0)
    if total == 0:
        return f"""
        <section class="card card--perf">
          <h2>ביצועי paper-trading {_info("paper")}</h2>
          <p class="muted">
            עדיין לא נרשם איתות קנייה. המערכת רושמת כל קנייה חזקה/רגילה
            אוטומטית, וברגע שהיום של היעד נסגר, התצפית האמיתית קובעת
            אם ה-bucket זכה — והרווח/הפסד המדומה מחושב אוטומטית.
          </p>
        </section>
        """

    win_rate = perf.get("win_rate")
    realized = perf.get("realized_pnl") or 0
    expected = perf.get("expected_pnl") or 0
    pending_stake = perf.get("pending_stake") or 0
    roi = perf.get("roi_on_settled_stake")

    pnl_cls = "pos" if realized > 0 else ("neg" if realized < 0 else "")

    # פיצול לפי אסטרטגיה — שני תיקים מקבילים
    STRATEGY_LABEL = {"max_edge": "יתרון מקסימלי", "most_likely": "הסביר ביותר"}
    strat_rows_html = []
    by_strategy = perf.get("by_strategy") or {}
    for s_name in ("max_edge", "most_likely"):
        s = by_strategy.get(s_name) or {}
        if s.get("total", 0) == 0:
            continue
        s_pnl = s.get("realized_pnl") or 0
        cls = "pos" if s_pnl > 0 else ("neg" if s_pnl < 0 else "")
        wr = s.get("win_rate")
        wr_txt = f"{wr*100:.0f}%" if wr is not None else "—"
        roi = s.get("roi_on_settled_stake")
        roi_txt = f"{roi*100:+.1f}%" if roi is not None else "—"
        strat_rows_html.append(
            f'<tr>'
            f'<td class="t-label">{_esc(STRATEGY_LABEL[s_name])}</td>'
            f'<td>{s.get("total",0)}</td>'
            f'<td>{s.get("won",0)}</td>'
            f'<td>{s.get("lost",0)}</td>'
            f'<td>{s.get("pending",0)}</td>'
            f'<td>{wr_txt}</td>'
            f'<td class="{cls}">${s_pnl:+.2f}</td>'
            f'<td>{roi_txt}</td>'
            f'</tr>'
        )
    strat_table = ""
    if strat_rows_html:
        strat_table = f"""
        <h3 class="perf__sub">השוואת אסטרטגיות</h3>
        <p class="muted small">שני תיקים מדומים מקבילים: "יתרון מקסימלי" מהמר על ה-bucket עם הפער הגדול ביותר; "הסביר ביותר" מהמר על ה-bucket עם ההסתברות הגבוהה ביותר שגם עובר את סף הקנייה.</p>
        <table class="perf">
          <thead><tr>
            <th>אסטרטגיה</th><th>סה"כ</th><th>זכיות</th><th>הפסדים</th>
            <th>פתוחים</th><th>אחוז זכייה</th><th>P&L</th><th>ROI</th>
          </tr></thead>
          <tbody>{"".join(strat_rows_html)}</tbody>
        </table>
        """

    # פיצול לפי תזמון (early / mid / late)
    TIMING_LABEL = {"early": "מוקדם (>8 שעות)", "mid": "אמצע (1-8 שעות)", "late": "מאוחר (<שעה)"}
    timing_rows_html = []
    by_timing = perf.get("by_timing") or {}
    for t_name in ("early", "mid", "late"):
        t = by_timing.get(t_name) or {}
        if t.get("total", 0) == 0:
            continue
        t_pnl = t.get("realized_pnl") or 0
        cls = "pos" if t_pnl > 0 else ("neg" if t_pnl < 0 else "")
        wr = t.get("win_rate")
        wr_txt = f"{wr*100:.0f}%" if wr is not None else "—"
        roi = t.get("roi_on_settled_stake")
        roi_txt = f"{roi*100:+.1f}%" if roi is not None else "—"
        timing_rows_html.append(
            f'<tr>'
            f'<td class="t-label">{_esc(TIMING_LABEL[t_name])}</td>'
            f'<td>{t.get("total",0)}</td>'
            f'<td>{t.get("won",0)}</td>'
            f'<td>{t.get("lost",0)}</td>'
            f'<td>{t.get("pending",0)}</td>'
            f'<td>{wr_txt}</td>'
            f'<td class="{cls}">${t_pnl:+.2f}</td>'
            f'<td>{roi_txt}</td>'
            f'</tr>'
        )
    timing_table = ""
    if timing_rows_html:
        timing_table = f"""
        <h3 class="perf__sub">פיצול לפי תזמון ההימור</h3>
        <p class="muted small">כל עסקה מתויגת לפי כמה דקות נותרו עד שהאירוע בפולימארקט נסגר. מעניין לראות לאורך זמן אם הימורים מאוחרים (השוק יותר מיושב) מצליחים יותר מהימורים מוקדמים.</p>
        <table class="perf">
          <thead><tr>
            <th>תזמון</th><th>סה"כ</th><th>זכיות</th><th>הפסדים</th>
            <th>פתוחים</th><th>אחוז זכייה</th><th>P&L</th><th>ROI</th>
          </tr></thead>
          <tbody>{"".join(timing_rows_html)}</tbody>
        </table>
        """

    per_city_rows = []
    for city_key, slot in (perf.get("per_city") or {}).items():
        cls = "pos" if (slot["pnl"] or 0) > 0 else ("neg" if (slot["pnl"] or 0) < 0 else "")
        per_city_rows.append(
            f'<tr>'
            f'<td>{_esc(city_key)}</td>'
            f'<td>{slot["total"]}</td>'
            f'<td>{slot["won"]}</td>'
            f'<td>{slot["lost"]}</td>'
            f'<td>{slot["pending"]}</td>'
            f'<td class="{cls}">${slot["pnl"]:+.2f}</td>'
            f'</tr>'
        )
    city_table = ""
    if per_city_rows:
        city_table = f"""
        <h3 class="perf__sub">פיצול לפי עיר (כל האסטרטגיות)</h3>
        <table class="perf">
          <thead><tr>
            <th>עיר</th><th>סה"כ</th><th>זכיות</th><th>הפסדים</th>
            <th>פתוחים</th><th>P&L מצטבר</th>
          </tr></thead>
          <tbody>{"".join(per_city_rows)}</tbody>
        </table>
        """

    return f"""
    <section class="card card--perf">
      <h2>ביצועי paper-trading {_info("paper")}</h2>
      <div class="perf__grid">
        <div><span class="muted">איתותים סה"כ</span><strong>{total}</strong></div>
        <div><span class="muted">סגורים</span><strong>{perf.get("settled",0)}</strong></div>
        <div><span class="muted">פתוחים</span><strong>{perf.get("pending",0)}</strong></div>
        <div><span class="muted">אחוז זכייה</span><strong>{_pct(win_rate, 0, signed=False)}</strong></div>
        <div><span class="muted">P&L ממומש</span><strong class="{pnl_cls}">${realized:+.2f}</strong></div>
        <div><span class="muted">P&L צפוי (EV)</span><strong>${expected:+.2f}</strong></div>
        <div><span class="muted">סטייק פתוח</span><strong>${pending_stake:.2f}</strong></div>
        <div><span class="muted">ROI על סטייק סגור</span><strong>{_pct(roi, 1, signed=True) if roi is not None else "—"}</strong></div>
      </div>
      {strat_table}
      {timing_table}
      {city_table}
    </section>
    """


# ─────────────────────────────────────────────
# כרטיסיה של עיר בודדת
# ─────────────────────────────────────────────

def _render_model_chips_compact(cons: dict) -> str:
    """תצוגה קומפקטית — רק אם יש חריג או σ גבוה נבלט."""
    outliers = cons.get("outliers") or {}
    if not outliers:
        return ""  # נסתר כברירת מחדל כשאין חריג
    names = ", ".join(outliers.keys())
    return (f'<div class="banner banner--warn">'
            f'⚠ מודלים חריגים שהוסרו: {_esc(names)}.'
            f'</div>')


def _render_metar_panel(run: dict, city: dict) -> str:
    obs = run.get("observation") or {}
    if obs.get("observed_max_int") is None:
        return ""
    om   = obs["observed_max_int"]
    pt   = obs.get("peak_time_local") or "—"
    rpt  = obs.get("report_count", 0)
    lt   = obs.get("latest_time_local") or "—"
    ltemp = obs.get("latest_temp")
    age   = obs.get("latest_age_min")
    rfc   = obs.get("remaining_forecast_max")
    raw   = obs.get("raw_sample")
    post_peak = rfc is None or om >= rfc
    state_txt = "השיא היומי כבר עבר — התוצאה כמעט נעולה." if post_peak else "השיא היומי עדיין יכול לקרות."
    rem_html = (f'תחזית לשעות שנותרו: <strong>{rfc:.1f}°C</strong>. '
                if rfc is not None else '')

    age_cls = ""
    if isinstance(age, int):
        if age <= 35:    age_cls = " age-fresh"
        elif age <= 70:  age_cls = " age-mid"
        else:            age_cls = " age-stale"
    age_txt = f" (לפני {age} דק׳)" if isinstance(age, int) else ""
    latest_html = (f'דיווח אחרון ב-<strong class="metar-age{age_cls}">{_esc(lt)}{age_txt}</strong>: '
                   f'<strong>{ltemp}°C</strong>. ' if ltemp is not None else '')

    try:
        ymd = run["target_date"].split("-")
        wu_url = (f"https://www.wunderground.com/history/daily/"
                  f"{city['wu_url_part']}/date/"
                  f"{int(ymd[0])}-{int(ymd[1])}-{int(ymd[2])}")
    except Exception:
        wu_url = f"https://www.wunderground.com/history/daily/{city['wu_url_part']}"

    raw_html = ""
    if raw:
        raw_html = f'<details class="metar-details"><summary>METAR גולמי</summary><code>{_esc(raw)}</code></details>'

    return (
        f'<div class="banner banner--obs">'
        f'🌡️ <strong>METAR {_esc(city["metar_station"] if "metar_station" in city else "")} {_info("metar")}</strong>: '
        f'מקסימום עד כה <strong>{om}°C</strong> '
        f'(שיא ב-<strong>{_esc(pt)}</strong>, {rpt} דיווחים). '
        f'{latest_html}'
        f'{rem_html}'
        f'{state_txt} '
        f'<a href="{wu_url}" target="_blank" rel="noopener" class="wu-link-inline">[אימות ב-Wunderground]</a>'
        f'{raw_html}'
        f'</div>'
    )


def _render_ensemble_compact(cons: dict) -> str:
    ens = cons.get("ensemble") or {}
    if not ens or not ens.get("systems"):
        return ""
    combined = ens.get("combined_std")
    agreement = ens.get("agreement_c", 0)
    if agreement < 0.3:
        agr_cls = "good"; agr_word = "הסכמה"
    elif agreement < 0.8:
        agr_cls = "mid"; agr_word = "הסכמה בינונית"
    else:
        agr_cls = "bad"; agr_word = "⚠ חוסר הסכמה"
    details = []
    for name, s in ens["systems"].items():
        details.append(f'<span class="ens-pill">{_esc(name)}: μ={s["mean"]:.2f} σ={s["std"]:.2f}</span>')
    return (
        f'<div class="ens-compact ens-compact--{agr_cls}">'
        f'<strong>ensemble:</strong> σ משולב {combined:.2f}°C · '
        f'{"".join(details)} · '
        f'<span class="ens-agr">{agr_word} ({agreement:.2f}°C)</span>'
        f'</div>'
    )


def _render_edges_table(run: dict) -> str:
    edges = run.get("edges") or []
    if not edges:
        return '<p class="muted">אין חוזים זמינים.</p>'
    sig = run.get("signal") or {}
    best       = (sig.get("best") or {})
    most_likely = (sig.get("most_likely") or {})
    best_label        = (best.get("bucket") or {}).get("label")
    likely_label      = (most_likely.get("bucket") or {}).get("label")

    sorted_by_prob = sorted(edges, key=lambda e: e["our_prob"], reverse=True)
    visible = list(sorted_by_prob[:TOP_N_BUCKETS])
    visible_labels = {e["bucket"]["label"] for e in visible}
    for must_show in (best_label, likely_label):
        if must_show and must_show not in visible_labels:
            row = next((e for e in edges if e["bucket"]["label"] == must_show), None)
            if row is not None:
                visible.append(row)
                visible_labels.add(must_show)
    type_order = {"below": 0, "single": 1, "above": 2}
    visible.sort(key=lambda e: (type_order[e["bucket"]["type"]], e["bucket"]["temp"]))

    rows = []
    for e in visible:
        lbl = e["bucket"]["label"]
        is_best   = best_label   and lbl == best_label
        is_likely = likely_label and lbl == likely_label
        edge_cls = "pos" if e["edge"] > 0 else ("neg" if e["edge"] < 0 else "")
        row_cls = "row"
        if is_best:   row_cls += " row--best"
        if is_likely: row_cls += " row--likely"
        markers = ""
        if is_best:   markers += '<span class="mark mark--best">פעולה</span>'
        if is_likely: markers += '<span class="mark mark--likely">סביר</span>'
        rows.append(
            f'<tr class="{row_cls}">'
            f'<td class="t-label">{_esc(lbl)} {markers}</td>'
            f'<td>{e["our_prob"]*100:.1f}%</td>'
            f'<td>{e["yes_price"]*100:.1f}%</td>'
            f'<td class="t-edge {edge_cls}">{_pct(e["edge"])}</td>'
            f'<td>{e["kelly"]*100:.0f}%</td>'
            f'<td class="{edge_cls}">{_pct(e["ev"])}</td>'
            f'</tr>'
        )
    return f"""
    <table class="edges">
      <thead><tr>
        <th>טמפ' (°C)</th>
        <th>הסתברות {_info('prob_ours')}</th>
        <th>שוק {_info('market_price')}</th>
        <th>יתרון {_info('edge')}</th>
        <th>Kelly {_info('kelly')}</th>
        <th>EV {_info('ev')}</th>
      </tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    """


def _render_arb(arb: Optional[dict]) -> str:
    if not arb:
        return ""
    if not arb.get("has_opportunity"):
        return ""
    profit = arb.get("best_profit_usd", 0) * 100
    roi = arb.get("roi", 0) * 100
    strategy = arb.get("best_strategy")
    title = ("מכירת YES על כל החוזים" if strategy == "sell_yes"
             else "קניית YES על כל החוזים")
    return (f'<div class="banner banner--arb">'
            f'🎯 <strong>ארביטראז׳ {_info("arb")}</strong>: '
            f'{_esc(title)}. רווח {profit:.1f} סנט לבונדל, ROI כ-{roi:.1f}%.'
            f'</div>')


def _has_active_signal(city_data: dict) -> bool:
    for r in city_data.get("runs") or []:
        act = (r.get("signal") or {}).get("action")
        if act in ("STRONG_BUY", "BUY", "AVOID"):
            return True
    return False


def _render_city_run(city: dict, run: dict) -> str:
    sig = run.get("signal") or {}
    action = sig.get("action", "NO_DATA")
    color = ACTION_COLOR[action]
    cons = run.get("consensus") or {}
    mu, std, n = cons.get("mean"), cons.get("std"), cons.get("n", 0)
    n_total = len(cons.get("all_models") or WEATHER_MODELS)
    event = run.get("event")
    event_link = ""
    if event:
        slug = _esc(event.get("slug"))
        event_link = (f'<a class="event-link" href="https://polymarket.com/event/{slug}" '
                      f'target="_blank" rel="noopener">[פתח בפולימארקט]</a>')

    return f"""
    <div class="run">
      <header class="run__head">
        <h3>{_esc(run["target_date"])}</h3>
        {event_link}
      </header>
      <div class="signal" style="--sig:{color}">
        <span class="signal__action">{ACTION_HE[action]}</span>
        <span class="signal__why">{_esc(sig.get("rationale",""))}</span>
      </div>
      {_render_model_chips_compact(cons)}
      {_render_metar_panel(run, city)}
      {_render_arb(run.get("arbitrage"))}
      <div class="cons-compact">
        <span>μ: <strong>{_fmt(mu,"°C",2)}</strong></span>
        <span>σ מודלים: <strong>{_fmt(std,"°C",2)}</strong></span>
        <span>מודלים: <strong>{n}/{n_total}</strong></span>
      </div>
      {_render_ensemble_compact(cons)}
      {_render_edges_table(run)}
    </div>
    """


def _render_city_card(city_data: dict) -> str:
    is_open = _has_active_signal(city_data)
    open_attr = " open" if is_open else ""
    runs_html = "".join(_render_city_run(city_data, r)
                         for r in (city_data.get("runs") or []))
    return f"""
    <section class="card city-card" id="city-{_esc(city_data['key'])}">
      <details class="city-details"{open_attr}>
        <summary>
          <span class="city-name">{_esc(city_data["display_name_he"])}</span>
          <span class="city-name-en muted">{_esc(city_data["display_name_en"])}</span>
        </summary>
        <div class="city-body">{runs_html}</div>
      </details>
    </section>
    """


# ─────────────────────────────────────────────
# Accuracy
# ─────────────────────────────────────────────

def _render_accuracy(acc: Optional[dict]) -> str:
    if not acc or not (acc.get("global") or {}).get("days_measured"):
        return """
        <section class="card card--acc">
          <h2>איכות מודלים לאורך זמן</h2>
          <p class="muted">
            עדיין לא נצברה היסטוריה מספקת. כל יום שחולף נשמר, תצפית METAR
            של סוף היום מצליבה אוטומטית, ומדדי הדיוק כאן מתחילים להיבנות.
          </p>
        </section>
        """
    glob = acc["global"]
    rows = []
    items = list(glob["models"].items())
    items.sort(key=lambda kv: (kv[1]["mae"] if kv[1]["mae"] is not None else 999))
    for name, s in items:
        if s["n"] == 0:
            rows.append(f'<tr><td>{_esc(name)}</td>'
                        f'<td class="muted" colspan="5">אין נתונים</td></tr>')
            continue
        mae_cls = "pos" if s["mae"] is not None and s["mae"] < 1.0 else ""
        bias_cls = "pos" if s["bias"] is not None and abs(s["bias"]) < 0.3 else ""
        rows.append(
            f'<tr>'
            f'<td class="t-label">{_esc(name)}</td>'
            f'<td class="{mae_cls}">{_fmt(s["mae"],"°C",2)}</td>'
            f'<td class="{bias_cls}">{_fmt(s["bias"],"°C",2) if s["bias"] is not None else "—"}</td>'
            f'<td>{_pct(s["hit_1c"],0,signed=False) if s["hit_1c"] is not None else "—"}</td>'
            f'<td>{_fmt(s["rank_avg"],"",2)}</td>'
            f'<td class="muted">{s["n"]}</td>'
            f'</tr>'
        )
    c = glob.get("consensus") or {}
    cons_row = ""
    if c.get("n"):
        cons_row = (
            f'<tr class="row--best">'
            f'<td class="t-label">קונצנזוס</td>'
            f'<td>{_fmt(c["mae"],"°C",2)}</td>'
            f'<td>{_fmt(c["bias"],"°C",2)}</td>'
            f'<td>{_pct(c["hit_1c"],0,signed=False) if c["hit_1c"] is not None else "—"}</td>'
            f'<td class="muted">—</td>'
            f'<td class="muted">{c["n"]}</td>'
            f'</tr>'
        )
    return f"""
    <section class="card card--acc">
      <h2>איכות מודלים לאורך זמן</h2>
      <p class="muted small">
        {glob["days_measured"]} ימים שלמים נמדדו (כל הערים). עמודת MAE = שגיאה מוחלטת ממוצעת; נמוך יותר = טוב יותר.
        עמודת הטיה קרובה לאפס = מודל ניטרלי.
      </p>
      <table class="acc">
        <thead><tr>
          <th>מודל</th><th>MAE</th><th>הטיה</th>
          <th>פגיעה ±1°C</th><th>דירוג ממוצע</th><th>ימים</th>
        </tr></thead>
        <tbody>{"".join(rows)}{cons_row}</tbody>
      </table>
    </section>
    """


# ─────────────────────────────────────────────
# Intro (מקופל כברירת מחדל)
# ─────────────────────────────────────────────

def _render_intro() -> str:
    return """
    <details class="intro">
      <summary>איך לקרוא את הלוח הזה? (מקופל)</summary>
      <div class="intro__body">
        <ul>
          <li><strong>סקירה כוללת</strong> — טבלה אחת עם כל הערים והאיתות היומי שלהן.</li>
          <li><strong>paper-trading</strong> — רווח/הפסד מדומה על כל איתות קנייה. מצטבר לאורך זמן.</li>
          <li><strong>פרטי עיר</strong> — לחיצה על שם העיר פותחת את הפרטים המלאים.</li>
          <li><strong>METAR</strong> — מקור התצפית הרשמי. מגיע חי מ-aviationweather.gov.</li>
          <li><strong>ensemble</strong> — 80 חברי מודל עצמאיים (ECMWF + GEFS). σ ביניהם = אי-ודאות אמיתית.</li>
          <li><strong>⚠ מלכודת</strong> — התצוגה החיה של Wunderground יכולה להראות ערך שונה מהטבלה ההיסטורית שממנה Polymarket מיישב. תמיד להצליב מול הטבלה ההיסטורית.</li>
        </ul>
      </div>
    </details>
    """


# ─────────────────────────────────────────────
# רינדור מרכזי
# ─────────────────────────────────────────────

def render_dashboard(payload: dict) -> str:
    gen_utc_ms = int(payload.get("generated_at_utc_ms") or 0)
    gen_local  = _esc(payload.get("generated_local", "—"))
    gen_user   = _esc(payload.get("generated_user", "—"))
    gen_date   = _esc(payload.get("generated_date_local", ""))

    city_cards = "".join(_render_city_card(c) for c in payload.get("cities", []))

    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>שכבת מודיעין כמותי — מזג אוויר</title>
<style>
  :root {{
    --bg:#0B0F12; --card:#151B20; --border:#1F2932;
    --text:#E8EDF0; --muted:#7A858C;
    --mint:#B5EBBF; --pos:#5FC87A; --neg:#E45858; --warn:#E4A858;
    --accent2:#9BD3F2;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:'Segoe UI','Heebo','Rubik',system-ui,sans-serif; }}
  body {{ padding:20px; max-width:1200px; margin:0 auto; }}
  a {{ color:var(--mint); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .muted {{ color:var(--muted); }}
  .small {{ font-size:12px; }}

  header.top {{ display:flex; justify-content:space-between; flex-wrap:wrap;
    align-items:flex-start; border-bottom:1px solid var(--border);
    padding-bottom:14px; margin-bottom:16px; gap:14px; }}
  header.top h1 {{ margin:0; font-size:22px; font-weight:600; }}
  header.top h1 span {{ color:var(--mint); }}
  header.top .ts {{ font-size:13px; text-align:left;
    display:flex; flex-direction:column; gap:3px; }}
  header.top .ts__row {{ display:flex; gap:6px; align-items:baseline; flex-wrap:wrap; }}
  header.top .ts strong {{ color:var(--text); font-weight:600; }}
  header.top .sep {{ color:var(--border); }}
  header.top .age {{ font-size:12px; padding:2px 8px; border-radius:999px;
    background:var(--border); color:var(--muted); margin-top:2px; }}
  header.top .age.fresh {{ background:color-mix(in srgb, var(--pos) 18%, transparent); color:var(--pos); }}
  header.top .age.mid   {{ background:color-mix(in srgb, var(--warn) 18%, transparent); color:var(--warn); }}
  header.top .age.stale {{ background:color-mix(in srgb, var(--neg) 18%, transparent); color:var(--neg); }}

  details.intro {{ background:var(--card); border:1px solid var(--border);
    border-radius:10px; padding:10px 14px; margin-bottom:14px; font-size:13px; }}
  details.intro summary {{ cursor:pointer; color:var(--muted); }}
  details.intro ul {{ padding-inline-start:18px; margin:8px 0; line-height:1.6; }}

  .overview {{ background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:16px; margin-bottom:16px; }}
  .overview h2 {{ margin:0 0 10px 0; font-size:16px; }}
  .overview table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  .overview th, .overview td {{ padding:8px 10px; text-align:right;
    border-bottom:1px solid var(--border); }}
  .overview th {{ color:var(--muted); font-weight:500; font-size:12px; }}
  .overview th.city {{ text-align:right; font-size:13px; color:var(--text); font-weight:600; }}
  .overview th.city a {{ color:var(--mint); }}
  .cell {{ border-right:3px solid var(--sig); padding-inline-end:8px; }}
  .cell__action {{ color:var(--sig); font-weight:700; font-size:14px; }}
  .cell__label {{ font-size:12px; color:var(--muted); margin-top:2px; }}

  .card {{ background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:18px; margin-bottom:14px; }}
  .card h2 {{ margin:0 0 10px 0; font-size:16px; }}

  .card--perf h2 {{ color:var(--mint); }}
  .perf__grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr));
    gap:10px; margin-bottom:12px; }}
  .perf__grid div {{ display:flex; flex-direction:column; padding:8px;
    background:#0F1518; border-radius:8px; }}
  .perf__grid strong {{ font-size:16px; color:var(--text); }}
  .perf__grid .pos {{ color:var(--pos); }}
  .perf__grid .neg {{ color:var(--neg); }}
  table.perf {{ width:100%; border-collapse:collapse; font-size:12px; }}
  table.perf th, table.perf td {{ text-align:right; padding:6px 8px;
    border-bottom:1px solid var(--border); }}
  table.perf th {{ color:var(--muted); font-weight:500; }}
  table.perf .pos {{ color:var(--pos); }}
  table.perf .neg {{ color:var(--neg); }}
  .perf__sub {{ margin:14px 0 6px 0; font-size:13px; color:var(--mint); }}

  .city-card {{ padding:0; overflow:hidden; }}
  .city-details summary {{ cursor:pointer; list-style:none; padding:14px 18px;
    display:flex; gap:10px; align-items:baseline;
    border-bottom:1px solid transparent; }}
  .city-details[open] summary {{ border-bottom-color:var(--border); }}
  .city-details summary::-webkit-details-marker {{ display:none; }}
  .city-name {{ font-size:17px; font-weight:600; color:var(--mint); }}
  .city-name-en {{ font-size:12px; }}
  .city-body {{ padding:14px 18px; display:flex; flex-direction:column; gap:16px; }}
  .run {{ padding-bottom:14px; border-bottom:1px dashed var(--border); }}
  .run:last-child {{ border-bottom:none; padding-bottom:0; }}
  .run__head {{ display:flex; justify-content:space-between; align-items:baseline;
    gap:10px; flex-wrap:wrap; margin-bottom:8px; }}
  .run__head h3 {{ margin:0; font-size:15px; font-weight:600; }}
  .event-link {{ font-size:12px; color:var(--mint); }}

  .signal {{ border-right:4px solid var(--sig);
    background:color-mix(in srgb, var(--sig) 10%, transparent);
    padding:8px 14px; border-radius:6px; margin-bottom:10px;
    display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; }}
  .signal__action {{ color:var(--sig); font-size:16px; font-weight:700; }}
  .signal__why {{ font-size:12px; color:var(--text); line-height:1.4; flex:1 1 300px; }}

  .banner {{ padding:8px 12px; border-radius:6px; margin:6px 0;
    font-size:12px; border:1px solid; line-height:1.55; }}
  .banner--warn {{ border-color:var(--warn);
    background:color-mix(in srgb, var(--warn) 10%, transparent);
    color:color-mix(in srgb, var(--warn) 80%, white); }}
  .banner--obs {{ border-color:var(--accent2);
    background:color-mix(in srgb, var(--accent2) 10%, transparent);
    color:color-mix(in srgb, var(--accent2) 80%, white); }}
  .banner--obs strong {{ color:var(--accent2); }}
  .banner--arb {{ border-color:#F2C94C;
    background:color-mix(in srgb, #F2C94C 10%, transparent);
    color:color-mix(in srgb, #F2C94C 85%, white); }}
  .banner--arb strong {{ color:#F2C94C; }}
  .metar-age.age-fresh {{ color:var(--pos); }}
  .metar-age.age-mid   {{ color:var(--warn); }}
  .metar-age.age-stale {{ color:var(--neg); }}
  .wu-link-inline {{ color:var(--accent2); font-size:11px; margin-inline-start:4px; }}
  .metar-details {{ margin-top:6px; font-size:11px; }}
  .metar-details summary {{ cursor:pointer; color:var(--muted); }}
  .metar-details code {{ direction:ltr; unicode-bidi:embed;
    background:#0B1114; color:var(--mint);
    padding:2px 6px; border-radius:3px; display:inline-block;
    font-family:'Consolas',monospace; margin-top:4px; }}

  .cons-compact {{ display:flex; gap:14px; font-size:13px; color:var(--muted);
    flex-wrap:wrap; margin-bottom:6px; }}
  .cons-compact strong {{ color:var(--text); font-weight:600; }}

  .ens-compact {{ display:flex; gap:8px; align-items:baseline; flex-wrap:wrap;
    font-size:12px; padding:6px 10px; border-radius:6px;
    background:color-mix(in srgb, var(--mint) 6%, transparent);
    border:1px solid color-mix(in srgb, var(--mint) 25%, transparent);
    margin-bottom:8px; }}
  .ens-compact strong {{ color:var(--mint); }}
  .ens-pill {{ padding:2px 8px; background:#0F1518; border-radius:999px; }}
  .ens-agr {{ margin-inline-start:auto; font-weight:600; }}
  .ens-compact--good .ens-agr {{ color:var(--pos); }}
  .ens-compact--mid  .ens-agr {{ color:var(--warn); }}
  .ens-compact--bad  .ens-agr {{ color:var(--neg); }}

  table.edges, table.acc {{ width:100%; border-collapse:collapse; font-size:12px; }}
  table.edges th, table.edges td,
  table.acc th, table.acc td {{ padding:6px 8px; text-align:right;
    border-bottom:1px solid var(--border); }}
  table.edges th, table.acc th {{ color:var(--muted); font-weight:500; font-size:11px; }}
  table.edges .t-label, table.acc .t-label {{ font-weight:600; color:var(--text); }}
  table.edges .t-edge {{ font-weight:600; }}
  .pos {{ color:var(--pos); }}
  .neg {{ color:var(--neg); }}
  .row--best {{ background:color-mix(in srgb, var(--mint) 8%, transparent); }}
  .row--best .t-label {{ color:var(--mint); }}
  .row--likely {{ background:color-mix(in srgb, var(--accent2) 10%, transparent); }}
  .row--likely .t-label {{ color:var(--accent2); }}
  .row--best.row--likely {{ background:color-mix(in srgb, var(--mint) 6%, color-mix(in srgb, var(--accent2) 10%, transparent)); }}
  .mark {{ display:inline-block; font-size:10px; padding:1px 6px;
    border-radius:999px; margin-inline-start:5px; font-weight:600; }}
  .mark--best {{ background:var(--mint); color:var(--bg); }}
  .mark--likely {{ background:var(--accent2); color:var(--bg); }}

  .info {{ display:inline-block; margin-right:4px;
    width:14px; height:14px; line-height:14px; text-align:center;
    background:var(--border); color:var(--muted);
    border-radius:50%; font-size:10px; cursor:help; }}
  .info:hover {{ background:var(--mint); color:var(--bg); }}

  .exports {{ background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:16px; margin-top:20px; }}
  .exports h2 {{ margin:0 0 6px 0; font-size:15px; color:var(--mint); }}
  .exports__links {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:10px; }}
  .exports__links a {{ padding:6px 12px; border:1px solid var(--mint);
    border-radius:6px; font-size:13px; background:color-mix(in srgb, var(--mint) 8%, transparent); }}
  .exports__links a:hover {{ background:color-mix(in srgb, var(--mint) 20%, transparent); text-decoration:none; }}
  footer {{ margin-top:20px; color:var(--muted); font-size:11px; text-align:center; line-height:1.6; }}
</style>
</head>
<body>
  <header class="top">
    <h1>שכבת מודיעין כמותי — <span>מזג אוויר</span></h1>
    <div class="ts">
      <div class="ts__row"><span class="muted">תאריך</span><strong>{gen_date}</strong></div>
      <div class="ts__row">
        <span class="muted">לונדון</span><strong>{gen_local}</strong>
        <span class="sep">·</span>
        <span class="muted">ישראל</span><strong>{gen_user}</strong>
      </div>
      <div class="ts__row"><span class="age" id="age-indicator" data-ts="{gen_utc_ms}">מחשב גיל…</span></div>
    </div>
  </header>

  {_render_intro()}
  {_render_overview(payload)}
  {_render_performance(payload.get("performance"))}

  {city_cards}

  {_render_accuracy(payload.get("accuracy"))}

  <section class="exports">
    <h2>הורדת נתונים</h2>
    <p class="muted small">הקבצים נוצרים מחדש בכל הרצה. Excel יכול להיצמד ל-CSV דרך Data ⟵ From Web לקבלת רענון אוטומטי.</p>
    <div class="exports__links">
      <a href="performance.xlsx" download>קובץ Excel מלא (5 גיליונות)</a>
      <a href="signals.csv" download>signals.csv</a>
      <a href="forecasts.csv" download>forecasts.csv</a>
      <a href="daily_performance.csv" download>daily_performance.csv</a>
    </div>
  </section>

  <footer>
    <div>תחזיות: Open-Meteo (5 מודלים + 2 אנסמבלים). מחירים: Polymarket Gamma. תצפיות: aviationweather.gov METAR.</div>
    <div>סף קנייה: יתרון 3% ומעלה + הסתברות 30% ומעלה.</div>
  </footer>

  <script>
    (function () {{
      var el = document.getElementById('age-indicator');
      if (!el) return;
      var ts = parseInt(el.getAttribute('data-ts') || '0', 10);
      if (!ts) {{ el.textContent = ''; return; }}
      function fmt(ms) {{
        var s = Math.max(0, Math.floor(ms / 1000));
        if (s < 60) return 'עודכן לפני ' + s + ' שניות';
        var m = Math.floor(s / 60);
        if (m < 60) return 'עודכן לפני ' + m + ' דק׳';
        var h = Math.floor(m / 60);
        return 'עודכן לפני ' + h + ' שעות ו-' + (m % 60) + ' דק׳';
      }}
      function tick() {{
        var age = Date.now() - ts;
        el.textContent = fmt(age);
        el.classList.remove('fresh', 'mid', 'stale');
        if (age < 6 * 60000) el.classList.add('fresh');
        else if (age < 12 * 60000) el.classList.add('mid');
        else el.classList.add('stale');
      }}
      tick(); setInterval(tick, 15000);
    }})();
    setTimeout(function () {{
      try {{
        var u = new URL(location.href);
        u.searchParams.set('_', Date.now().toString());
        location.replace(u.toString());
      }} catch (e) {{ location.reload(); }}
    }}, 300000);
  </script>
</body>
</html>
"""

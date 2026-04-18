"""
רינדור HTML סטטי (RTL, Dark, mint #B5EBBF) לתוצאות הסריקה.
כולל:
  • הסברים inline ו-tooltips לכל מדד
  • סימון ויזואלי של מודלים חריגים (אדום)
  • פאנל דיוק מודלים לאורך זמן
  • טבלת Top-N חוזים לפי הסתברות (נקייה יותר מכל 11 ה-buckets)
"""
import html
from typing import Optional

from config import CITY_NAME_HE, TOP_N_BUCKETS, WEATHER_MODELS

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

# הסברים קצרים שיופיעו בטולטיפ ובמדריך הראשי
HELP = {
    "consensus":     "ממוצע חשבוני של תחזיות המודלים הזמינים באותו יום, לאחר הסרת חריגים.",
    "sigma":         "סטיית תקן בין המודלים. ככל שהיא גבוהה, יש יותר חוסר הסכמה ופחות ביטחון.",
    "available":     "כמה מתוך חמשת המודלים הגיבו ולא סומנו כחריגים.",
    "prob_ours":     "ההסתברות שחישבנו שהטמפ' המקסימלית תיפול בדיוק ב-bucket הזה, לפי התפלגות נורמלית.",
    "market_price":  "המחיר הנוכחי לקניית YES באותו חוזה ב-Polymarket. מייצג את ההסתברות שהשוק מתמחר.",
    "edge":          "הפער בין ההסתברות שלנו למחיר השוק. חיובי גדול = הזדמנות קנייה.",
    "kelly":         "אחוז מומלץ מהבנקרול לפוזיציה, לפי נוסחת קלי (Kelly). חוסם ב-[0,1].",
    "ev":            "תשואה צפויה על כל 1$ שמושקע בחוזה, לפי ההסתברות שלנו.",
    "volume":        "נפח המסחר ב-USD בחוזה מאז פתיחתו. מעיד על נזילות ועומק שוק.",
    "outlier":       "המודל חרג יותר מ-2°C מהחציון של האחרים — הוסר מחישוב הקונצנזוס של היום.",
    "mae":           "שגיאה מוחלטת ממוצעת של המודל מול תצפיות בפועל. נמוך יותר = מדויק יותר.",
    "bias":          "האם המודל נוטה להיות חם מדי (חיובי) או קר מדי (שלילי) בממוצע.",
    "hit_1c":        "אחוז הימים שהמודל חזה בטווח של ±1°C מהמדידה בפועל.",
    "rank_avg":      "דירוג ממוצע. 1 = הכי מדויק באותו יום. נמוך יותר = עקבי יותר.",
    "action":        "המלצת הפעולה על בסיס היתרון הגבוה ביותר בטבלה. הסף לקנייה הוא 3%.",
    "observed":      "הטמפ' המקסימלית שכבר נמדדה היום עד השעה הנוכחית. המודל מתייחס אליה כאל חסם תחתון — המקסימום היומי לא יכול להיות נמוך ממנה.",
    "post_peak":     "סימון שהשיא היומי כבר עבר (התצפית גבוהה מהתחזית לשעות הנותרות). במצב הזה אי-הוודאות קטנה משמעותית.",
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
    """מחזיר טולטיפ קצר עם סימן מידע קטן ליד תווית."""
    return f'<span class="info" title="{_esc(HELP[key])}">ⓘ</span>'


def _render_model_chips(cons: dict) -> str:
    all_models = cons.get("all_models") or {}
    outliers = cons.get("outliers") or {}
    chips = []
    for name in WEATHER_MODELS.keys():
        v = all_models.get(name)
        if v is None:
            chips.append(
                f'<div class="chip chip--off" title="המודל לא החזיר ערך לתאריך הזה">'
                f'<span class="chip__name">{_esc(name)}</span>'
                f'<span class="chip__val">—</span></div>'
            )
        elif name in outliers:
            dev = outliers[name]
            chips.append(
                f'<div class="chip chip--outlier" '
                f'title="חריג: סטיה של {dev:+.1f}°C מהחציון. הוסר מהחישוב.">'
                f'<span class="chip__name">{_esc(name)}</span>'
                f'<span class="chip__val">{v:.1f}°C ⚠</span></div>'
            )
        else:
            chips.append(
                f'<div class="chip">'
                f'<span class="chip__name">{_esc(name)}</span>'
                f'<span class="chip__val">{v:.1f}°C</span></div>'
            )
    return "".join(chips)


def _render_edges_table(edges: list,
                        best_label: Optional[str],
                        likely_label: Optional[str],
                        best_edge_label: Optional[str]) -> str:
    if not edges:
        return '<p class="muted">אין חוזים זמינים לתאריך הזה.</p>'

    # מציגים את TOP_N_BUCKETS הגבוהים בהסתברות שלנו,
    # ותמיד מבטיחים שה-bucket הכי סביר, הפעולה, והיתרון המקסימלי כלולים.
    sorted_by_prob = sorted(edges, key=lambda e: e["our_prob"], reverse=True)
    visible = list(sorted_by_prob[:TOP_N_BUCKETS])
    visible_labels = {e["bucket"]["label"] for e in visible}
    for must_show in (best_label, likely_label, best_edge_label):
        if must_show and must_show not in visible_labels:
            row = next((e for e in edges
                        if e["bucket"]["label"] == must_show), None)
            if row is not None:
                visible.append(row)
                visible_labels.add(must_show)
    # ממיינים לצורך תצוגה: טמפ' עולה
    type_order = {"below": 0, "single": 1, "above": 2}
    visible.sort(key=lambda e: (type_order[e["bucket"]["type"]],
                                e["bucket"]["temp"]))

    rows = []
    for e in visible:
        lbl = e["bucket"]["label"]
        is_best   = best_label   and lbl == best_label
        is_likely = likely_label and lbl == likely_label
        edge_cls = "pos" if e["edge"] > 0 else ("neg" if e["edge"] < 0 else "")
        row_classes = ["row"]
        if is_best:   row_classes.append("row--best")
        if is_likely: row_classes.append("row--likely")
        markers = []
        if is_best:   markers.append('<span class="mark mark--best">פעולה</span>')
        if is_likely: markers.append('<span class="mark mark--likely">הכי סביר</span>')
        marker_html = "".join(markers)
        rows.append(
            f'<tr class="{" ".join(row_classes)}">'
            f'<td class="t-label">{_esc(lbl)} {marker_html}</td>'
            f'<td>{e["our_prob"]*100:.1f}%</td>'
            f'<td>{e["yes_price"]*100:.1f}%</td>'
            f'<td class="t-edge {edge_cls}">{_pct(e["edge"])}</td>'
            f'<td>{e["kelly"]*100:.1f}%</td>'
            f'<td class="{edge_cls}">{_pct(e["ev"])}</td>'
            f'<td class="muted">${e["volume"]:,.0f}</td>'
            f'</tr>'
        )
    total_n = len(edges)
    shown_n = len(visible)
    note = ""
    if shown_n < total_n:
        note = (f'<p class="muted note">מוצגים {shown_n} מתוך {total_n} חוזים. '
                f'כלולים: הטופ לפי הסתברות, ה-bucket הכי סביר לפי המודל, '
                f'החוזה שמניב את ההמלצה, וה-bucket עם היתרון המקסימלי '
                f'(אם זה שונה מהשאר). </p>')
    return f"""
    <table class="edges">
      <thead><tr>
        <th>טמפרטורה (°C)</th>
        <th>הסתברות חזויה {_info('prob_ours')}</th>
        <th>מחיר YES {_info('market_price')}</th>
        <th>יתרון (Edge) {_info('edge')}</th>
        <th>Kelly {_info('kelly')}</th>
        <th>EV ל-$1 {_info('ev')}</th>
        <th>נפח {_info('volume')}</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    {note}
    """


def _render_run(run: dict) -> str:
    cons   = run.get("consensus") or {}
    signal = run.get("signal") or {}
    event  = run.get("event")
    action = signal.get("action", "NO_DATA")
    color  = ACTION_COLOR[action]
    best        = signal.get("best") or {}
    most_likely = signal.get("most_likely") or {}
    best_edge_b = signal.get("best_edge") or {}
    best_label        = (best.get("bucket") or {}).get("label")
    likely_label      = (most_likely.get("bucket") or {}).get("label")
    best_edge_label   = (best_edge_b.get("bucket") or {}).get("label")

    # קוביות משנה קטנות ליד הסיגנל — "הכי סביר" ו"יתרון מקסימלי"
    signal_chips = []
    if likely_label:
        p_ml = most_likely["our_prob"] * 100
        signal_chips.append(
            f'<div class="sigchip sigchip--likely" '
            f'title="הטמפרטורה שהמודל חושב שהכי סבירה, ללא קשר למחיר השוק.">'
            f'<span class="sigchip__label">הכי סביר</span> '
            f'<span class="sigchip__val">{_esc(likely_label)} · {p_ml:.1f}%</span>'
            f'</div>'
        )
    if best_edge_label and best_edge_label != best_label:
        be = best_edge_b
        signal_chips.append(
            f'<div class="sigchip sigchip--edge" '
            f'title="הbucket עם היתרון הגדול ביותר. אם הוא אינו המומלץ — סביר שההסתברות שלו נמוכה מסף 30%.">'
            f'<span class="sigchip__label">יתרון מקסימלי</span> '
            f'<span class="sigchip__val">{_esc(best_edge_label)} · {be["edge"]*100:+.1f}%</span>'
            f'</div>'
        )
    chips_html = (f'<div class="sigchips">{"".join(signal_chips)}</div>'
                  if signal_chips else "")

    if event:
        title = _esc(event.get("title"))
        slug  = _esc(event.get("slug"))
        url   = f"https://polymarket.com/event/{slug}" if slug else "#"
        event_html = (
            f'<div class="event"><span class="muted">אירוע:</span> '
            f'<a href="{url}" target="_blank" rel="noopener">{title}</a></div>'
        )
    else:
        event_html = '<div class="event muted">לא נמצא אירוע Polymarket תואם לתאריך.</div>'

    mu    = cons.get("mean")
    std   = cons.get("std")
    n     = cons.get("n", 0)
    outliers = cons.get("outliers") or {}
    total_models = len(cons.get("all_models") or WEATHER_MODELS)

    outlier_banner = ""
    if outliers:
        names = ", ".join(outliers.keys())
        outlier_banner = (
            f'<div class="banner banner--warn">'
            f'⚠ מודלים חריגים שהוסרו מהחישוב: {_esc(names)}. '
            f'הקונצנזוס מבוסס רק על המודלים המוסכמים. '
            f'</div>'
        )

    # אזהרת אי-התאמה לשוק: כשההסתברות שלנו וה-YES בשוק רחוקים
    # מאוד זה מזה עבור אותו bucket דומיננטי. שני הכיוונים אפשריים:
    # (א) השוק יודע משהו שאנחנו לא (תצפית שטרם נקלטה, מזג אוויר חריג)
    # (ב) המודל שלנו משקלל לא-נכון פרמטרים
    divergence_banner = ""
    if most_likely and most_likely.get("our_prob", 0) > 0.5:
        ours = most_likely["our_prob"]
        mkt  = most_likely["yes_price"]
        if abs(ours - mkt) > 0.30:
            direction = "מעריך את האירוע הזה כהרבה יותר סביר מהשוק" if ours > mkt else "מעריך את האירוע הזה כהרבה פחות סביר מהשוק"
            divergence_banner = (
                f'<div class="banner banner--diverge">'
                f'⚠ אי-התאמה משמעותית לשוק: המודל {direction} '
                f'(שלנו {ours*100:.0f}% מול {mkt*100:.0f}% בשוק). '
                f'ייתכן שהשוק רואה נתוני METAR/מזג אוויר שעדיין לא נקלטו אצלנו, '
                f'או שהמודל שוקל פחות טוב. יש להתייחס להמלצה בזהירות.'
                f'</div>'
            )

    # פאנל תצפית METAR בזמן-אמת (רק ליום הנוכחי שיש לו דיווחי METAR).
    # מוסיפים את ה-METAR הגולמי האחרון (מה שסוחרים בפולי-מארקט ציטטו לאורך כל הדיון),
    # וגם קישור לדף ההיסטוריה של Wunderground — הדף שממנו החוזה מיושב.
    obs = run.get("observation") or {}
    obs_panel = ""
    if obs.get("observed_max_int") is not None:
        om   = obs["observed_max_int"]
        pt   = obs.get("peak_time_local") or "—"
        rpt  = obs.get("report_count", 0)
        lt   = obs.get("latest_time_local") or "—"
        ltemp = obs.get("latest_temp")
        hr   = obs.get("hours_remaining", 0)
        rfc  = obs.get("remaining_forecast_max")
        raw  = obs.get("raw_sample")
        post_peak = rfc is None or om >= rfc
        state_txt = "השיא היומי כבר עבר — התוצאה כמעט נעולה." if post_peak else "השיא היומי עדיין יכול לקרות בשעות שנותרו."
        rem_html = (f'תחזית לשעות שנותרו: <strong>{rfc:.1f}°C</strong>. '
                    if rfc is not None else '')
        latest_html = (f'דיווח אחרון בשעה <strong>{_esc(lt)}</strong>: '
                       f'<strong>{ltemp}°C</strong>. ' if ltemp is not None else '')
        raw_html = (f'<div class="metar-raw">METAR גולמי: <code>{_esc(raw)}</code></div>'
                    if raw else '')
        # קישור לטבלה ההיסטורית של Wunderground — הטבלה שממנה Polymarket מיישב
        wu_date = run["target_date"].replace("-", "-")  # כבר בפורמט נכון
        try:
            ymd = run["target_date"].split("-")
            wu_url = f"https://www.wunderground.com/history/daily/gb/london/EGLC/date/{int(ymd[0])}-{int(ymd[1])}-{int(ymd[2])}"
        except Exception:
            wu_url = "https://www.wunderground.com/history/daily/gb/london/EGLC"
        wu_html = (f'<div class="wu-link">'
                   f'לאימות עצמאי: <a href="{wu_url}" target="_blank" rel="noopener">'
                   f'טבלת ההיסטוריה של Wunderground ל-EGLC</a> (מקור היישוב של Polymarket). '
                   f'שים לב — התצוגה החיה של WU יכולה להראות ערך גבוה יותר מהטבלה '
                   f'ההיסטורית. ההחלטה נעשית לפי הטבלה ההיסטורית ולא לפי התצוגה.'
                   f'</div>')
        obs_panel = (
            f'<div class="banner banner--obs">'
            f'🌡️ <strong>תצפית METAR חיה (תחנת EGLC)</strong>: '
            f'מקסימום שנמדד עד כה <strong>{om}°C</strong> '
            f'(שיא בשעה <strong>{_esc(pt)}</strong>, {rpt} דיווחים). '
            f'{latest_html}'
            f'{rem_html}'
            f'{state_txt} '
            f'{_info("observed")}'
            f'{raw_html}'
            f'{wu_html}'
            f'</div>'
        )

    return f"""
    <section class="card">
      <header class="card__head">
        <h2>תאריך יעד — {_esc(run["target_date"])}</h2>
        {event_html}
      </header>

      <div class="signal" style="--sig:{color}">
        <div class="signal__row">
          <div class="signal__label">המלצה {_info('action')}</div>
          <div class="signal__action">{ACTION_HE[action]}</div>
        </div>
        <div class="signal__rationale">{_esc(signal.get("rationale", ""))}</div>
        {chips_html}
      </div>

      {outlier_banner}
      {obs_panel}
      {divergence_banner}

      <div class="consensus">
        <div class="consensus__stats">
          <div>
            <span class="muted">קונצנזוס (μ) {_info('consensus')}</span>
            <strong>{_fmt(mu, "°C", 2)}</strong>
          </div>
          <div>
            <span class="muted">פיזור בין-מודלים (σ) {_info('sigma')}</span>
            <strong>{_fmt(std, "°C", 2)}</strong>
          </div>
          <div>
            <span class="muted">מודלים זמינים {_info('available')}</span>
            <strong>{n} / {total_models}</strong>
          </div>
        </div>
        <div class="chips">{_render_model_chips(cons)}</div>
      </div>

      {_render_edges_table(run.get("edges") or [],
                           best_label, likely_label, best_edge_label)}
    </section>
    """


def _render_accuracy(acc: Optional[dict]) -> str:
    if not acc or not acc.get("days_measured"):
        return """
        <section class="card card--acc">
          <h2>איכות מודלים לאורך זמן</h2>
          <p class="muted">
            עדיין לא נצברה היסטוריה מספקת. כל יום שחולף נשמר, התצפית בפועל
            נשלפת אוטומטית אחרי סוף היום, והמדדים כאן יתחילו להיבנות.
            צריך לפחות מספר ימים כדי שיהיו מדדים אמינים.
          </p>
        </section>
        """
    rows = []
    # סידור: הכי מדויק (MAE הכי נמוך) קודם
    items = list(acc["models"].items())
    items.sort(key=lambda kv: (kv[1]["mae"] if kv[1]["mae"] is not None else 999))
    for name, s in items:
        if s["n"] == 0:
            rows.append(
                f'<tr><td>{_esc(name)}</td>'
                f'<td class="muted">—</td><td class="muted">—</td>'
                f'<td class="muted">—</td><td class="muted">—</td>'
                f'<td class="muted">0</td></tr>'
            )
            continue
        mae_cls = "pos" if s["mae"] is not None and s["mae"] < 1.0 else ""
        bias_cls = "pos" if s["bias"] is not None and abs(s["bias"]) < 0.3 else ""
        rows.append(
            f'<tr>'
            f'<td class="t-label">{_esc(name)}</td>'
            f'<td class="{mae_cls}">{_fmt(s["mae"], "°C", 2)}</td>'
            f'<td class="{bias_cls}">{_fmt(s["bias"], "°C", 2) if s["bias"] is not None else "—"}</td>'
            f'<td>{_pct(s["hit_1c"], 0, signed=False) if s["hit_1c"] is not None else "—"}</td>'
            f'<td>{_fmt(s["rank_avg"], "", 2)}</td>'
            f'<td class="muted">{s["n"]}</td>'
            f'</tr>'
        )
    c = acc.get("consensus") or {}
    cons_row = ""
    if c.get("n"):
        cons_row = (
            f'<tr class="row--best">'
            f'<td class="t-label">קונצנזוס</td>'
            f'<td>{_fmt(c["mae"], "°C", 2)}</td>'
            f'<td>{_fmt(c["bias"], "°C", 2)}</td>'
            f'<td>{_pct(c["hit_1c"], 0, signed=False) if c["hit_1c"] is not None else "—"}</td>'
            f'<td class="muted">—</td>'
            f'<td class="muted">{c["n"]}</td>'
            f'</tr>'
        )

    return f"""
    <section class="card card--acc">
      <h2>איכות מודלים לאורך זמן</h2>
      <p class="muted">
        לכל יום שחלף אוספים את הטמפרטורה שנמדדה בפועל, משווים לתחזיות שכל מודל
        נתן, ומחשבים מדדי דיוק. אחרי שבוע-שבועיים אפשר יהיה לראות אילו מודלים
        מדויקים יותר בתנאים של EGLC בפועל.
      </p>
      <table class="acc">
        <thead><tr>
          <th>מודל</th>
          <th>שגיאה מוחלטת ממוצעת (MAE) {_info('mae')}</th>
          <th>הטיה ממוצעת {_info('bias')}</th>
          <th>פגיעה בטווח 1°C {_info('hit_1c')}</th>
          <th>דירוג ממוצע {_info('rank_avg')}</th>
          <th>מס' ימים</th>
        </tr></thead>
        <tbody>
          {''.join(rows)}
          {cons_row}
        </tbody>
      </table>
      <p class="muted small">
        MAE נמוך = מדויק יותר. הטיה קרובה לאפס = מודל ניטרלי. דירוג 1 = היה המדויק
        ביותר באותו יום.
      </p>
    </section>
    """


def _render_intro() -> str:
    return """
    <details class="intro">
      <summary>איך לקרוא את הלוח הזה?</summary>
      <div class="intro__body">
        <p>
          המערכת משווה בין תחזית משוקללת של חמישה מודלים מטאורולוגיים לבין המחירים
          שמסחרים סביב "הטמפרטורה המקסימלית בלונדון" בשוק Polymarket. כשהפער
          גדול — המודל מזהה הזדמנות.
        </p>
        <ul>
          <li><strong>קונצנזוס (μ)</strong> — ממוצע תחזיות המודלים לאחר הסרת חריגים.</li>
          <li><strong>פיזור (σ)</strong> — כמה המודלים לא מסכימים. ערך גבוה = פחות ביטחון באיתות.</li>
          <li><strong>יתרון (Edge)</strong> — הפער בין ההסתברות שלנו למחיר בשוק. 3% ומעלה = קנייה.</li>
          <li><strong>Kelly</strong> — אחוז מהבנקרול שמומלץ להשקיע בחוזה בודד.</li>
          <li><strong>מודל חריג (⚠)</strong> — מודל שחרג יותר מ-2°C מהחציון הוסר מהחישוב.</li>
          <li><strong>METAR חי</strong> — המקור הגולמי של דיווחי טמפרטורה מתחנת EGLC, מדווח במעלות שלמות כל 30 דקות. זה המקור ש-Wunderground מכניס לטבלה ההיסטורית שלה, ושממנו Polymarket מיישב.</li>
          <li><strong>איכות מודלים</strong> — טבלת דיוק שנבנית לאורך זמן מול תצפיות בפועל.</li>
        </ul>
        <p class="small">
          <strong style="color:var(--warn)">⚠ מלכודת נפוצה</strong>:
          התצוגה החיה של Wunderground יכולה להראות ערך כמו 17°C כשכל ה-METAR-ים
          של היום דיווחו 16°C. המלצה: לאמת תמיד מול טבלת ההיסטוריה של WU (הקישור מופיע
          בפאנל ה-METAR ליד התצפית) — לא מול הערך החי.
        </p>
        <p class="muted small">
          גלילה אל מעל כל תווית עם סימן ⓘ כדי לקבל הסבר קצר על המדד.
        </p>
      </div>
    </details>
    """


def render_dashboard(payload: dict) -> str:
    runs_html = "".join(_render_run(r) for r in payload.get("runs", []))
    acc_html  = _render_accuracy(payload.get("accuracy"))
    gen_utc_ms = int(payload.get("generated_at_utc_ms") or 0)
    gen_local  = _esc(payload.get("generated_local", "—"))
    gen_user   = _esc(payload.get("generated_user", "—"))
    gen_date   = _esc(payload.get("generated_date_local", ""))
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>שכבת מודיעין כמותי — {_esc(CITY_NAME_HE)}</title>
<style>
  :root {{
    --bg:#0B0F12; --card:#151B20; --border:#1F2932;
    --text:#E8EDF0; --muted:#7A858C;
    --mint:#B5EBBF; --pos:#5FC87A; --neg:#E45858; --warn:#E4A858;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:'Segoe UI', 'Heebo', 'Rubik', system-ui, sans-serif; }}
  body {{ padding:24px; max-width:1200px; margin:0 auto; }}
  header.top {{ display:flex; justify-content:space-between; align-items:flex-start;
    border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:20px; gap:16px; flex-wrap:wrap; }}
  header.top h1 {{ margin:0; font-size:22px; font-weight:600; }}
  header.top h1 span {{ color:var(--mint); }}
  header.top .ts {{ color:var(--muted); font-size:13px; text-align:left;
    display:flex; flex-direction:column; gap:3px; }}
  header.top .ts__row {{ display:flex; gap:6px; align-items:baseline; flex-wrap:wrap; }}
  header.top .ts strong {{ color:var(--text); font-weight:600; }}
  header.top .sep {{ color:var(--border); }}
  header.top .age {{ font-size:12px; padding:2px 8px; border-radius:999px;
    background:var(--border); color:var(--muted); margin-top:2px; }}
  header.top .age.fresh {{ background:color-mix(in srgb, var(--pos) 18%, transparent); color:var(--pos); }}
  header.top .age.mid   {{ background:color-mix(in srgb, var(--warn) 18%, transparent); color:var(--warn); }}
  header.top .age.stale {{ background:color-mix(in srgb, var(--neg) 18%, transparent); color:var(--neg); }}
  .muted {{ color:var(--muted); }}
  .small {{ font-size:12px; }}

  details.intro {{ background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:14px 18px; margin-bottom:20px; }}
  details.intro summary {{ cursor:pointer; color:var(--mint); font-weight:600; }}
  details.intro .intro__body {{ margin-top:10px; line-height:1.65; }}
  details.intro ul {{ padding-inline-start:20px; }}
  details.intro li {{ margin:4px 0; }}

  .card {{ background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:20px; margin-bottom:20px; }}
  .card__head h2 {{ margin:0 0 4px 0; font-size:18px; }}
  .card--acc h2 {{ color:var(--mint); }}

  .event {{ font-size:13px; margin-bottom:14px; }}
  .event a {{ color:var(--mint); text-decoration:none; border-bottom:1px dotted var(--mint); }}

  .signal {{ border-right:4px solid var(--sig);
    background:color-mix(in srgb, var(--sig) 10%, transparent);
    padding:14px 18px; border-radius:8px; margin:14px 0 14px; }}
  .signal__row {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
  .signal__label {{ color:var(--muted); font-size:13px; }}
  .signal__action {{ color:var(--sig); font-size:22px; font-weight:700; letter-spacing:0.5px; }}
  .signal__rationale {{ margin-top:6px; color:var(--text); line-height:1.55; }}

  .banner {{ padding:10px 14px; border-radius:8px; margin:6px 0 14px;
    font-size:13px; border:1px solid; }}
  .banner--warn {{ border-color:var(--warn);
    background:color-mix(in srgb, var(--warn) 10%, transparent);
    color:color-mix(in srgb, var(--warn) 80%, white); }}
  .banner--obs {{ border-color:#6AB4E0;
    background:color-mix(in srgb, #6AB4E0 10%, transparent);
    color:color-mix(in srgb, #9BD3F2 80%, white); line-height:1.7; }}
  .banner--obs strong {{ color:#9BD3F2; }}
  .metar-raw {{ margin-top:8px; font-size:12px; opacity:0.85; }}
  .metar-raw code {{ background:#0B1114; color:var(--mint);
    padding:2px 6px; border-radius:4px; font-family:'Consolas','Courier New',monospace;
    direction:ltr; unicode-bidi:embed; }}
  .wu-link {{ margin-top:8px; font-size:12px; padding-top:8px;
    border-top:1px dashed color-mix(in srgb, #6AB4E0 30%, transparent); }}
  .wu-link a {{ color:#9BD3F2; text-decoration:none; border-bottom:1px dotted #9BD3F2; }}
  .banner--diverge {{ border-color:var(--neg);
    background:color-mix(in srgb, var(--neg) 8%, transparent);
    color:color-mix(in srgb, var(--neg) 75%, white); line-height:1.6; }}

  .consensus {{ display:flex; gap:18px; flex-wrap:wrap;
    align-items:center; margin-bottom:16px; }}
  .consensus__stats {{ display:flex; gap:22px; flex-wrap:wrap; }}
  .consensus__stats div {{ display:flex; flex-direction:column; gap:2px; }}
  .consensus__stats strong {{ font-size:18px; color:var(--text); }}

  .chips {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .chip {{ display:inline-flex; gap:6px; padding:4px 10px; border:1px solid var(--border);
    border-radius:999px; font-size:12px; background:#0F1518; }}
  .chip__name {{ color:var(--muted); }}
  .chip__val  {{ color:var(--mint); font-weight:600; }}
  .chip--off {{ opacity:0.45; }}
  .chip--off .chip__val {{ color:var(--muted); }}
  .chip--outlier {{ border-color:var(--neg); background:color-mix(in srgb, var(--neg) 8%, transparent); }}
  .chip--outlier .chip__val {{ color:var(--neg); }}

  table.edges, table.acc {{ width:100%; border-collapse:collapse;
    font-size:13px; margin-top:8px; }}
  table.edges th, table.edges td,
  table.acc th, table.acc td {{ text-align:right; padding:8px 10px;
    border-bottom:1px solid var(--border); }}
  table.edges th, table.acc th {{ color:var(--muted); font-weight:500; font-size:12px; }}
  table.edges .t-label, table.acc .t-label {{ font-weight:600; color:var(--text); }}
  table.edges .t-edge {{ font-weight:600; }}
  table.edges .pos, table.acc .pos {{ color:var(--pos); }}
  table.edges .neg, table.acc .neg {{ color:var(--neg); }}
  table.edges .row--best {{ background:color-mix(in srgb, var(--mint) 8%, transparent); }}
  table.edges .row--best .t-label {{ color:var(--mint); }}
  table.edges .row--likely {{ background:color-mix(in srgb, #6AB4E0 10%, transparent); }}
  table.edges .row--likely .t-label {{ color:#9BD3F2; }}
  table.edges .row--best.row--likely {{ background:color-mix(in srgb, var(--mint) 6%, color-mix(in srgb, #6AB4E0 10%, transparent)); }}
  table.edges .mark {{ display:inline-block; font-size:10px;
    padding:1px 7px; border-radius:999px; margin-inline-start:6px;
    vertical-align:middle; font-weight:600; letter-spacing:0.3px; }}
  table.edges .mark--best {{ background:var(--mint); color:var(--bg); }}
  table.edges .mark--likely {{ background:#9BD3F2; color:var(--bg); }}
  table.acc .row--best {{ background:color-mix(in srgb, var(--mint) 6%, transparent); }}
  table.acc .row--best .t-label {{ color:var(--mint); font-weight:700; }}
  p.note {{ margin-top:8px; font-size:12px; }}

  .sigchips {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
  .sigchip {{ display:inline-flex; gap:6px; align-items:baseline;
    padding:4px 10px; border-radius:8px; font-size:12px;
    border:1px solid var(--border); background:#0F1518; }}
  .sigchip__label {{ color:var(--muted); }}
  .sigchip__val {{ font-weight:600; }}
  .sigchip--likely .sigchip__val {{ color:#9BD3F2; }}
  .sigchip--edge .sigchip__val {{ color:var(--mint); }}

  .info {{ display:inline-block; margin-right:4px;
    width:14px; height:14px; line-height:14px; text-align:center;
    background:var(--border); color:var(--muted);
    border-radius:50%; font-size:10px; cursor:help; user-select:none; }}
  .info:hover {{ background:var(--mint); color:var(--bg); }}

  footer {{ margin-top:28px; color:var(--muted); font-size:12px; text-align:center; line-height:1.6; }}
</style>
</head>
<body>
  <header class="top">
    <h1>שכבת מודיעין כמותי — <span>{_esc(CITY_NAME_HE)}</span></h1>
    <div class="ts">
      <div class="ts__row">
        <span class="muted">רוענן לאחרונה בתאריך</span>
        <strong>{gen_date}</strong>
      </div>
      <div class="ts__row">
        <span class="muted">לונדון</span><strong>{gen_local}</strong>
        <span class="sep">·</span>
        <span class="muted">ישראל</span><strong>{gen_user}</strong>
      </div>
      <div class="ts__row">
        <span class="age" id="age-indicator" data-ts="{gen_utc_ms}">מחשב גיל הנתונים…</span>
      </div>
    </div>
  </header>

  {_render_intro()}
  {runs_html}
  {acc_html}

  <footer>
    <div>תחזיות: Open-Meteo (חמישה מודלים). מחירים: Polymarket Gamma API. תצפיות: Open-Meteo Archive/ERA5.</div>
    <div>סף קנייה: יתרון של 3% ומעלה. סף חזק: 8% ומעלה.</div>
    <div>הדף מתרענן אוטומטית כל 5 דקות. ניתן לרענן ידנית בכל רגע.</div>
  </footer>

  <script>
    // מונה חי: מראה כמה זמן עבר מאז העדכון האחרון.
    // צבע הכרטיסיה משתנה לפי הגיל: ירוק עד 6 דק', צהוב עד 12 דק', אדום מעבר.
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
        var mm = m % 60;
        return 'עודכן לפני ' + h + ' שעות ו-' + mm + ' דק׳';
      }}

      function tick() {{
        var age = Date.now() - ts;
        el.textContent = fmt(age);
        el.classList.remove('fresh', 'mid', 'stale');
        if (age < 6 * 60000) el.classList.add('fresh');
        else if (age < 12 * 60000) el.classList.add('mid');
        else el.classList.add('stale');
      }}

      tick();
      setInterval(tick, 15000);
    }})();

    // רענון חוזר עם cache-busting כדי לעקוף את ה-CDN של GitHub Pages.
    // meta refresh בלבד לא תמיד חד-פעמי ביחס לקאש.
    setTimeout(function () {{
      try {{
        var u = new URL(location.href);
        u.searchParams.set('_', Date.now().toString());
        location.replace(u.toString());
      }} catch (e) {{
        location.reload();
      }}
    }}, 300000);
  </script>
</body>
</html>
"""

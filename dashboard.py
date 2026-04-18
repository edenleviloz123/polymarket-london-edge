"""
רינדור HTML סטטי (RTL, Dark, mint-green #B5EBBF) לתוצאות הסריקה.
קובץ עצמאי אחד ללא תלויות חיצוניות — מתאים לפריסה ב-GitHub Pages.
"""
import html
from typing import Optional

from config import CITY_NAME_EN, CITY_NAME_HE, WEATHER_MODELS

ACTION_HE = {
    "STRONG_BUY": "קנה (חזק)",
    "BUY":        "קנה",
    "HOLD":       "המתן",
    "AVOID":      "הימנע",
    "NO_DATA":    "אין נתונים",
}
ACTION_COLOR = {
    "STRONG_BUY": "#5FC87A",
    "BUY":        "#B5EBBF",
    "HOLD":       "#7A858C",
    "AVOID":      "#E45858",
    "NO_DATA":    "#3A464E",
}


def _fmt(v: Optional[float], suffix="", digits=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}{suffix}"


def _pct(v: Optional[float], digits=1) -> str:
    if v is None:
        return "—"
    return f"{v*100:+.{digits}f}%"


def _esc(s) -> str:
    return html.escape(str(s), quote=True) if s is not None else ""


def _render_model_chips(cons: dict) -> str:
    all_models = cons.get("all_models") or {}
    chips = []
    for name in WEATHER_MODELS.keys():
        v = all_models.get(name)
        if v is None:
            chips.append(
                f'<div class="chip chip--off" title="המודל לא החזיר ערך">'
                f'<span class="chip__name">{_esc(name)}</span>'
                f'<span class="chip__val">—</span></div>'
            )
        else:
            chips.append(
                f'<div class="chip">'
                f'<span class="chip__name">{_esc(name)}</span>'
                f'<span class="chip__val">{v:.1f}°C</span></div>'
            )
    return "".join(chips)


def _render_edges_table(edges: list, best_label: Optional[str]) -> str:
    if not edges:
        return '<p class="muted">אין חוזים זמינים לתאריך הזה.</p>'
    rows = []
    for e in edges:
        is_best = best_label and e["bucket"]["label"] == best_label
        edge_cls = "pos" if e["edge"] > 0 else ("neg" if e["edge"] < 0 else "")
        row_cls = "row row--best" if is_best else "row"
        rows.append(
            f'<tr class="{row_cls}">'
            f'<td class="t-label">{_esc(e["bucket"]["label"])}</td>'
            f'<td>{e["our_prob"]*100:.1f}%</td>'
            f'<td>{e["yes_price"]*100:.1f}%</td>'
            f'<td class="t-edge {edge_cls}">{_pct(e["edge"])}</td>'
            f'<td>{e["kelly"]*100:.1f}%</td>'
            f'<td>{_pct(e["ev"])}</td>'
            f'<td class="muted">${e["volume"]:,.0f}</td>'
            f'</tr>'
        )
    return f"""
    <table class="edges">
      <thead><tr>
        <th>טמפ׳ (°C)</th>
        <th>הסתברות חזויה</th>
        <th>מחיר YES</th>
        <th>יתרון</th>
        <th>Kelly</th>
        <th>EV ל-$1</th>
        <th>נפח</th>
      </tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """


def _render_run(run: dict) -> str:
    cons   = run.get("consensus") or {}
    signal = run.get("signal") or {}
    event  = run.get("event")
    action = signal.get("action", "NO_DATA")
    color  = ACTION_COLOR[action]
    best   = signal.get("best") or {}
    best_label = (best.get("bucket") or {}).get("label")

    event_html = ""
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

    return f"""
    <section class="card">
      <header class="card__head">
        <h2>תאריך יעד — {_esc(run["target_date"])}</h2>
        {event_html}
      </header>

      <div class="signal" style="--sig:{color}">
        <div class="signal__action">{ACTION_HE[action]}</div>
        <div class="signal__rationale">{_esc(signal.get("rationale", ""))}</div>
      </div>

      <div class="consensus">
        <div class="consensus__stats">
          <div><span class="muted">קונצנזוס (μ)</span><strong>{_fmt(mu, "°C", 2)}</strong></div>
          <div><span class="muted">פיזור בין-מודלים (σ)</span><strong>{_fmt(std, "°C", 2)}</strong></div>
          <div><span class="muted">מודלים זמינים</span><strong>{n} / {len(WEATHER_MODELS)}</strong></div>
        </div>
        <div class="chips">{_render_model_chips(cons)}</div>
      </div>

      {_render_edges_table(run.get("edges") or [], best_label)}
    </section>
    """


def render_dashboard(payload: dict) -> str:
    runs_html = "".join(_render_run(r) for r in payload.get("runs", []))
    generated = _esc(payload.get("generated_at"))
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>שכבת מודיעין כמותי — {_esc(CITY_NAME_HE)} ({_esc(CITY_NAME_EN)})</title>
<style>
  :root {{
    --bg:#0B0F12; --card:#151B20; --border:#1F2932;
    --text:#E8EDF0; --muted:#7A858C;
    --mint:#B5EBBF; --pos:#5FC87A; --neg:#E45858;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; background:var(--bg); color:var(--text);
    font-family:'Segoe UI', 'Heebo', system-ui, sans-serif; }}
  body {{ padding:24px; max-width:1200px; margin:0 auto; }}
  header.top {{ display:flex; justify-content:space-between; align-items:baseline;
    border-bottom:1px solid var(--border); padding-bottom:16px; margin-bottom:24px; }}
  header.top h1 {{ margin:0; font-size:22px; font-weight:600; }}
  header.top h1 span {{ color:var(--mint); }}
  header.top .ts {{ color:var(--muted); font-size:13px; }}
  .muted {{ color:var(--muted); }}
  .card {{ background:var(--card); border:1px solid var(--border);
    border-radius:12px; padding:20px; margin-bottom:20px; }}
  .card__head h2 {{ margin:0 0 4px 0; font-size:18px; }}
  .event {{ font-size:13px; margin-bottom:14px; }}
  .event a {{ color:var(--mint); text-decoration:none; border-bottom:1px dotted var(--mint); }}
  .signal {{ border-right:4px solid var(--sig); background:color-mix(in srgb, var(--sig) 10%, transparent);
    padding:14px 18px; border-radius:8px; margin:14px 0 18px; }}
  .signal__action {{ color:var(--sig); font-size:22px; font-weight:700; letter-spacing:0.5px; }}
  .signal__rationale {{ margin-top:6px; color:var(--text); line-height:1.5; }}
  .consensus {{ display:flex; gap:18px; flex-wrap:wrap; align-items:center; margin-bottom:16px; }}
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
  table.edges {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }}
  table.edges th, table.edges td {{ text-align:right; padding:8px 10px;
    border-bottom:1px solid var(--border); }}
  table.edges th {{ color:var(--muted); font-weight:500; font-size:12px; }}
  table.edges .t-label {{ font-weight:600; color:var(--text); }}
  table.edges .t-edge {{ font-weight:600; }}
  table.edges .pos {{ color:var(--pos); }}
  table.edges .neg {{ color:var(--neg); }}
  table.edges .row--best {{ background:color-mix(in srgb, var(--mint) 8%, transparent); }}
  table.edges .row--best .t-label {{ color:var(--mint); }}
  footer {{ margin-top:32px; color:var(--muted); font-size:12px; text-align:center; }}
  a.code {{ color:var(--mint); }}
</style>
</head>
<body>
  <header class="top">
    <h1>שכבת מודיעין כמותי • <span>{_esc(CITY_NAME_HE)}</span></h1>
    <div class="ts">רוענן לאחרונה: {generated}</div>
  </header>

  {runs_html}

  <footer>
    <div>מקור תחזיות: Open-Meteo • מקור מחירים: Polymarket Gamma API</div>
    <div>היתרון (Edge) = הסתברות חזויה − מחיר YES בשוק. סף קנייה ≥ 3%.</div>
  </footer>
</body>
</html>
"""

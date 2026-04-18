# שכבת מודיעין כמותי — חוזי טמפרטורה בלונדון

מערכת פייתון קטנה וסטטית שבודקת אם חוזי "הטמפרטורה המקסימלית בלונדון" ב-Polymarket
מתומחרים נכון ביחס לתחזית משוקללת מחמישה מודלים מטאורולוגיים עולמיים.

## איך זה עובד

1. **שליפת תחזיות** (`weather.py`) — Open-Meteo, חמישה מודלים במקביל:
   MeteoFrance, ICON, GFS, UKMO, ECMWF. ערכים מאומתים בטווח שפיות, כשלים מסוננים.
2. **קונצנזוס + פיזור** — ממוצע של המודלים הזמינים + סטיית תקן בין-מודלית.
   דורשים ≥3/5 מודלים זמינים כדי לסמוך על האיתות.
3. **גילוי חוזים** (`markets.py`) — קודם דרך slug ישיר
   (`highest-temperature-in-london-on-<month>-<day>-<year>`); אם נכשל, סריקה רחבה
   של עד 1000 אירועים פעילים ב-Polymarket Gamma API.
4. **חישוב Edge** (`edge.py`) — לכל bucket (11°C או פחות, 12°C, ... 21°C ומעלה):
   - `P(bucket) = Φ((t+0.5−μ)/σ) − Φ((t−0.5−μ)/σ)` עם continuity correction
   - `σ אפקטיבי = max(σ בין-מודלית, 0.7)` — חוסר הסכמה מגדיל את אי-הוודאות
   - `Edge = P_חזויה − מחיר YES`
   - Kelly ו-EV לכל חוזה
5. **איתות** — השוואת היתרון הטוב ביותר לסף: `≥3%` קנייה, `≥8%` קנייה חזקה,
   `≤−3%` הימנע, אחרת המתן.
6. **Dashboard** (`dashboard.py`) — HTML סטטי אחד, RTL, Dark, mint green `#B5EBBF`.

## הרצה מקומית

```bash
pip install -r requirements.txt
python main.py
```

פלט: `docs/index.html`, `docs/data.json`, `docs/history.json`.

## פריסה

ה-workflow ב-`.github/workflows/scan.yml` רץ כל 20 דקות ומפרסם ל-GitHub Pages.
יש להפעיל ב-Settings → Pages → "Build and deployment" → Source: **GitHub Actions**.

## מבנה

| קובץ | תפקיד |
|------|-------|
| `config.py`    | קבועים: מיקום, מילות מפתח, ספים |
| `weather.py`   | Open-Meteo multi-model + ולידציה + קונצנזוס |
| `markets.py`   | Gamma API + parsing של buckets + broad scan |
| `edge.py`      | CDF נורמלי לכל bucket, Kelly, EV, סיווג איתות |
| `dashboard.py` | רינדור HTML (RTL, Dark) |
| `main.py`      | Orchestrator |

## הרחבות אפשריות

- **ערים נוספות** — שנה `CITY_NAME_*`, `LAT`, `LON`, `MARKET_CITY_SLUG` ב-`config.py`.
- **סף איתות שונה** — `EDGE_THRESHOLD_BUY`.
- **תחזית למספר ימים** — שנה את `target_dates` ב-`main.py`.

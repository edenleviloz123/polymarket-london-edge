"""
קונפיגורציה מרכזית לשכבת המודיעין הכמותי.
כל פרמטר שמקבלים עליו החלטה מופיע כאן, במקום אחד.
"""
from zoneinfo import ZoneInfo

# ── רשימת הערים לסריקה ───────────────────────────────────
# כל ערך ברשימה הוא מילון עם כל מה שצריך לסרוק עיר:
#   קואורדינטות, אזור זמן, תחנת METAR (קוד ICAO),
#   הכתובת בוונדרגראונד, וה-slug של פולימארקט לאותה עיר.
# ניתן להרחיב ערים נוספות בהמשך באמצעות הוספת מילון נוסף.
CITIES = [
    {
        "key":                  "london",
        "display_name_he":      "לונדון",
        "display_name_en":      "London",
        "lat":                  51.5048,
        "lon":                  0.0495,
        "timezone":             "Europe/London",
        "metar_station":        "EGLC",
        "wu_url_part":          "gb/london/EGLC",
        "polymarket_city_slug": "london",
        "unit":                 "C",
    },
    {
        "key":                  "paris",
        "display_name_he":      "פריז",
        "display_name_en":      "Paris",
        "lat":                  49.0097,   # Charles de Gaulle
        "lon":                  2.5479,
        "timezone":             "Europe/Paris",
        "metar_station":        "LFPG",
        "wu_url_part":          "fr/paris/LFPG",
        "polymarket_city_slug": "paris",
        "unit":                 "C",
    },
]

# העיר ה"ברירת-מחדל" לצורכי שליפות גלובליות (אם מישהו עדיין משתמש).
# בעתיד נסיר את זה כליל.
DEFAULT_CITY = CITIES[0]
TIMEZONE_TZ = ZoneInfo(DEFAULT_CITY["timezone"])

# אזור זמן של המשתמש — מוצג במקביל בדשבורד
USER_TZ_NAME = "Asia/Jerusalem"
USER_TZ = ZoneInfo(USER_TZ_NAME)

# ── חמשת מודלי מזג האוויר הגלובליים ────────────────────────
WEATHER_MODELS = {
    "MeteoFrance": "meteofrance_seamless",
    "ICON":        "icon_seamless",
    "GFS":         "gfs_seamless",
    "UKMO":        "ukmo_seamless",
    "ECMWF":       "ecmwf_ifs025",
}
MIN_MODELS_REQUIRED = 3

# ── פרמטרים להמרת טמפרטורה → הסתברות ──────────────────────
MIN_SIGMA = 0.1

# ── ולידציה ──────────────────────────────────────────────
TEMP_SANITY_MIN = -20.0
TEMP_SANITY_MAX = 45.0

# ── ספי איתות ─────────────────────────────────────────────
EDGE_THRESHOLD_BUY = 0.03
EDGE_THRESHOLD_STRONG = 0.08
MIN_PROB_FOR_BUY = 0.30

PRICE_MIN_TRADABLE = 0.005
PRICE_MAX_TRADABLE = 0.995

# ── Polymarket ────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
BROAD_SCAN_LIMIT = 1000
MARKET_KEYWORDS_REQUIRED = ["temperature"]
MARKET_KEYWORDS_ANY = [c["polymarket_city_slug"] for c in CITIES]

# ── HTTP ─────────────────────────────────────────────────
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
HTTP_BACKOFF = 1.6

# ── Ensemble Prediction Systems ──────────────────────────
OPEN_METEO_ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = {
    "ECMWF EPS": "ecmwf_ifs025",
    "NOAA GEFS": "gfs025",
}
ENSEMBLE_MIN_MEMBERS = 10

# ── סינון חריגים בין-מודלים ───────────────────────────────
OUTLIER_THRESHOLD_C = 2.0

# ── תצוגת חוזים ───────────────────────────────────────────
TOP_N_BUCKETS = 4

# ── מעקב דיוק מודלים לאורך זמן ────────────────────────────
ACCURACY_JSON     = "docs/accuracy.json"
FORECASTS_LOG     = "docs/forecasts.jsonl"
OBSERVATIONS_JSON = "docs/observations.json"
ACCURACY_MAX_DAYS = 60
OBSERVATION_CUTOFF_HOURS = 6
ACCURACY_HIT_WINDOW_C = 1.0

# ── מעקב איתותים (paper trading) ─────────────────────────
SIGNALS_LOG         = "docs/signals.jsonl"
PAPER_BANKROLL_USD  = 100.0      # "בנקרול" תאורטי לחישוב גודל פוזיציות
KELLY_FRACTION      = 0.5        # half-kelly — שמרני, מופחת סיכוי לפשיטת רגל

# ── תפוקה ─────────────────────────────────────────────────
OUTPUT_DIR   = "docs"
OUTPUT_HTML  = "docs/index.html"
OUTPUT_JSON  = "docs/data.json"
HISTORY_JSON = "docs/history.json"
HISTORY_MAX_ENTRIES = 96
